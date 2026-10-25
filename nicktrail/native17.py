"""Documented anonymous profile APIs. Only exact returned aliases and public fields."""

import json, re
from urllib.parse import quote, urlsplit
from .adapters import extract

SITES = {
    'RubyGems': ('https://rubygems.org/profiles/', 'https://rubygems.org/api/v1/profiles/', '.json'),
    'HuggingFace': ('https://huggingface.co/', 'https://huggingface.co/api/users/', '/overview'),
    'CratesIO': ('https://crates.io/users/', 'https://crates.io/api/v1/users/', ''),
    'Speedrun': ('https://www.speedrun.com/users/', 'https://www.speedrun.com/api/v1/users/', ''),
}


def lookup_platform(platform, alias, client):
    from .search import validate_nickname

    alias = validate_nickname(alias)
    base, api, suffix = SITES[platform]
    response = client.get(api + quote(alias, safe='') + suffix)
    if response['state'] != 'found':
        return response | {'matches': []}
    final = urlsplit(response.get('url') or api)
    if (
        final.scheme != 'https'
        or final.hostname != urlsplit(api).hostname
        or final.username
        or final.password
    ):
        return {
            'state': 'partial',
            'matches': [],
            'detail': 'REDIRECT_MISMATCH: API left its documented public host',
        }
    body = json.loads(response['text'])
    data = {}
    links = []
    text = ''
    if not isinstance(body, dict):
        return {'state': 'partial', 'matches': [], 'detail': 'PROFILE_SCHEMA_MISMATCH: expected object'}
    if platform == 'RubyGems':
        name = body.get('handle')
        stable = body.get('id')
        # Email is included only when the public API explicitly exposes it.
        text = body.get('email') if isinstance(body.get('email'), str) else ''
    elif platform == 'HuggingFace':
        name = body.get('user')
        stable = body.get('_id')
        if body.get('type') != 'user':
            return {'state': 'partial', 'matches': [], 'detail': 'PROFILE_TYPE_MISMATCH: not a public user'}
        data = {
            'display': body.get('fullname'),
            'bio': body.get('details'),
            'avatar_url': body.get('avatarUrl'),
        }
        text = data.get('bio') or ''
    elif platform == 'CratesIO':
        body = body.get('user')
        if not isinstance(body, dict):
            return {'state': 'partial', 'matches': [], 'detail': 'PROFILE_SCHEMA_MISMATCH: missing user'}
        name = body.get('login')
        stable = body.get('id')
        data = {'display': body.get('name'), 'avatar_url': body.get('avatar')}
        if isinstance(body.get('url'), str):
            links.append(body['url'])
    else:
        body = body.get('data')
        if not isinstance(body, dict):
            return {'state': 'partial', 'matches': [], 'detail': 'PROFILE_SCHEMA_MISMATCH: missing data'}
        names = body.get('names')
        name = names.get('international') if isinstance(names, dict) else None
        stable = body.get('id')
        for field in ('twitch', 'twitter', 'youtube', 'speedrunslive', 'hitbox'):
            value = body.get(field)
            if isinstance(value, dict) and isinstance(value.get('uri'), str):
                links.append(value['uri'])
        assets = body.get('assets')
        icon = assets.get('icon') if isinstance(assets, dict) else None
        if isinstance(icon, dict):
            data['avatar_url'] = icon.get('uri')
    if not isinstance(name, str) or name.casefold() != alias.casefold():
        return {
            'state': 'partial',
            'matches': [],
            'detail': 'PROFILE_ALIAS_MISMATCH: returned alias differs from requested alias',
        }
    valid = (
        type(stable) is int and stable > 0
        if platform in ('RubyGems', 'CratesIO')
        else isinstance(stable, str)
        and bool(re.fullmatch(r'[0-9a-f]{24}' if platform == 'HuggingFace' else r'[A-Za-z0-9]{8}', stable))
    )
    if not valid:
        return {
            'state': 'partial',
            'matches': [],
            'detail': 'PROFILE_SCHEMA_MISMATCH: missing stable public ID',
        }
    url = base + quote(name, safe='')
    evidence = extract(text, url, 'public_profile') if isinstance(text, str) else []
    for link in links:
        evidence += extract('', url, 'public_social_link', links=[link])
    data = {k: v for k, v in data.items() if isinstance(v, str) and v}
    return {
        'state': 'found',
        'matches': [
            {
                'url': url,
                'data': data | {'alias': name, 'stable_id': str(stable), 'public_adapter': platform},
                'evidence': evidence,
            }
        ],
        'detail': 'Exact public API profile; ownership unconfirmed.',
    }


def read(node, client):
    if node.get('kind') != 'profile':
        return {'state': 'unsupported', 'detail': 'Only public profile URLs are supported'}
    alias = urlsplit(node['url']).path.strip('/').split('/')[-1]
    result = lookup_platform(node['platform'], alias, client)
    matches = result.get('matches', [])
    return (
        {
            'state': 'found',
            'canonical_url': matches[0]['url'],
            'data': matches[0]['data'],
            'evidence': matches[0]['evidence'],
        }
        if matches
        else {k: v for k, v in result.items() if k != 'matches'}
    )
