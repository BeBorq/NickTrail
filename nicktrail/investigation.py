"""Bounded next-action/review baseline. Rule-based; nothing runs automatically."""

import hashlib, json
from .identity import identify
from .storage import now


def prepare(store, project, limit=8, snapshot=None, ranking=None, criteria=None, terms=None):
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('Planner limit is 1–10')
    from .ranking import evaluate
    from .pools import classify
    from .search import schema

    schema(store)
    snapshot = snapshot if snapshot is not None else store.snapshot(project, scan_limit=0)
    if not snapshot['projects']:
        raise ValueError('Unknown project')
    latest = store.rows('SELECT options FROM searches WHERE project=? ORDER BY id DESC LIMIT 1', (project,))
    opts = json.loads(latest[0]['options']) if latest else {}
    terms = opts.get('_terms', []) if terms is None else terms
    criteria = opts.get('_criteria', {}) if criteria is None else criteria
    rank = ranking if ranking is not None else evaluate(snapshot, criteria, terms)
    pools = classify(snapshot, rank, terms, criteria)
    historical = {e['target'] for e in snapshot['evidence'] if e.get('method') == 'historical_archive'}
    hub_sites = {
        'Linktree',
        'Carrd',
        'about.me',
        'Beacons',
        'Bento',
        'bio.site',
        'Taplink',
        'Gravatar',
        'Keybase',
    }
    actions = []
    from .exposurecontext import context as exposure_context

    exposure = exposure_context(store, project)
    for n in snapshot['nodes']:
        if n['ownership'] != 'unknown' or n['kind'] not in ('profile', 'page') or n['state'] == 'not_found':
            continue
        r = rank['nodes'].get(str(n['id']), {})
        p = pools.get(str(n['id']), {})
        paths = [path for path in r.get('graph_paths', []) if path['kind'] != 'incoming_link']
        if not p.get('primary_visible') and not paths and n['id'] not in historical:
            continue
        # No first-name/fuzzy pollution in the active-review list without public path evidence.
        if (
            not paths
            and n['id'] not in historical
            and r.get('query_match', 0) < 3
            and not (criteria.get('first_name') and criteria.get('last_name') and p.get('primary_visible'))
        ):
            continue
        evidence = sorted({e['id'] for path in paths for e in path['edges'] if e.get('id') is not None})
        groups = {e.get('independence_group', 'unknown') for path in paths for e in path['edges']}
        anchors = {path['anchor'] for path in paths}
        value = (
            12 * min(2, len(anchors))
            + 4 * min(3, len(groups))
            + 3 * min(4, r.get('link_count', 0))
            + 8 * (r.get('query_match', 0) == 3)
        )
        reasons = []
        from urllib.parse import urlsplit

        host = (urlsplit(n['url']).hostname or '').casefold().removeprefix('www.')
        exposure_refs = [e['id'] for e in exposure if host == e['domain'] or host.endswith('.' + e['domain'])]
        if exposure_refs:
            value += 4
            reasons.append(
                'EXPOSURE_SUGGESTS_PLATFORM '
                + ', '.join(exposure_refs)
                + ': metadata only, no identity evidence'
            )
        if len(anchors) >= 2:
            reasons.append('Links may connect more than one reviewed source')
        elif paths:
            reasons.append('Existing current public path to the selected cluster')
        if n['id'] in historical:
            value += 10
            reasons.append('Historical lead needs a current public check')
        if r.get('conflicts'):
            value += 8
            reasons.append('Conflicting or unavailable data needs human review')
        if n['platform'] in hub_sites:
            value += 6
            reasons.append('Public identity hub may reveal declared links')
        if not reasons:
            reasons.append('Exact supplied alias; ownership still unreviewed')
        manual = n['state'] in ('blocked', 'unsupported', 'error')
        kind = (
            'MANUAL_REVIEW'
            if manual
            else (
                'READ_PUBLIC_PROFILE'
                if n['state'] != 'found' or n['id'] in historical
                else 'REVIEW_OWNERSHIP'
            )
        )
        cost = 'manual' if manual or kind == 'REVIEW_OWNERSHIP' else 'bounded_public_read'
        aid = (
            'A'
            + hashlib.sha256(
                json.dumps([n['id'], kind, evidence, n['state'], n['data']], sort_keys=True).encode()
            ).hexdigest()[:16]
        )
        actions.append(
            {
                'id': aid,
                'node': n['id'],
                'platform': n['platform'],
                'url': n['url'],
                'operation': kind,
                'expected_information_value': value,
                'cost': cost,
                'reasons': reasons,
                'evidence_ids': ['E' + str(id) for id in evidence],
                'independent_source_groups': len(groups),
                'current_read_state': n['state'],
                'user_label': 'unknown',
                'limits': (
                    {'queries': 3, 'seconds': 30, 'follow_links': False}
                    if kind == 'READ_PUBLIC_PROFILE'
                    else {'network_requests': 0}
                ),
                'identity_probability': None,
            }
        )
    actions.sort(key=lambda a: (-a['expected_information_value'], a['node']))
    chosen = []
    sources = {}
    for action in actions:
        if sources.get(action['platform'], 0) >= 2:
            continue
        sources[action['platform']] = sources.get(action['platform'], 0) + 1
        chosen.append(action)
        if len(chosen) >= limit:
            break
    payload = {
        'project': project,
        'actions': chosen,
        'policy': {
            'execute_automatically': False,
            'can_create_urls': False,
            'can_change_network_policy': False,
            'user_labels_override': True,
            'maximum_actions': limit,
        },
        'basis': 'deterministic utility baseline, not identity likelihood or a validated learned planner',
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return {'fingerprint': fingerprint, 'plan': payload, 'network_calls': 0}
