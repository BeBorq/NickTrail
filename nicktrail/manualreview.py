"""Explicit user resolution of an unresolved source. No implicit network or ownership inference."""

import hashlib, json
from urllib.parse import urlsplit
from .storage import SCHEMA_LOCK, now


def key(search, platform, term, mode):
    return hashlib.sha256(
        json.dumps([search, platform, term, mode], separators=(',', ':')).encode()
    ).hexdigest()


def schema(store):
    with SCHEMA_LOCK:
        store.db.execute(
            '''CREATE TABLE IF NOT EXISTS manual_reviews(project INTEGER REFERENCES projects ON DELETE CASCADE,source_key TEXT,search INTEGER REFERENCES searches ON DELETE CASCADE,platform TEXT,term TEXT,mode TEXT,status TEXT,url TEXT,node INTEGER REFERENCES nodes ON DELETE SET NULL,updated TEXT,PRIMARY KEY(project,source_key))'''
        )
        store.db.commit()


def reviews(store, project, search):
    schema(store)
    return {
        r['source_key']: r
        for r in store.rows('SELECT * FROM manual_reviews WHERE project=? AND search=?', (project, search))
    }


def resolve(store, project, search, platform, term, mode, decision, url=None):
    from .search import schema as search_schema
    from .diagnostics import manual_queue
    from .search import results
    from .archives import public_url
    from .identity import identify

    search_schema(store)
    schema(store)
    if decision not in ('mine', 'not_mine', 'unresolved'):
        raise ValueError('Invalid manual decision')
    run = next((r for r in results(store, project) if r['run']['id'] == search), None)
    if run is None:
        raise ValueError('Search belongs to another project')
    k = key(search, platform, term, mode)
    row = next((r for r in manual_queue(run, store) if r.get('source_key') == k), None)
    if row is None:
        raise ValueError('This unresolved source is not in the selected run')
    node = None
    normalized = ''
    if url:
        normalized = public_url(url)
        target = identify(normalized)
        if (
            target['kind'] not in ('profile', 'page')
            or target['kind'] == 'page'
            and target['platform'] in ('X', 'Facebook', 'GitHub')
        ):
            raise ValueError('Paste a public account or personal-page URL, not an application route')
        if row.get('url') and row.get('status') != 'INDEX_ONLY':
            expected = (urlsplit(row['url']).hostname or '').removeprefix('www.')
            actual = (urlsplit(normalized).hostname or '').removeprefix('www.')
            if actual != expected:
                raise ValueError('URL belongs to another service; add it separately as a lead')
        if not row.get('url'):
            from .providers import REGISTRY

            provider = REGISTRY.get(platform)
            if (
                provider
                and provider.scope in ('public_api', 'platform_search')
                and target['platform'] != platform
            ):
                raise ValueError('URL does not match the selected platform')
        node = store.add(project, normalized, seed=False)
        if decision in ('mine', 'not_mine'):
            store.decide(node, decision)
    elif decision != 'unresolved':
        raise ValueError('Public URL required for an ownership decision')
    else:
        previous = reviews(store, project, search).get(k)
        if previous:
            node = previous['node']
            normalized = previous['url']
        elif row.get('node'):
            node = row['node']
            normalized = row.get('url') or ''
    store.execute(
        'INSERT OR REPLACE INTO manual_reviews VALUES(?,?,?,?,?,?,?,?,?,?)',
        (project, k, search, platform, term, mode, decision, normalized, node, now()),
    )
    return {
        'source_key': k,
        'status': decision,
        'url': normalized,
        'node': node,
        'automatic_verification': False,
        'network_calls': 0,
        'note': 'User declaration is separate from automatic profile verification; no links were followed.',
    }
