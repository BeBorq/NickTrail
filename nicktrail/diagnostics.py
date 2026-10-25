"""Local explanations: no network request and no inferred absence from missing search results."""

import json
from urllib.parse import quote, urlsplit
from .identity import identify, normalize
from .freeprofiles import TEMPLATES
from .stages import phase


def reason(state, detail=''):
    """Prefer explicit adapter diagnostics; HTTP failure never implies absence."""
    text = str(detail).casefold()
    for code, needles in (
        ('LOCAL_BUDGET_EXHAUSTED', ('limit domeny', 'local_domain_budget', 'limit zapytań')),
        ('API_REQUEST_REJECTED', ('http 400',)),
        ('ROBOTS_RESTRICTED', ('robots_restricted', 'robots.txt')),
        ('DNS_ERROR', ('dns_error', 'gaierror', 'name resolution')),
        ('LOGIN_REQUIRED', ('login_required', 'sign in to continue', 'http 401')),
        ('CAPTCHA', ('captcha',)),
        ('REDIRECT_POLICY_BLOCKED', ('redirect_policy_blocked', 'limit przekierowań')),
        ('PARSER_FAILED', ('jsondecodeerror', 'parser_failed', 'parseerror')),
        ('UPSTREAM_DEFINITION_BROKEN', ('upstream_definition_broken',)),
        ('UPSTREAM_INPUT_ERROR', ('upstream_input_error',)),
        ('RATE_LIMITED', ('429', 'retry-after', 'backoff', 'przerwa zalecona')),
        ('JS_REQUIRED', ('javascript', 'js_required')),
        ('REDIRECT_MISMATCH', ('redirect_mismatch', 'przekierowanie do', 'redirect rejected')),
        ('PROFILE_ALIAS_MISMATCH', ('profile_alias_mismatch',)),
        ('PROFILE_SCHEMA_MISMATCH', ('profile_schema_mismatch', 'profile_type_mismatch')),
        ('USERNAME_RULE_REJECTED', ('reguł', 'username_rule_rejected')),
        ('SOFT_404', ('soft_404', 'soft-404')),
    ):
        if any(token in text for token in needles):
            return code
    return {
        'blocked': 'BLOCKED_BY_PLATFORM',
        'error': 'NETWORK_ERROR',
        'partial': 'PROFILE_DETECTOR_REJECTED',
        'unsupported': 'AUTOMATION_UNAVAILABLE',
        'unverified': 'UNVERIFIED_LEAD',
        'not_found': 'LAST_CHECK_NOT_FOUND',
        'pending': 'EXACT_CHECK_PENDING',
    }.get(state, 'UNKNOWN')


def completeness(item, store=None, snapshot=None, pools=None):
    tasks = item['tasks']
    groups = {p: {'total': 0, 'done': 0} for p in ('A_EXACT', 'B_ENRICH', 'D_VARIANTS', 'E_WEAK')}
    counts = {
        s: sum(t['state'] == s for t in tasks)
        for s in ('found', 'not_found', 'partial', 'blocked', 'error', 'unsupported', 'unverified', 'pending')
    }
    for t in tasks:
        g = groups[phase(t['platform'], t['mode'])]
        g['total'] += 1
        g['done'] += t['state'] not in ('pending', 'searching')
    pipeline = json.loads(item['run']['options']).get('_pipeline', {})
    groups['C_LINKS'] = {
        'total': len(pipeline.get('roots', [])),
        'done': pipeline.get('offset', 0),
        'unit': 'roots_in_completed_batches',
    }
    summary = {
        'stages': groups,
        'tasks': len(tasks),
        'outcomes': counts,
        'exact_complete': groups['A_EXACT']['done'] == groups['A_EXACT']['total'],
        'budget_pending': counts['pending'],
        'note': 'Liczniki prób/zadań, nie potwierdzeń właściciela ani pełnego internetu.',
    }
    from .providers import REGISTRY
    from .servicecatalog import services as html_services
    from .extended import services as imported_services
    from .engineconfig import instances
    from .indexes import INDEXES

    options = json.loads(item['run']['options'])
    selected = set(options.get('_platforms', []))
    all_keys = {'provider:' + id for id in REGISTRY if id not in ('Free', 'Extended')}
    all_keys |= {'Free:' + row['id'] for row in html_services()} | {
        'Extended:' + row['id'] for row in imported_services()
    }

    def definition_key(task):
        return (
            task['platform'] + ':' + task['term'].split(':', 1)[0]
            if task['platform'] in ('Free', 'Extended')
            else 'provider:' + task['platform']
        )

    scheduled = {definition_key(t) for t in tasks if t['mode'] != 'enrich'}
    attempted = {
        definition_key(t)
        for t in tasks
        if t['mode'] != 'enrich' and t['state'] not in ('pending', 'searching', 'unsupported')
    }
    selected_keys = {
        key
        for key in all_keys
        if (
            key.split(':', 1)[0] in selected
            if not key.startswith('provider:')
            else key.split(':', 1)[1] in selected
        )
    } | scheduled
    disabled = {
        key
        for key in all_keys
        if key.startswith('provider:') and not REGISTRY[key.split(':', 1)[1]].available()
    }
    eligible = {definition_key(t) for t in tasks if t['mode'] != 'enrich' and t['state'] != 'unsupported'}
    health = __import__('nicktrail.health', fromlist=['latest']).latest(store) if store else {}
    from .healthrevision import fingerprint

    paired = {
        key
        for key, h in health.items()
        if h['confidence'] == 'paired_live_controls'
        and h['status'] in ('FULL', 'EXACT_ONLY')
        and (not h.get('definition_hash') or h['definition_hash'] == fingerprint(key))
    }
    failed = {
        definition_key(t)
        for t in tasks
        if reason(t['state'], t.get('detail', ''))
        in ('PARSER_FAILED', 'PROFILE_SCHEMA_MISMATCH', 'UPSTREAM_DEFINITION_BROKEN')
    }
    summary['definitions'] = {
        'total_catalog_definitions': len(all_keys),
        'selected_definitions': len(selected_keys),
        'eligible_scheduled_definitions': len(eligible),
        'automatically_attempted': len(attempted),
        'scheduled': len(scheduled),
        'disabled_by_configuration': len(disabled),
        'skipped_due_selected_mode_or_scope': len(all_keys - selected_keys),
        'without_operational_check': len(all_keys - set(health)),
        'paired_live_healthy': len(all_keys & paired),
        'broken_detector_definitions': len(
            failed | {key for key, h in health.items() if h['status'] == 'BROKEN'}
        ),
        'note': 'Overlapping definitions may describe the same website. Operational checks are separate from legacy smoke observations; eligibility follows selected scope and username-rule outcomes.',
    }
    ids = {id for task in tasks for id in json.loads(task['nodes'])}
    if store:
        for run_id in pipeline.get('runs', []):
            ids.update(
                r['node']
                for r in store.rows(
                    'SELECT bn.node FROM branch_nodes bn JOIN branch_runs br ON br.id=bn.run WHERE br.id=? AND br.project=?',
                    (run_id, item['run']['project']),
                )
            )
    nodes = {n['id']: n for n in (snapshot or {}).get('nodes', [])}
    verified = {
        id
        for id in ids
        if id in nodes
        and nodes[id]['state'] == 'found'
        and nodes[id]['kind'] in ('profile', 'page')
        and not json.loads(nodes[id]['data']).get('indexed_only')
        and not json.loads(nodes[id]['data']).get('definition_only')
    }
    network_definitions = {
        definition_key(t) for t in tasks if t.get('requests') is not None and t['requests'] > 0
    }
    unknown_network = {
        definition_key(t)
        for t in tasks
        if t['state'] not in ('pending', 'searching') and t.get('requests') is None
    }
    summary['definitions']['automatic_verification_attempts'] = len(attempted)
    summary['definitions']['automatically_attempted'] = (
        len(network_definitions) if not unknown_network else None
    )
    summary['definitions']['known_definitions_with_http_attempts'] = len(network_definitions)
    summary['definitions']['definitions_with_unknown_legacy_request_attribution'] = len(unknown_network)
    summary['network_requests_discovery'] = item['run'].get('requests', 0)
    summary['network_requests_branches'] = sum(
        store.rows('SELECT requests FROM branch_runs WHERE id=? AND project=?', (id, item['run']['project']))[
            0
        ]['requests']
        for id in pipeline.get('runs', [])
        if store
        and store.rows('SELECT 1 FROM branch_runs WHERE id=? AND project=?', (id, item['run']['project']))
    )
    summary['outcome_report'] = {
        'confirmed_profile_existence': len(verified) if snapshot is not None else None,
        'user_marked_mine': sum(nodes[id]['ownership'] == 'mine' for id in verified),
        'likely_or_unverified_leads': sum(
            id in nodes and nodes[id]['state'] in ('partial', 'unverified') for id in ids
        ),
        'confirmed_absent_exact_tasks': sum(
            t['state'] == 'not_found' and phase(t['platform'], t['mode']) == 'A_EXACT' for t in tasks
        ),
        'uncertain_tasks': sum(t['state'] in ('partial', 'unverified') for t in tasks),
        'blocked_tasks': counts['blocked'],
        'rate_limited_tasks': sum(reason(t['state'], t.get('detail', '')) == 'RATE_LIMITED' for t in tasks),
        'manual_checks_remaining': sum(
            not r.get('review') or r['review']['status'] == 'unresolved' for r in manual_queue(item, store)
        ),
        'skipped_due_budget_tasks': counts['pending'] if item['run']['status'] == 'limited' else 0,
        'interrupted_pending_tasks': (
            counts['pending'] if item['run']['status'] in ('paused', 'failed') else 0
        ),
        'visible_candidates': sum(
            (pools or {}).get(str(id), {}).get('primary_visible', False) for id in verified
        ),
        'note': 'Existence is not shared ownership. Task counts and profile counts are different units; blocked/rate-limited/manual categories overlap.',
    }
    terms = options.get('_terms', [])
    done = []
    partial = []
    untouched = []
    for alias in terms:
        related = [
            t
            for t in tasks
            if phase(t['platform'], t['mode']) == 'A_EXACT'
            and (
                t['term'].split(':', 1)[-1] if t['platform'] in ('Free', 'Extended') else t['term']
            ).casefold()
            == alias.casefold()
        ]
        completed = sum(t['state'] not in ('pending', 'searching') for t in related)
        (done if related and completed == len(related) else partial if completed else untouched).append(alias)
    edge_targets = {
        e['target']
        for e in (snapshot or {}).get('evidence', [])
        if e['source'] in ids
        and e.get('current', 1)
        and e.get('method') in ('parser', 'rendered_public_page')
        and e['decision'] != 'rejected'
    }
    aliases = {str(json.loads(nodes[id]['data']).get('alias') or '') for id in edge_targets if id in nodes}
    aliases = {a for a in aliases if a and a.casefold() not in {t.casefold() for t in terms}}
    domains = {
        urlsplit(nodes[id]['url']).hostname
        for id in edge_targets
        if id in nodes and nodes[id]['kind'] in ('profile', 'page')
    }
    summary['aliases'] = {
        'exact_completed': done,
        'exact_partially_completed': partial,
        'exact_not_attempted': untouched,
        'new_alias_leads_from_public_edges': sorted(aliases),
        'linked_domains': sorted(d for d in domains if d),
    }
    summary['source_coverage'] = {
        'indexes': [
            {k: t[k] for k in ('platform', 'state', 'detail')}
            for t in item['sources']
            if t['platform'] in INDEXES or t['platform'] == 'Catalog'
        ],
        'generic_instances': [
            {k: t[k] for k in ('platform', 'state', 'detail')}
            for t in item['sources']
            if t['platform'] in instances()
        ],
        'observed_engine_families': sorted(
            {
                json.loads(nodes[id]['data']).get('public_engine')
                for id in verified
                if json.loads(nodes[id]['data']).get('public_engine')
            }
        ),
    }
    from .protocol import summary as protocol_summary

    summary['protocol'] = protocol_summary(store, item['run']['id'], tasks)
    summary['provider_cooldowns'] = (
        __import__('nicktrail.cooldowns', fromlist=['active']).active(store) if store else []
    )
    summary['scan_mode'] = options.get('_scan_mode', 'CUSTOM')
    return summary


# Why a source needs a human look, in the order the panel shows the groups.
MANUAL_GROUPS = (
    ('captcha', 'CAPTCHA, ochrona anty-bot lub wymagany JavaScript', ('CAPTCHA', 'JS_REQUIRED')),
    ('access', 'Odmowa dostępu (403/401) lub wymagane logowanie', ('BLOCKED_BY_PLATFORM', 'LOGIN_REQUIRED')),
    ('robots', 'Serwis prosi automaty o nieodczytywanie (robots.txt)', ('ROBOTS_RESTRICTED',)),
    ('limit', 'Limit zapytań — można spróbować później', ('RATE_LIMITED', 'LOCAL_BUDGET_EXHAUSTED')),
    ('index', 'Trafienia wyszukiwarek do potwierdzenia', ('INDEX_ONLY', 'UNVERIFIED_LEAD')),
    ('nosearch', 'Serwis bez publicznego wyszukiwania kont', ('NO_PUBLIC_SEARCH', 'AUTOMATION_UNAVAILABLE')),
)


def manual_group(status):
    for order, (group, label, codes) in enumerate(MANUAL_GROUPS):
        if status in codes:
            return {'group': group, 'group_label': label, 'group_order': order}
    return {
        'group': 'other',
        'group_label': 'Inne błędy i niejednoznaczne strony',
        'group_order': len(MANUAL_GROUPS),
    }


def manual_queue(item, store=None):
    from .routes import profile_url
    from .manualreview import key, reviews
    from .indexes import INDEXES

    out = []
    search = item['run']['id']
    project = item['run']['project']
    saved = reviews(store, project, search) if store else {}

    def add(platform, alias, url, status, detail, origin, term, mode, node=None):
        source_key = key(search, origin, term, mode)
        out.append(
            {
                'platform': platform,
                'alias': alias,
                'url': url,
                'status': status,
                'detail': detail,
                'action': 'Ręczna deklaracja własności jest osobna od odczytu. Możesz wkleić publiczny URL; nic nie będzie odczytane automatycznie.',
                'source_key': source_key,
                'search': search,
                'source_platform': origin,
                'term': term,
                'mode': mode,
                'node': node,
                'review': saved.get(source_key),
                'capability_state': (
                    status
                    if status in ('INDEX_ONLY', 'RATE_LIMITED', 'LOGIN_REQUIRED', 'JS_REQUIRED')
                    else (
                        'BLOCKED'
                        if status in ('ROBOTS_RESTRICTED', 'CAPTCHA', 'BLOCKED_BY_PLATFORM')
                        else 'MANUAL'
                    )
                ),
            }
        )

    for t in item['tasks']:
        if t['mode'] == 'enrich':
            continue
        if t['platform'] in INDEXES or t['platform'] in ('Catalog', 'Archive'):
            if t['state'] == 'found':
                ids = json.loads(t['nodes'])
                if store:
                    for id in ids:
                        n = store.node(id)
                        if n['project'] != project:
                            continue
                        add(
                            t['platform'],
                            t['term'],
                            n['url'],
                            'INDEX_ONLY',
                            'Trafienie indeksu bez niezależnego odczytu profilu.',
                            t['platform'],
                            t['term'],
                            t['mode'] + '#node=' + str(id),
                            id,
                        )
                elif ids:
                    add(
                        t['platform'],
                        t['term'],
                        None,
                        'INDEX_ONLY',
                        'Trafienia indeksu wymagają oceny.',
                        t['platform'],
                        t['term'],
                        t['mode'],
                    )
                continue
        if t['state'] not in ('blocked', 'error', 'partial', 'unsupported', 'unverified'):
            continue
        url = None
        alias = t['term']
        service = t['platform']
        if service in ('Free', 'Extended'):
            service, alias = alias.split(':', 1)
            if t['platform'] == 'Free' and service in TEMPLATES:
                url = TEMPLATES[service].format(nick=quote(alias, safe=''))
            elif t['platform'] == 'Extended':
                from .extended import services

                definition = next((s for s in services() if s['id'] == service), None)
                if definition:
                    url = definition['profile_url'].format(nick=quote(alias, safe=''))
                    service = definition['name']
        else:
            url = profile_url(service, alias)
        add(
            service,
            alias,
            url,
            reason(t['state'], t.get('detail', '')),
            t.get('detail', ''),
            t['platform'],
            t['term'],
            t['mode'],
        )
    selected = json.loads(item['run']['options']).get('_platforms', [])
    terms = json.loads(item['run']['options']).get('_terms', [])
    tasked = {t['platform'] for t in item['tasks']}
    for source in item['sources']:
        if (
            source['platform'] in selected
            and source['platform'] not in tasked
            and source['state'] == 'unsupported'
        ):
            for alias in terms or ['']:
                add(
                    source['platform'],
                    alias,
                    profile_url(source['platform'], alias),
                    'NO_PUBLIC_SEARCH',
                    source['detail'],
                    source['platform'],
                    alias,
                    'source',
                )
    # Review utility only: never ownership, existence or an automatic permission to read.
    options = json.loads(item['run']['options'])
    supplied = {str(t).casefold() for t in options.get('_terms', [])}
    from .providers import REGISTRY

    bridges = {
        'keybase',
        'linktree',
        'carrd',
        'about.me',
        'beacons',
        'bento',
        'bio.site',
        'taplink',
        'gravatar',
        'biolink',
        'allmylinks',
    }
    for row in out:
        mode = row['mode'].split('|')[0]
        exact = mode in ('exact', 'probe', 'source') and row['alias'].casefold() in supplied
        provider = REGISTRY.get(row['source_platform'])
        major = bool(provider and provider.supports_exact)
        bridge = row['platform'].casefold() in bridges
        weak = mode in ('related', 'context') or row['status'] == 'INDEX_ONLY'
        score = (
            ((80 if options.get('_lead_sources') else 100) if exact else 20)
            + (40 if major else 0)
            + (20 if bridge else 0)
            - (30 if weak else 0)
        )
        reasons = [
            (
                'Dokładny podany alias'
                if exact and not options.get('_lead_sources')
                else (
                    'Alias z wcześniejszego publicznego odczytu'
                    if exact
                    else 'Słabszy trop wymagający odrębnej oceny'
                )
            )
        ]
        if major:
            reasons.append('Źródło z deklarowanym dokładnym adapterem')
        if bridge:
            reasons.append('Serwis może łączyć kilka profili')
        row.update(
            review_priority=score, priority_reason=' · '.join(reasons), priority_is_identity_confidence=False
        )
    for row in out:
        row.update(manual_group(row['status']))
    out.sort(
        key=lambda row: (
            bool(row['review'] and row['review']['status'] != 'unresolved'),
            -row['review_priority'],
            row['platform'],
            row['alias'],
            row['source_key'],
        )
    )
    return out


def explain(store, project, url, pools=None, search_id=None):
    if pools is None:
        from .ranking import evaluate
        from .pools import classify
        from .search import results as search_results

        recent = search_results(store, project, limit=1)
        settings = json.loads(recent[0]['run']['options']) if recent else {}
        snapshot = store.snapshot(project)
        terms = settings.get('_terms', [])
        criteria = settings.get('_criteria', {})
        pools = classify(snapshot, evaluate(snapshot, criteria, terms), terms, criteria)
    target = identify(url)
    matches = store.rows('SELECT * FROM nodes WHERE project=? AND url=?', (project, target['url']))
    from .search import results

    runs = results(store, project, limit=None if search_id else 1)
    item = (
        next((r for r in runs if r['run']['id'] == search_id), None)
        if search_id
        else (runs[0] if runs else None)
    )
    if matches and search_id:
        scope_ids = {id for t in item['tasks'] for id in json.loads(t['nodes'])} if item else set()
        matches = [n for n in matches if n['id'] in scope_ids]
    if matches:
        node = matches[0]
        pool = (pools or {}).get(str(node['id']), {})
        if node['state'] == 'found':
            code = 'PROFILE_FOUND_BUT_HIDDEN' if pool.get('primary_visible') is False else 'PROFILE_FOUND'
        else:
            code = {
                'blocked': 'BLOCKED_BY_PLATFORM',
                'error': 'NETWORK_ERROR',
                'partial': 'PROFILE_DETECTOR_REJECTED',
                'not_found': 'LAST_READ_NOT_FOUND',
                'unverified': 'UNVERIFIED_LEAD',
                'unsupported': 'MANUAL',
            }.get(node['state'], 'UNKNOWN')
        observation = store.rows(
            'SELECT o.scan,o.state,o.detail,s.started FROM observations o JOIN scans s ON s.id=o.scan WHERE s.project=? AND o.node=? ORDER BY o.scan DESC LIMIT 1',
            (project, node['id']),
        )
        read = observation[0] if observation and observation[0]['state'] == node['state'] else None
        if read and node['state'] != 'found':
            specific = reason(read['state'], read.get('detail', ''))
            if specific not in ('UNKNOWN', 'UNVERIFIED_LEAD'):
                code = specific
        return {
            'url': target['url'],
            'platform': target['platform'],
            'code': code,
            'node': node['id'],
            'state': node['state'],
            'pool': pool,
            'last_matching_read': read,
            'detail': 'Zapisany stan odczytu; szczegół pochodzi wyłącznie z ostatniego zgodnego odczytu. Nie oznacza potwierdzenia tożsamości.',
        }
    if not item:
        return {
            'url': target['url'],
            'code': 'EXACT_CHECK_NOT_SCHEDULED',
            'detail': 'Brak historii wyszukiwania w projekcie.',
        }
    relevant = []
    opts = json.loads(item['run']['options'])
    variant_aliases = [
        r['alias']
        for r in store.rows('SELECT alias FROM search_variants WHERE search=?', (item['run']['id'],))
    ]
    path_alias = urlsplit(target['url']).path.strip('/').split('/')[-1]
    if (
        target['platform'] != 'Strona'
        and path_alias
        and not path_alias.isdigit()
        and target['platform'] not in ('Roblox', 'HackerNews')
        and path_alias.casefold() not in {str(t).casefold() for t in opts.get('_terms', []) + variant_aliases}
    ):
        return {
            'url': target['url'],
            'platform': target['platform'],
            'code': 'EXACT_CHECK_NOT_SCHEDULED',
            'detail': 'Dokładny alias z tego adresu nie był podany w ostatnim wyszukiwaniu.',
        }
    for t in item['tasks']:
        if t['platform'] in ('Free', 'Extended') and t['mode'] != 'enrich':
            site, alias = t['term'].split(':', 1)
            templates = TEMPLATES
            if t['platform'] == 'Extended':
                from .extended import services

                templates = {s['id']: s['profile_url'] for s in services()}
            if site in templates:
                try:
                    same = (
                        identify(templates[site].format(nick=quote(alias, safe='')))['url'] == target['url']
                    )
                except ValueError:
                    same = False
                if same:
                    relevant.append(t)
        elif t['platform'] == target['platform'] and (
            t['mode'].split('|')[0] in ('related', 'context')
            or t['term'].casefold() == path_alias.casefold()
            or target['platform'] in ('Roblox', 'HackerNews')
        ):
            relevant.append(t)
    if not relevant:
        code = 'PLATFORM_NOT_CATALOGUED' if target['platform'] == 'Strona' else 'EXACT_CHECK_NOT_SCHEDULED'
    elif any(t['state'] in ('pending', 'searching') for t in relevant):
        code = (
            'REQUEST_BUDGET_EXHAUSTED'
            if item['run']['status'] == 'limited'
            else (
                'QUEUE_INTERRUPTED'
                if item['run']['status'] in ('paused', 'stopped', 'cancelled')
                else 'EXACT_CHECK_PENDING'
            )
        )
    elif any(t['state'] == 'blocked' for t in relevant):
        code = 'BLOCKED_BY_PLATFORM'
    elif any(t['state'] == 'error' for t in relevant):
        code = 'NETWORK_ERROR'
    elif any(t['state'] == 'partial' for t in relevant):
        code = 'PROFILE_DETECTOR_REJECTED'
    elif any(t['state'] == 'unsupported' for t in relevant):
        code = 'AUTOMATION_UNAVAILABLE'
    else:
        code = (
            'SEARCH_PROVIDER_MISSED'
            if all(phase(t['platform'], t['mode']) != 'A_EXACT' for t in relevant)
            else 'LAST_CHECK_NOT_FOUND'
        )
    specific = [reason(t['state'], t.get('detail', '')) for t in relevant]
    detailed = next(
        (
            r
            for r in specific
            if r
            in {
                'ROBOTS_RESTRICTED',
                'DNS_ERROR',
                'LOGIN_REQUIRED',
                'CAPTCHA',
                'RATE_LIMITED',
                'REDIRECT_POLICY_BLOCKED',
                'PARSER_FAILED',
                'UPSTREAM_DEFINITION_BROKEN',
                'JS_REQUIRED',
                'PROFILE_ALIAS_MISMATCH',
                'PROFILE_SCHEMA_MISMATCH',
                'USERNAME_RULE_REJECTED',
                'SOFT_404',
            }
        ),
        None,
    )
    if detailed and code not in ('EXACT_CHECK_PENDING', 'REQUEST_BUDGET_EXHAUSTED', 'QUEUE_INTERRUPTED'):
        code = detailed
    return {
        'url': target['url'],
        'platform': target['platform'],
        'code': code,
        'tasks': relevant,
        'reasons': list(dict.fromkeys(reason(t['state'], t.get('detail', '')) for t in relevant)),
        'detail': 'Diagnoza ostatniego wyszukiwania; brak trafienia nie jest dowodem braku konta. Porównaj publiczny URL i alias.',
    }
