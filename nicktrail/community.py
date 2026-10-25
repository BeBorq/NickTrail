"""Public high-information profiles: Stack Exchange user search and chess APIs."""

import json, re
from urllib.parse import urlencode, urlsplit, quote
from .identity import normalize
from .adapters import extract

STACK = {
    'StackOverflow': ('stackoverflow', 'stackoverflow.com'),
    'SecuritySE': ('security', 'security.stackexchange.com'),
    'SuperUser': ('superuser', 'superuser.com'),
    'AskUbuntu': ('askubuntu', 'askubuntu.com'),
    'GameDevSE': ('gamedev', 'gamedev.stackexchange.com'),
    'MathSE': ('math', 'math.stackexchange.com'),
}


def stack_matches(items, platform):
    if not isinstance(items, list):
        raise ValueError('Nieprawidłowa lista użytkowników')
    site, host = STACK[platform]
    matches = []
    for user in items[:10]:
        if (
            not isinstance(user, dict)
            or type(user.get('user_id')) is not int
            or user['user_id'] <= 0
            or not isinstance(user.get('display_name'), str)
        ):
            continue
        url = 'https://' + host + '/users/' + str(user['user_id'])
        evidence = []
        for field in ('website_url', 'about_me'):
            if isinstance(user.get(field), str):
                evidence += extract(user[field], url, field)
        matches.append(
            {
                'url': url,
                'data': {
                    'stable_id': str(user['user_id']),
                    'display': user['display_name'],
                    'bio': user.get('about_me'),
                    'declared_location': user.get('location'),
                    'avatar_url': user.get('profile_image'),
                    'public_adapter': platform,
                },
                'evidence': evidence,
            }
        )
    return matches


def lookup_platform(platform, term, client):
    if platform in STACK:
        if not isinstance(term, str) or not 1 <= len(term) <= 150:
            raise ValueError('Nieprawidłowa nazwa')
        # Immutable safe filter: default + user.about_me; generated once using /filters/create.
        endpoint = 'https://api.stackexchange.com/2.3/users?' + urlencode(
            {
                'site': STACK[platform][0],
                'inname': term,
                'pagesize': 10,
                'filter': '!SyjNqbwGU2NWZ1y5pj',
                'sort': 'reputation',
            }
        )
        result = client.get(endpoint)
        if result['state'] != 'found':
            return result | {'matches': []}
        body = json.loads(result['text'])
        if not isinstance(body, dict):
            raise ValueError('Nieprawidłowa odpowiedź Stack Exchange')
        if body.get('error_id'):
            return {'state': 'blocked', 'matches': [], 'detail': 'Stack Exchange: API odrzuciło zapytanie.'}
        matches = stack_matches(body.get('items'), platform)
        throttled = bool(body.get('backoff')) or body.get('quota_remaining') == 0
        if throttled and hasattr(client, 'defer_host'):
            client.defer_host('api.stackexchange.com', body.get('backoff', 86400))
        return {
            'state': 'partial' if body.get('has_more') or throttled else 'found' if matches else 'not_found',
            'matches': matches,
            'detail': 'Publiczne wyszukiwanie inname, do 10 wyników; podobna nazwa nie potwierdza osoby.'
            + (' API zaleciło przerwę; kolejne zadania tego hosta odroczone.' if throttled else ''),
        }
    from .search import validate_nickname

    alias = validate_nickname(term)
    url = ('https://lichess.org/@/' if platform == 'Lichess' else 'https://www.chess.com/member/') + quote(
        alias, safe=''
    )
    result = read({'platform': platform, 'url': url, 'kind': 'profile'}, client)
    return result | {
        'matches': (
            [
                {
                    'url': result.get('canonical_url', url),
                    'data': result['data'],
                    'evidence': result.get('evidence', []),
                }
            ]
            if result['state'] == 'found'
            else []
        )
    }


def read(node, client):
    platform = node['platform']
    alias = urlsplit(node['url']).path.strip('/').split('/')[-1]
    if platform in STACK:
        parts = urlsplit(node['url']).path.strip('/').split('/')
        if len(parts) < 2 or parts[0] != 'users' or not parts[1].isdigit():
            return {'state': 'unsupported', 'detail': 'Wymagany numeryczny adres profilu Stack Exchange'}
        id = int(parts[1])
        response = client.get(
            'https://api.stackexchange.com/2.3/users/'
            + str(id)
            + '?'
            + urlencode({'site': STACK[platform][0], 'filter': '!SyjNqbwGU2NWZ1y5pj'})
        )
        if response['state'] != 'found':
            return response
        body = json.loads(response['text'])
        if not isinstance(body, dict):
            raise ValueError('Nieprawidłowa odpowiedź Stack Exchange')
        if body.get('backoff') and hasattr(client, 'defer_host'):
            client.defer_host('api.stackexchange.com', body['backoff'])
        if body.get('error_id'):
            return {'state': 'blocked', 'detail': 'Stack Exchange: błąd API'}
        matches = stack_matches(body.get('items'), platform)
        if not matches:
            return {'state': 'not_found', 'detail': 'Brak publicznego profilu o tym ID'}
        match = next((m for m in matches if m['data']['stable_id'] == str(id)), None)
        if not match:
            return {'state': 'partial', 'detail': 'Odpowiedź dotyczy innego konta'}
        return {
            'state': 'found',
            'canonical_url': match['url'],
            'data': match['data'],
            'evidence': match['evidence'],
        }
    endpoint = (
        'https://lichess.org/api/user/' if platform == 'Lichess' else 'https://api.chess.com/pub/player/'
    ) + quote(alias, safe='')
    result = client.get(endpoint)
    if result['state'] != 'found':
        return result
    body = json.loads(result['text'])
    if (
        not isinstance(body, dict)
        or not isinstance(body.get('username'), str)
        or body['username'].casefold() != alias.casefold()
    ):
        return {'state': 'partial', 'detail': 'Brak jednoznacznych danych żądanego konta'}
    if platform == 'Lichess':
        if not isinstance(body.get('id'), str) or body['id'].casefold() != alias.casefold():
            return {'state': 'partial', 'detail': 'Niezgodne ID Lichess'}
        profile = body.get('profile', {})
        if not isinstance(profile, dict):
            raise ValueError('Nieprawidłowe dane profilu')
        fields = {
            'alias': body['username'],
            'display': profile.get('realName'),
            'bio': profile.get('bio'),
            'declared_location': profile.get('location'),
        }
        base = 'https://lichess.org/@/' + quote(body['username'], safe='')
        evidence = extract(str(profile.get('bio') or ''), base, 'bio') + extract(
            str(profile.get('links') or ''), base, 'links'
        )
        # Lichess id is normalized username, not immutable across account lifecycle.
    else:
        if type(body.get('player_id')) is not int or body['player_id'] <= 0:
            return {'state': 'partial', 'detail': 'Brak ID Chess.com'}
        fields = {
            'stable_id': str(body['player_id']),
            'alias': body['username'],
            'display': body.get('name'),
            'declared_location': body.get('location'),
            'avatar_url': body.get('avatar'),
        }
        base = 'https://www.chess.com/member/' + quote(body['username'], safe='')
        evidence = []
    return {
        'state': 'found',
        'canonical_url': base,
        'data': fields | {'public_adapter': platform},
        'evidence': evidence,
        'detail': 'Publiczny profil API; własność niepotwierdzona.',
    }
