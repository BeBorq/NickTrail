"""Opt-in keyed gaming/streaming APIs. Keys live only in the environment.

Each platform here needs a key the user adds themselves and a public profile the
lookup confirms:
  * Twitch  — Helix API (Client-Id + OAuth app token), public channel profile.
  * Xbox    — OpenXBL (xbl.io) API key, public account.xbox.com profile.

A matching handle is a candidate, never proof of ownership.  Nothing is read or
sent without the key, and no secret is ever stored in results.
"""
import json
import os
import re
from urllib.parse import quote, urlsplit, parse_qs

from .adapters import extract

TWITCH_LOGIN = r'[A-Za-z0-9][A-Za-z0-9_]{2,24}'
XBOX_GAMERTAG = r'[A-Za-z0-9][A-Za-z0-9 ]{0,14}'


def configured(platform):
    if platform == 'Twitch':
        return bool(os.environ.get('NICKTRAIL_TWITCH_CLIENT_ID') and os.environ.get('NICKTRAIL_TWITCH_TOKEN'))
    if platform == 'Xbox':
        return bool(os.environ.get('NICKTRAIL_XBOX_KEY'))
    return False


def twitch_lookup(login, client):
    login = str(login).strip()
    if not re.fullmatch(TWITCH_LOGIN, login):
        return {'state': 'unsupported', 'detail': 'Nick nie spełnia reguł Twitch', 'matches': []}
    response = client.get('https://api.twitch.tv/helix/users?login=' + quote(login.lower(), safe=''),
                          headers={'Client-Id': os.environ['NICKTRAIL_TWITCH_CLIENT_ID'],
                                   'Authorization': 'Bearer ' + os.environ['NICKTRAIL_TWITCH_TOKEN']})
    if response['state'] != 'found':
        return response
    body = json.loads(response['text'])
    data = body.get('data')
    if not isinstance(data, list):
        raise ValueError('Nieprawidłowa odpowiedź Twitch')
    d = next((x for x in data if isinstance(x, dict) and str(x.get('login', '')).lower() == login.lower()), None)
    if not d or not str(d.get('id', '')):
        return {'state': 'not_found', 'detail': 'Twitch: brak konta o tym loginie'}
    url = 'https://www.twitch.tv/' + str(d['login']).lower()
    evidence = extract(str(d.get('description') or ''), url, 'bio')
    return {'state': 'found', 'url': url,
            'data': {'avatar_url': d.get('profile_image_url'), 'stable_id': 'twitch:' + str(d['id']),
                     'alias': d.get('login'), 'display': d.get('display_name')},
            'evidence': evidence}


def xbox_lookup(gamertag, client):
    gamertag = str(gamertag).strip()
    if not re.fullmatch(XBOX_GAMERTAG, gamertag):
        return {'state': 'unsupported', 'detail': 'Nieprawidłowy gamertag Xbox', 'matches': []}
    response = client.get('https://xbl.io/api/v2/search/' + quote(gamertag, safe=''),
                          headers={'X-Authorization': os.environ['NICKTRAIL_XBOX_KEY'], 'Accept': 'application/json'})
    if response['state'] != 'found':
        return response
    body = json.loads(response['text'])
    users = body.get('profileUsers')
    if not isinstance(users, list):
        raise ValueError('Nieprawidłowa odpowiedź Xbox')
    for user in users:
        if not isinstance(user, dict):
            continue
        settings = {s.get('id'): s.get('value') for s in user.get('settings', []) if isinstance(s, dict)}
        name = settings.get('Gamertag') or settings.get('ModernGamertag')
        if not isinstance(name, str) or name.lower() != gamertag.lower():
            continue
        url = 'https://account.xbox.com/en-us/profile?gamertag=' + quote(name, safe='')
        evidence = extract(str(settings.get('Bio') or ''), url, 'bio')
        return {'state': 'found', 'url': url,
                'data': {'avatar_url': settings.get('GameDisplayPicRaw'), 'stable_id': 'xbox:' + str(user.get('id')),
                         'alias': name, 'display': settings.get('ModernGamertag') or name},
                'evidence': evidence}
    return {'state': 'not_found', 'detail': 'Xbox: brak dokładnego gamertagu'}


def lookup(nickname, client):
    """Username-style entry point used by discovery (term is the handle)."""
    # The caller passes the platform via the client-independent dispatcher below.
    raise NotImplementedError


def read_gaming(node, client):
    if not configured(node['platform']):
        return {'state': 'unsupported', 'detail': 'Brak wymaganej konfiguracji API'}
    p = urlsplit(node['url'])
    if node['platform'] == 'Twitch':
        return twitch_lookup(p.path.strip('/'), client)
    gamertag = parse_qs(p.query).get('gamertag', [''])[0]
    return xbox_lookup(gamertag, client)
