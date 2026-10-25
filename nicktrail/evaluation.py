"""Offline ranking regression benchmark. Synthetic ground truth, no calibration claim."""

import json
from .ranking import evaluate


def node(id, alias, display='', ownership='unknown'):
    return {
        'id': id,
        'kind': 'profile',
        'ownership': ownership,
        'state': 'found',
        'url': 'https://example.org/' + str(id),
        'data': json.dumps({'alias': alias, 'display': display}),
    }


def builtin_cases():
    cases = []
    for i in range(12):
        base = 'fictional' + str(i)
        nodes = (
            [node(1, 'reference' + str(i))]
            + [node(j, base + 'extra' + str(j)) for j in range(2, 22)]
            + [node(99, base + 'q')]
        )
        cases.append(
            {
                'name': 'exact_alias_' + str(i),
                'snapshot': {'nodes': nodes, 'evidence': [], 'focus': []},
                'query_terms': [base, base + 'q'],
                'criteria': {},
                'candidates': [n['id'] for n in nodes if n['id'] != 1],
                'expected': [99],
            }
        )
    for i in range(6):
        nodes = [node(1, 'ref'), node(2, 'exact'), node(99, 'different')]
        edges = [
            {
                'source': 1,
                'target': 99,
                'relation': 'links',
                'current': 1,
                'decision': 'accepted',
                'method': 'parser',
            }
        ]
        cases.append(
            {
                'name': 'explicit_link_' + str(i),
                'snapshot': {'nodes': nodes, 'evidence': edges, 'focus': [{'node': 1}]},
                'query_terms': ['exact'],
                'criteria': {},
                'candidates': [2, 99],
                'expected': [99],
            }
        )
    for i in range(6):
        nodes = [node(2, 'other', 'Anna Other'), node(99, 'different', 'Anna Fictional')]
        cases.append(
            {
                'name': 'full_name_' + str(i),
                'snapshot': {'nodes': nodes, 'evidence': [], 'focus': []},
                'query_terms': [],
                'criteria': {'first_name': 'Anna', 'last_name': 'Fictional'},
                'candidates': [2, 99],
                'expected': [99],
            }
        )
    return cases + graph_cases()


def graph_cases():
    """Hard negatives and graph bridges; complete fictional relevance labels."""
    cases = []

    def edge(id, a, b, **extra):
        return {
            'id': id,
            'source': a,
            'target': b,
            'relation': 'links',
            'current': 1,
            'decision': 'unknown',
            'method': 'parser',
            'location': 'bio',
        } | extra

    for mode in (
        'bridge',
        'email',
        'personal_site',
        'stale',
        'manual',
        'rejected',
        'quote',
        'blocked_source',
        'provider_home',
        'role_email',
        'hub',
        'imported',
        'depth_bound',
        'duplicate',
        'late_email',
        'mine_anchor',
    ):
        root = node(1, 'reference')
        candidate = node(99, 'different')
        exact = node(2, 'exact')
        middle = node(50, 'shared')
        middle.update(url='https://x.com/shared', platform='X')
        nodes = [root, candidate, exact, middle]
        for n in nodes:
            n.setdefault('platform', 'GitHub')
        edges = [edge(1, 1, 50), edge(2, 99, 50)]
        focus = [{'node': 1}]
        expected = 99
        if mode in ('email', 'role_email', 'late_email'):
            email = node(60, 'contact')
            email.update(
                kind='email',
                url='support@example.org' if mode == 'role_email' else 'fictional-person@example.org',
                platform='Deklaracja',
            )
            nodes.append(email)
            contact = [
                edge(3, 1, 60, relation='public_contact_occurrence'),
                edge(4, 99, 60, relation='public_contact_occurrence'),
            ]
            if mode != 'late_email':
                edges = contact
            else:
                edges += contact
                other = node(98, 'also-different')
                other['platform'] = 'GitHub'
                nodes.append(other)
                edges.append(edge(5, 98, 50))
        if mode == 'personal_site':
            middle.update(kind='page', platform='Strona', url='https://personal.example')
        if mode == 'provider_home':
            middle.update(kind='page', platform='Strona', url='https://github.com')
        if mode == 'stale':
            edges[1]['current'] = 0
        if mode == 'manual':
            edges[1]['method'] = 'manual_observation'
            edges[1]['decision'] = 'accepted'
        if mode == 'imported':
            edges[1]['method'] = 'import_rule'
        if mode == 'rejected':
            edges[1]['decision'] = 'rejected'
        if mode == 'quote':
            edges[1]['context'] = 'quote'
        if mode == 'blocked_source':
            candidate['state'] = 'blocked'
        if mode == 'hub':
            for i in range(70, 80):
                n = node(i, 'hub' + str(i))
                n['platform'] = 'GitHub'
                nodes.append(n)
                edges.append(edge(i, i, 50))
        if mode == 'depth_bound':
            a = node(51, 'a')
            b = node(52, 'b')
            a['platform'] = b['platform'] = 'GitHub'
            nodes.extend([a, b])
            edges = [edge(1, 1, 50), edge(2, 50, 51), edge(3, 51, 52), edge(4, 52, 99)]
        if mode == 'duplicate':
            edges += edges.copy()
        if mode == 'mine_anchor':
            focus = []
            root['ownership'] = 'mine'
        if mode in (
            'stale',
            'manual',
            'rejected',
            'quote',
            'blocked_source',
            'provider_home',
            'role_email',
            'hub',
            'imported',
            'depth_bound',
        ):
            expected = 2
        candidates = [2, 99] + ([98] if mode == 'late_email' else [])
        cases.append(
            {
                'name': 'graph_' + mode,
                'snapshot': {'nodes': nodes, 'evidence': edges, 'focus': focus},
                'query_terms': ['exact'],
                'criteria': {},
                'candidates': candidates,
                'expected': [expected],
            }
        )
    return cases


def benchmark(cases=None):
    cases = builtin_cases() if cases is None else cases
    if not isinstance(cases, list) or not cases or len(cases) > 1000:
        raise ValueError('Wymagana lista 1–1000 przypadków testowych')
    details = []
    for case in cases:
        expected = set(case['expected'])
        candidates = set(case['candidates'])
        if not expected or not expected <= candidates:
            raise ValueError('Brak poprawnych oczekiwanych kandydatów')
        ranked = evaluate(case['snapshot'], case.get('criteria', {}), case.get('query_terms', []))['order']
        ranked = [i for i in ranked if i in candidates]
        positions = [j + 1 for j, i in enumerate(ranked) if i in expected]
        first = min(positions) if positions else None
        metrics = {}
        for k in (1, 3, 5):
            selected = ranked[:k]
            tp = len(set(selected) & expected)
            metrics['precision_at_' + str(k)] = tp / k
            metrics['recall_at_' + str(k)] = tp / len(expected)
            metrics['hit_at_' + str(k)] = bool(tp)
        selected = set(ranked[:5])
        negatives = candidates - expected
        metrics['false_positive_rate_at_5'] = len(selected - expected) / len(negatives) if negatives else 0
        metrics['false_negative_rate_at_5'] = len(expected - selected) / len(expected)
        details.append(
            metrics
            | {
                'name': case['name'],
                'first_correct': first,
                'hit_at_1': first == 1,
                'hit_at_5': first is not None and first <= 5,
                'reciprocal_rank': 1 / first if first else 0,
            }
        )
    summary = {
        key: sum(d[key] for d in details) / len(details)
        for key in details[0]
        if key.startswith(
            ('precision_at_', 'recall_at_', 'false_positive_rate_', 'false_negative_rate_', 'hit_at_')
        )
    }
    return summary | {
        'dataset': 'synthetic regression cases; not a real-world accuracy estimate',
        'cases': len(details),
        'hit_at_1': sum(d['hit_at_1'] for d in details) / len(details),
        'hit_at_5': sum(d['hit_at_5'] for d in details) / len(details),
        'mrr': sum(d['reciprocal_rank'] for d in details) / len(details),
        'details': details,
    }
