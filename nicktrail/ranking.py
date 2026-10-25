"""Explainable local preference ranking, not a calibrated identity probability."""

import json
import re
from .context import compare
from .graphsignals import analyze, PUBLIC_METHODS
from .independence import group as source_group

BASE = {
    'alias': 8,
    'display': 12,
    'location': 6,
    'criteria': 10,
    'link': 28,
    'reciprocal': 16,
    'manual': 8,
    'accepted_path': 14,
}
BASE.update(
    criteria_partial=3, alias_variant=4, graph_bridge=22, public_email=36, graph_direct=28, graph_inbound=8
)
BASE.update(identity_group=30, identity_review=10)
LABELS = {
    'alias': 'Ten sam nick co punkt odniesienia',
    'display': 'Zgodne słowa nazwy wyświetlanej',
    'location': 'Zgodna deklaracja lokalizacji',
    'criteria': 'Zgodne dodatkowe kryteria',
    'link': 'Jawny odnośnik z wybranego konta',
    'reciprocal': 'Wzajemne aktualne odnośniki',
    'manual': 'Ręczna obserwacja linku — bez odczytu źródła',
    'accepted_path': 'Zatwierdzony łańcuch odnośników do dwóch kroków',
}
LABELS.update(
    identity_group='W sugerowanej grupie kont z punktem odniesienia lub Twoim kontem (wspólny e-mail, rel=me lub wzajemne deklaracje) — własność niepotwierdzona',
    identity_review='Para do przeglądu z kontem z sugerowanej grupy — słaba poszlaka',
)
LABELS.update(
    graph_inbound='Jednostronny odnośnik obcego profilu do punktu odniesienia — słaba poszlaka',
    graph_bridge='Aktualna ścieżka publicznych odnośników do punktu odniesienia',
    public_email='Ten sam jawnie opublikowany kontakt e-mail w odrębnych źródłach',
    graph_direct='Jawny odnośnik do/z konta wskazanego jako własne',
    criteria_partial='Zgodna tylko część podanych pól nazwy',
    alias_variant='Nick różni się wyłącznie separatorami',
)


def evaluate(snapshot, criteria=None, query_terms=()):
    nodes = snapshot['nodes']
    edges = snapshot['evidence']
    selected = snapshot.get('focus', [])
    root = next(
        (n for n in nodes if selected and n['id'] == selected[0]['node'] and n['ownership'] != 'not_mine'),
        None,
    )
    reference = json.loads(root['data']) if root else {}
    graph = analyze(snapshot)
    # Suggested account groups (entitylinks) are review priority, never identity.
    from .entitylinks import build as identity_build, known_domains

    identity = identity_build(snapshot, known_domains())
    anchors = ({root['id']} if root else set()) | {n['id'] for n in nodes if n['ownership'] == 'mine'}
    from .entitylinks import _claim

    # Addresses your account explicitly declares (website field, rel=me, sameAs)
    # pull their verified group into review priority, still without identity.
    declared = {
        e['target']
        for e in edges
        if e['source'] in anchors
        and e.get('current', 1)
        and e.get('decision') != 'rejected'
        and e.get('context', 'own') == 'own'
        and e.get('method', 'parser') in PUBLIC_METHODS
        and e.get('relation') in ('links', 'claims_ownership')
        and _claim(e)
    }
    declared = {i for i in declared if any(n['id'] == i and n['ownership'] != 'not_mine' for n in nodes)}
    group_members = set()
    for cluster in identity['clusters']:
        ids = set(cluster['members']) | {p for pages in cluster['site_pages'].values() for p in pages}
        if ids & (anchors | declared):
            group_members |= ids
    review_members = (
        {
            x
            for p in identity['pairs']
            if p['tier'] == 'review' and {p['a'], p['b']} & (group_members | anchors)
            for x in (p['a'], p['b'])
        }
        - group_members
        - anchors
    )

    def tokens(text):
        return set(re.findall(r'[^\W_]+', str(text or '').casefold()))

    def features(n):
        data = json.loads(n['data'])
        out = []
        if reference.get('alias') and str(data.get('alias', '')).casefold() == reference['alias'].casefold():
            out.append('alias')
        elif reference.get('alias') and data.get('alias'):
            a = re.sub(r'[-_.]', '', reference['alias'].casefold())
            b = re.sub(r'[-_.]', '', data['alias'].casefold())
            if len(a) >= 4 and a == b:
                out.append('alias_variant')
        words = tokens(reference.get('display'))
        other = tokens(data.get('display'))
        if words and len(words & other) / len(words | other) >= 0.6:
            out.append('display')
        location = str(reference.get('declared_location') or '').strip().casefold()
        if location and location == str(data.get('declared_location') or '').strip().casefold():
            out.append('location')
        matched = compare(data, criteria or {})
        requested = [k for k in ('first_name', 'last_name') if (criteria or {}).get(k)]
        if matched:
            out.append(
                'criteria_partial' if requested and any(k not in matched for k in requested) else 'criteria'
            )
        links = [
            e
            for e in edges
            if root
            and e['source'] == root['id']
            and e['target'] == n['id']
            and e.get('current', 1)
            and e['decision'] != 'rejected'
            and e['relation'] in ('links', 'claims_ownership')
        ]
        automated = [
            e
            for e in links
            if root.get('state') == 'found'
            and e.get('context', 'own') == 'own'
            and e.get('method', 'parser') in PUBLIC_METHODS
        ]
        if automated:
            out.append('link')
        elif any(e.get('method', 'parser') not in PUBLIC_METHODS for e in links):
            out.append('manual')
        if (
            automated
            and n.get('state') == 'found'
            and any(
                e.get('method', 'parser') in PUBLIC_METHODS
                and e['source'] == n['id']
                and e['target'] == root['id']
                and e.get('current', 1)
                and e['decision'] != 'rejected'
                and e['relation'] in ('links', 'claims_ownership')
                for e in edges
            )
        ):
            out.append('reciprocal')
        if root and root.get('state') == 'found' and not links:
            allowed = [
                e
                for e in edges
                if e.get('current', 1)
                and e['decision'] == 'accepted'
                and e['relation'] in ('links', 'claims_ownership')
                and e.get('method', 'parser') in PUBLIC_METHODS
            ]
            intermediates = {e['target'] for e in allowed if e['source'] == root['id']}
            valid = {
                a['id']
                for a in nodes
                if a['ownership'] != 'not_mine'
                and a.get('state') == 'found'
                and a['kind'] in ('profile', 'page')
            }
            if any(e['source'] in intermediates & valid and e['target'] == n['id'] for e in allowed):
                out.append('accepted_path')
        paths = graph.get(n['id'], [])
        if any(p['kind'] == 'shared_public_email' for p in paths):
            out.append('public_email')
        elif any(len(p['edges']) >= 2 for p in paths):
            if 'accepted_path' not in out:
                out.append('graph_bridge')
        elif paths and not links:
            out.append('graph_direct' if any(p['kind'] == 'direct_link' for p in paths) else 'graph_inbound')
        if n['id'] in group_members and not (root and n['id'] == root['id']):
            out.append('identity_group')
        elif n['id'] in review_members:
            out.append('identity_review')
        # Indexed-only or unread profiles cannot gain high rank from matching names alone.
        return out

    fs = {n['id']: features(n) for n in nodes if n['kind'] in ('profile', 'page')}
    training = [
        n
        for n in nodes
        if n['id'] in fs and n['ownership'] in ('mine', 'not_mine') and (not root or n['id'] != root['id'])
    ]
    scores = {}
    valid_ids = {n['id'] for n in nodes if n['ownership'] != 'not_mine'}
    verified_sources = {n['id'] for n in nodes if n.get('state') == 'found' and n['ownership'] != 'not_mine'}
    neighbors = {n['id']: set() for n in nodes}
    for e in edges:
        if (
            e.get('current', 1)
            and e['decision'] != 'rejected'
            and e['relation'] in ('links', 'claims_ownership')
            and e.get('method', 'parser') in PUBLIC_METHODS
            and e.get('context', 'own') == 'own'
            and e['source'] in verified_sources
            and e['source'] != e['target']
            and e['source'] in valid_ids
            and e['target'] in valid_ids
        ):
            neighbors[e['source']].add(e['target'])
            neighbors[e['target']].add(e['source'])
    for n in nodes:
        if n['id'] not in fs:
            continue
        # Leave this candidate out of training; repeated clicks do not duplicate examples.
        examples = [t for t in training if t['id'] != n['id']]
        weights = {}
        for feature, base in BASE.items():
            positive = sum(t['ownership'] == 'mine' and feature in fs[t['id']] for t in examples)
            negative = sum(t['ownership'] == 'not_mine' and feature in fs[t['id']] for t in examples)
            weights[feature] = base * (1 + (positive - negative) / (4 + positive + negative))
        value = min(95, round(sum(weights[f] for f in fs[n['id']]))) if fs[n['id']] else None
        if value is not None and not set(fs[n['id']]) & {
            'link',
            'reciprocal',
            'accepted_path',
            'manual',
            'graph_bridge',
            'public_email',
            'graph_direct',
            'identity_group',
        }:
            value = min(value, 20)
        conflicts = []
        if n['ownership'] == 'not_mine':
            conflicts.append('Odrzucone przez użytkownika; nie rozwija audytu')
        if n.get('state') == 'not_found':
            conflicts.append(
                'Ostatni odczyt wskazuje brak konta pod tym adresem; zapisane dane mogą być historyczne'
            )
        if n.get('state') in ('error', 'blocked', 'partial'):
            conflicts.append('Ostatni odczyt nie potwierdził pełnych aktualnych danych')
        if reference.get('declared_location'):
            own_location = str(json.loads(n['data']).get('declared_location') or '').strip().casefold()
            if own_location and own_location != str(reference['declared_location']).strip().casefold():
                conflicts.append(
                    'Różne deklaracje lokalizacji — możliwa zmiana miejsca lub nieaktualne dane; bez automatycznego odrzucenia'
                )
        if 'criteria_partial' in fs[n['id']]:
            conflicts.append('Zgodna tylko część nazwy; pozostałe pola niepotwierdzone')
        data = json.loads(n['data'])
        terms = {t.strip().casefold() for t in query_terms if isinstance(t, str) and t.strip()}
        alias = str(data.get('alias') or '').casefold()
        display = str(data.get('display') or '').casefold()
        query_match = 3 if alias and alias in terms else 2 if display and display in terms else 0
        if not query_match and alias:
            compact = re.sub(r'[-_.]', '', alias)
            if len(compact) >= 4 and any(compact == re.sub(r'[-_.]', '', t) for t in terms):
                query_match = 1
        full_name = bool(
            (criteria or {}).get('first_name')
            and (criteria or {}).get('last_name')
            and {'first_name', 'last_name'} <= set(compare({'display': data.get('display')}, criteria or {}))
        )
        priority = 4 if full_name else query_match
        sort_reason = (
            'Zgodne imię i nazwisko w nazwie wyświetlanej'
            if full_name
            else (
                'Dokładny nick lub alias z zapytania'
                if query_match == 3
                else (
                    'Dokładna nazwa wyświetlana'
                    if query_match == 2
                    else 'Wariant nicku' if query_match else 'Pozostały kandydat'
                )
            )
        )
        paths = graph.get(n['id'], [])
        if paths and any(p['kind'] != 'incoming_link' for p in paths):
            sort_reason = 'Graf: ' + {
                'shared_public_email': 'ten sam publiczny kontakt',
                'shared_profile': 'odnośniki do tego samego profilu',
                'shared_website': 'wspólna strona',
                'direct_link': 'jawny odnośnik do źródła',
                'public_path': 'łańcuch publicznych odnośników',
            }.get(paths[0]['kind'], 'powiązanie ze źródłem')
        independent_neighbors = {source_group(other) for other in nodes if other['id'] in neighbors[n['id']]}
        scores[str(n['id'])] = {
            'graph_paths': graph.get(n['id'], []),
            'priority': priority,
            'sort_reason': sort_reason,
            'link_count': len(independent_neighbors),
            'raw_link_count': len(neighbors[n['id']]),
            'independence_groups': sorted(independent_neighbors),
            'missing': n.get('state') == 'not_found',
            'confirmed': n['ownership'] == 'mine',
            'conflicts': conflicts,
            'query_match': query_match,
            'score': value,
            'reasons': [LABELS[f] for f in fs[n['id']]],
            'weights': {f: round(weights[f], 2) for f in fs[n['id']]},
            'examples': len(examples),
            'selected': bool(root and n['id'] == root['id']),
            'rejected': n['ownership'] == 'not_mine',
        }

    def order(n):
        r = scores.get(str(n['id']), {})
        strong = bool(
            set(r.get('weights', {}))
            & {
                'link',
                'reciprocal',
                'accepted_path',
                'graph_bridge',
                'public_email',
                'graph_direct',
                'identity_group',
            }
        )
        grouped = 'identity_group' in r.get('weights', {})
        reviewed = 'identity_review' in r.get('weights', {})
        return (
            r.get('rejected', False),
            -int(r.get('confirmed', False)),
            int(r.get('missing', False)),
            -int(strong),
            -int(grouped),
            -(max((p['strength'] for p in r.get('graph_paths', [])), default=28) if strong else 0),
            -int(reviewed),
            -r.get('priority', 0),
            -min(r.get('link_count', 0), 10),
            -(r.get('score') or 0),
            n['id'],
        )

    ordered = [n['id'] for n in sorted((n for n in nodes if str(n['id']) in scores), key=order)]
    return {
        'order': ordered,
        'nodes': scores,
        'examples': len(training),
        'label': 'Wskaźnik dopasowania — nie prawdopodobieństwo tożsamości',
        'reference': root['id'] if root else None,
    }


def promoted_candidates(snapshot, ranking, existing=(), limit=10):
    """Surface successfully read graph discoveries, without mixing unread URL leads into results."""
    if limit <= 0:
        return []
    existing = set(existing)
    nodes = {n['id']: n for n in snapshot['nodes']}
    out = []
    for id in ranking['order']:
        n = nodes[id]
        paths = ranking['nodes'][str(id)].get('graph_paths', [])
        if id in existing or n.get('state') != 'found' or n['ownership'] == 'not_mine':
            continue
        if any(p['kind'] != 'incoming_link' and p['strength'] >= 18 for p in paths):
            out.append(id)
        if len(out) >= limit:
            break
    return out


def focus_results(snapshot, store=None, history_limit=10):
    focus = snapshot.get('focus', [])
    if not focus:
        return {'root': None, 'links': [], 'scans': []}
    root = focus[0]['node']
    related = {root}
    links = []
    for edge in snapshot['evidence']:
        if edge['source'] == root and edge.get('current', 1):
            links.append(edge)
            related.add(edge['target'])
    scans = [
        s
        for s in snapshot['scans']
        if json.loads(s['options']).get('_focus_root') == root
        or root in json.loads(s['options']).get('_targets', [])
    ]
    if store is not None:
        ids = []
        project = store.node(root)['project']
        # Inspect lightweight option rows first; do not load every historical note/body.
        for row in store.db.execute(
            'SELECT id,options FROM scans WHERE project=? ORDER BY id DESC', (project,)
        ):
            options = json.loads(row['options'])
            if options.get('_focus_root') == root or root in options.get('_targets', []):
                ids.append(row['id'])
            if len(ids) >= history_limit:
                break
        scans = (
            store.rows(
                'SELECT * FROM scans WHERE id IN (' + ','.join('?' for _ in ids) + ') ORDER BY id', tuple(ids)
            )
            if ids
            else []
        )

    observations = []
    if scans:
        visited = json.loads(scans[-1].get('visited', '[]'))
        observations = [n for n in snapshot['nodes'] if n['id'] in visited]
    return {
        'root': root,
        'links': links,
        'scans': scans,
        'related': sorted(related),
        'unread': [n['id'] for n in observations if n.get('state') != 'found'],
    }
