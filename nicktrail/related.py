"""Public search results are leads, never identity evidence."""

import json
import re
from urllib.parse import quote, urlsplit
from .identity import identify


def search_related(platform, term, client, contextual=False, page=1, cursor=None):
    if platform == 'GitHub':
        endpoint = (
            'https://api.github.com/search/users?q='
            + quote((term + ' type:user') if contextual else (term + ' in:login type:user'), safe='')
            + '&per_page=10'
        )
    elif platform == 'GitLab':
        endpoint = 'https://gitlab.com/api/v4/users?search=' + quote(term, safe='') + '&per_page=10'
    elif platform == 'Roblox':
        if len(term) < 3:
            return {
                'state': 'unsupported',
                'detail': 'Wyszukiwanie pokrewnych nazw Roblox wymaga co najmniej 3 znaków',
                'matches': [],
            }
        endpoint = (
            'https://users.roblox.com/v1/users/search?keyword='
            + quote(term, safe='')
            + '&limit=10&sortOrder=Asc'
        )
    else:
        return {
            'state': 'unsupported',
            'detail': 'Brak publicznego wyszukiwania podobnych nazw w tym adapterze',
            'matches': [],
        }
    if page > 1:
        endpoint += (
            ('&cursor=' + quote(cursor, safe='')) if platform == 'Roblox' and cursor else '&page=' + str(page)
        )
    result = client.get(endpoint)
    if result['state'] != 'found':
        return result
    body = json.loads(result['text'])
    items = (
        body.get('items')
        if platform == 'GitHub' and isinstance(body, dict)
        else body.get('data') if platform == 'Roblox' and isinstance(body, dict) else body
    )
    if not isinstance(items, list):
        raise ValueError('Nieprawidłowa lista podobnych nazw')
    matches = []
    for item in items[:10]:
        if not isinstance(item, dict) or type(item.get('id')) is not int or item['id'] <= 0:
            raise ValueError('Nieprawidłowy identyfikator kandydata')
        alias = (
            item.get('login')
            if platform == 'GitHub'
            else item.get('username') if platform == 'GitLab' else item.get('name')
        )
        if not isinstance(alias, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,63}', alias):
            raise ValueError('Nieprawidłowy nick kandydata')
        url = (
            'https://github.com/' + alias
            if platform == 'GitHub'
            else (
                'https://gitlab.com/' + alias
                if platform == 'GitLab'
                else f"https://www.roblox.com/users/{item['id']}/profile"
            )
        )
        node = identify(url)
        if node['kind'] != 'profile':
            continue
        matches.append(
            {
                'url': node['url'],
                'data': {
                    'avatar_url': item.get('avatar_url'),
                    'stable_id': str(item['id']),
                    'alias': alias,
                    'display': item.get('displayName', item.get('name')),
                },
                'evidence': [],
            }
        )
        if platform == 'GitHub':
            from .accountentities import api_fields

            matches[-1]['data'].update(api_fields(item))
    detail = (
        'Do 10 wyników wyszukiwarki serwisu dla nazwy „'
        + term
        + '”. Podobieństwo nie jest dowodem wspólnego właściciela; bez paginacji.'
    )
    if isinstance(body, dict) and body.get('incomplete_results'):
        detail += ' API oznaczyło wynik jako niepełny.'
    more = (
        (body.get('total_count', 0) > page * 10)
        if platform == 'GitHub' and isinstance(body, dict)
        else (
            bool(body.get('nextPageCursor'))
            if platform == 'Roblox' and isinstance(body, dict)
            else len(items) >= 10
        )
    )
    return {
        'state': 'found' if matches else 'not_found',
        'detail': detail.replace('bez paginacji', 'strona ' + str(page) + '; do 3 stron'),
        'matches': matches,
        'next_page': page + 1 if more and page < 3 else None,
        'cursor': body.get('nextPageCursor') if isinstance(body, dict) else None,
    }


def terms_for(nickname, aliases=()):
    from .search import validate_nickname

    if not isinstance(aliases, (list, tuple)) or len(aliases) > 4:
        raise ValueError('Dodaj najwyżej 4 znane aliasy')
    terms = []
    for term in [nickname, *aliases]:
        term = validate_nickname(term)
        if term.lower() not in [s.lower() for s in terms]:
            terms.append(term)
    return terms


def alias_suggestions(store, project):
    focused = store.rows('SELECT node FROM focus WHERE project=?', (project,))
    if not focused:
        return []
    root = store.node(focused[0]['node'])
    if root['ownership'] == 'not_mine':
        return []
    nodes = [(root, 'Nick odczytany z wybranego profilu')]
    edges = store.rows(
        "SELECT target FROM evidence WHERE source=? AND current=1 AND decision!='rejected' AND relation='claims_ownership' AND context='own'",
        (root['id'],),
    )
    nodes += [
        (store.node(e['target']), 'Nick z jawnej deklaracji w wybranym profilu; własność niepotwierdzona')
        for e in edges
    ]
    out = []
    for node, reason in nodes:
        if node['kind'] != 'profile' or node['ownership'] == 'not_mine':
            continue
        data = json.loads(node['data'])
        alias = data.get('alias')
        if not alias:
            path = urlsplit(node['url']).path.strip('/').split('/')
            alias = (
                path[-1]
                if node['platform'] != 'Roblox'
                and not (node['platform'] == 'Steam' and path[0] == 'profiles')
                else None
            )
        if (
            isinstance(alias, str)
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}', alias)
            and alias.lower() not in [x['alias'].lower() for x in out]
        ):
            out.append({'alias': alias, 'reason': reason, 'node': node['id']})
    for address in store.rows('SELECT url FROM profile_addresses WHERE node=?', (root['id'],)):
        if address['url'] == root['url'] or root['platform'] not in ('GitHub', 'GitLab', 'DEV', 'Bluesky'):
            continue
        alias = urlsplit(address['url']).path.strip('/').split('/')[-1]
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}', alias) and alias.lower() not in [
            x['alias'].lower() for x in out
        ]:
            out.append(
                {
                    'alias': alias,
                    'reason': 'Historyczna nazwa tego konta; dziś może prowadzić do innego właściciela. Tylko kandydatura.',
                    'node': root['id'],
                }
            )
    # Learn the user's naming scheme from every confirmed account and add related handles.
    confirmed = [x['alias'] for x in out]
    for node in store.rows(
        "SELECT data,url,platform FROM nodes WHERE project=? AND ownership='mine'", (project,)
    ):
        data = json.loads(node['data'])
        alias = data.get('alias')
        if not alias:
            path = urlsplit(node['url']).path.strip('/').split('/')
            alias = path[-1] if path else None
        if isinstance(alias, str):
            confirmed.append(alias)
    from .aliasscheme import scheme

    known = {a.lower() for a in confirmed} | {x['alias'].lower() for x in out}
    for candidate in scheme(confirmed)['candidates']:
        if candidate['alias'].lower() not in known:
            out.append({'alias': candidate['alias'], 'reason': candidate['basis'], 'node': root['id']})
            known.add(candidate['alias'].lower())
    return out[:8]
