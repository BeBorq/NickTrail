"""Public Gitea-compatible user APIs with strict profile validation."""

import json
import re
from urllib.parse import quote, urlsplit
from .adapters import extract

HOSTS = {'Codeberg': 'codeberg.org', 'Gitea': 'gitea.com'}


def read(node, client):
    host = HOSTS[node['platform']]
    alias = urlsplit(node['url']).path.strip('/')
    if node['kind'] != 'profile' or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}', alias):
        return {'state': 'unsupported', 'detail': 'Adres nie jest profilem użytkownika'}
    result = client.get('https://' + host + '/api/v1/users/' + quote(alias, safe=''))
    if result['state'] != 'found':
        return result
    body = json.loads(result['text'])
    if (
        not isinstance(body, dict)
        or type(body.get('id')) is not int
        or body['id'] <= 0
        or not isinstance(body.get('login'), str)
        or body['login'].casefold() != alias.casefold()
    ):
        raise ValueError('Nieprawidłowy profil forge')
    url = 'https://' + host + '/' + quote(body['login'], safe='')
    evidence = []
    for field in ('description', 'website'):
        text = str(body.get(field) or '')
        if field == 'website' and text and '://' not in text and '.' in text:
            text = 'https://' + text
        evidence.extend(extract(text, url, field))
    return {
        'state': 'found',
        'canonical_url': url,
        'data': {
            'stable_id': str(body['id']),
            'alias': body['login'],
            'display': body.get('full_name'),
            'bio': body.get('description'),
            'declared_location': body.get('location'),
            'avatar_url': body.get('avatar_url'),
        },
        'evidence': evidence,
    }
