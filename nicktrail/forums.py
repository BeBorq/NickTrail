"""Anonymous public Discourse profiles only. No admin/user-email endpoints."""

import json, re
from urllib.parse import quote, urljoin, urlsplit
from .identity import normalize

HOSTS = {
    'PythonForum': 'discuss.python.org',
    'BlenderForum': 'blenderartists.org',
    'RustForum': 'users.rust-lang.org',
    'MozillaForum': 'discourse.mozilla.org',
    'GNOMEForum': 'discourse.gnome.org',
    'KDEForum': 'discuss.kde.org',
    'JuliaForum': 'discourse.julialang.org',
    'GodotForum': 'forum.godotengine.org',
    'ObsidianForum': 'forum.obsidian.md',
    'HuggingFaceForum': 'discuss.huggingface.co',
    'ProcessingForum': 'discourse.processing.org',
    'DiscourseMeta': 'meta.discourse.org',
}


def read(node, client):
    if node['platform'] not in HOSTS or node['kind'] != 'profile':
        return {'state': 'unsupported', 'detail': 'Adres nie jest obsługiwanym publicznym profilem forum'}
    alias = urlsplit(node['url']).path.strip('/').split('/')[-1]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}', alias):
        return {'state': 'unsupported', 'detail': 'Nieobsługiwany format nazwy forum'}
    host = HOSTS[node['platform']]
    base = 'https://' + host
    url = base + '/u/' + quote(alias, safe='')
    response = client.get(url + '.json')
    if response['state'] != 'found':
        return response
    final = urlsplit(response.get('url') or base)
    if final.hostname != host or final.scheme != 'https':
        return {
            'state': 'partial',
            'detail': 'REDIRECT_POLICY_BLOCKED: odpowiedź spoza wybranej instancji forum',
        }
    body = json.loads(response['text'])
    user = body.get('user') if isinstance(body, dict) else None
    if (
        not isinstance(user, dict)
        or type(user.get('id')) is not int
        or user['id'] <= 0
        or not isinstance(user.get('username'), str)
        or user['username'].casefold() != alias.casefold()
    ):
        return {'state': 'partial', 'detail': 'Brak jednoznacznych publicznych danych żądanego profilu forum'}
    from .adapters import extract

    evidence = []
    for field in ('bio_raw', 'bio_cooked', 'website'):
        value = user.get(field)
        if not isinstance(value, str):
            continue
        if field == 'website' and value and '://' not in value and '.' in value:
            value = 'https://' + value
        evidence += extract(value, url, field)
    avatar = user.get('avatar_template')
    avatar = urljoin(base, avatar.replace('{size}', '64')) if isinstance(avatar, str) else None
    if avatar:
        try:
            avatar = normalize(avatar)
        except ValueError:
            avatar = None
    canonical = base + '/u/' + quote(user['username'], safe='')
    return {
        'state': 'found',
        'canonical_url': canonical,
        'data': {
            'stable_id': str(user['id']),
            'alias': user['username'],
            'display': user.get('name'),
            'bio': user.get('bio_raw'),
            'declared_location': user.get('location'),
            'avatar_url': avatar,
            'public_engine': 'discourse',
            'id_scope': host,
        },
        'evidence': evidence,
        'detail': 'Publiczny profil Discourse; dostęp anonimowy zależy od ustawień forum. Własność niepotwierdzona.',
    }


def lookup(platform, alias, client):
    from .search import validate_nickname

    alias = validate_nickname(alias)
    url = 'https://' + HOSTS[platform] + '/u/' + quote(alias, safe='')
    result = read({'platform': platform, 'kind': 'profile', 'url': url}, client)
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


def python_lookup(alias, client):
    return lookup('PythonForum', alias, client)


def blender_lookup(alias, client):
    return lookup('BlenderForum', alias, client)


def lookup_platform(platform, alias, client):
    return lookup(platform, alias, client)
