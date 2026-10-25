"""Small, opt-in separator transformations. Never guesses names, dates or numeric suffixes."""

import re
from .search import validate_nickname


def proposals(terms, limit=8):
    provided = {t.casefold() for t in terms}
    seen = set(provided)
    out = []
    for seed in terms:
        if not re.search(r'[-_.]', seed) or len(seed) < 4:
            continue
        for separator in ('', '_', '-', '.'):
            alias = re.sub(r'[-_.]+', separator, seed)
            try:
                alias = validate_nickname(alias)
            except ValueError:
                continue
            if alias.casefold() in seen:
                continue
            out.append({'alias': alias, 'source_alias': seed, 'rule': 'provided_alias_separator'})
            seen.add(alias.casefold())
            if len(out) >= limit:
                return out
    return out


def schedule(store, search_id, terms, platforms):
    from .providers import REGISTRY
    from .stages import WEAK_SEARCH
    from .frontier import ordered_services, snapshot

    project = store.rows('SELECT project FROM searches WHERE id=?', (search_id,))[0]['project']
    for proposal in proposals(terms):
        alias = proposal['alias']
        store.execute(
            'INSERT OR IGNORE INTO search_variants VALUES(?,?,?,?)',
            (search_id, alias, proposal['source_alias'], proposal['rule']),
        )
        for platform in platforms:
            if platform == 'Free':
                for service in ordered_services(snapshot(store, project)):
                    store.execute(
                        "INSERT OR IGNORE INTO search_tasks(search,platform,term,mode) VALUES(?,?,?,'variant')",
                        (search_id, platform, service['id'] + ':' + alias),
                    )
            elif (
                platform in REGISTRY
                and platform not in WEAK_SEARCH
                and platform not in ('Extended', 'Steam', 'Mastodon')
                and REGISTRY[platform].available()
            ):
                store.execute(
                    "INSERT OR IGNORE INTO search_tasks(search,platform,term,mode) VALUES(?,?,?,'variant')",
                    (search_id, platform, alias),
                )
