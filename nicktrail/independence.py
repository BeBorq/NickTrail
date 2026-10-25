"""Conservative source groups; repeated pages or index observations are not corroboration."""

import json
from urllib.parse import urlsplit


def group(node):
    p = urlsplit(node['url'])
    host = (p.hostname or '').removeprefix('www.').casefold()
    if node.get('kind') == 'email':
        return 'email:' + node['url']
    if node.get('kind') == 'profile' and node.get('platform') not in ('Strona', 'Deklaracja'):
        raw = node.get('data', '{}')
        data = json.loads(raw) if isinstance(raw, str) else raw
        stable = data.get('stable_id') if isinstance(data, dict) else None
        if stable:
            return 'account:' + host + ':' + str(stable)
        # One account is one source, whatever view of it was linked (?tab=…, /videos).
        # The platform's canonical profile URL keeps only identifying query values
        # (e.g. Facebook ?id=, Hacker News ?id=, Xbox ?gamertag=).
        from .identity import identify

        try:
            canonical = urlsplit(identify(node['url'])['url'])
        except ValueError:
            canonical = p
        return (
            'account:'
            + host
            + ':'
            + canonical.path.casefold()
            + ('?' + canonical.query if canonical.query else '')
        )
    return 'origin:' + host if host else 'record:' + str(node['id'])


def provenance(snapshot):
    nodes = {n['id']: n for n in snapshot['nodes']}
    return {
        str(e['id']): {
            'origin': e['source_url'],
            'root_source': group(nodes[e['source']]),
            'independence_group': group(nodes[e['source']]),
            'derivation': e.get('method', 'parser'),
            'current': bool(e.get('current', 1)),
            'decision': e.get('decision', 'unknown'),
        }
        for e in snapshot['evidence']
        if e['source'] in nodes
    }


def repeated_descriptions(nodes):
    """Flag identical long public text; neither origin attribution nor identity proof."""
    import hashlib, re, unicodedata

    buckets = {}
    for node in nodes:
        if node.get('state') != 'found' or node.get('ownership') == 'not_mine':
            continue
        raw = node.get('data', {})
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        values = set()
        for field in ('bio', 'description', 'about'):
            value = data.get(field)
            if not isinstance(value, str) or len(value) > 10000:
                continue
            value = ' '.join(unicodedata.normalize('NFC', value).casefold().split())
            if len(value) < 160 or len(re.findall(r'\w+', value)) < 24:
                continue
            values.add(hashlib.sha256(value.encode('utf-8')).hexdigest())
        for value in values:
            buckets.setdefault(value, []).append(node)
    out = []
    seen = set()
    for members in buckets.values():
        ids = tuple(sorted({n['id'] for n in members}))
        if len(ids) < 2 or ids in seen or len({group(n) for n in members}) < 2:
            continue
        seen.add(ids)
        out.append(
            {
                'members': list(ids),
                'kind': 'identical_long_public_description',
                'independent_content_observations': 1,
                'identity_evidence': False,
                'origin_known': False,
                'note': 'Identical text may be copied or self-repeated. Count this text once; independent account links remain separate evidence.',
            }
        )
    return sorted(out, key=lambda row: row['members'])
