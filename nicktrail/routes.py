"""Safe public manual routes. A constructible address is not an existing account."""

import os
from urllib.parse import quote, urlencode
from .search import validate_nickname


def profile_url(platform, alias):
    try:
        alias = validate_nickname(alias)
    except ValueError:
        return None
    q = quote(alias, safe='')
    from .forums import HOSTS
    from .native15 import SITES as old
    from .native17 import SITES as new
    from .engineconfig import instances

    if platform in old | new:
        return (old | new)[platform][0] + q
    if platform in HOSTS:
        return 'https://' + HOSTS[platform] + '/u/' + q
    bases = {
        'GitHub': 'https://github.com/',
        'GitLab': 'https://gitlab.com/',
        'DEV': 'https://dev.to/',
        'Codeberg': 'https://codeberg.org/',
        'Gitea': 'https://gitea.com/',
        'Keybase': 'https://keybase.io/',
        'Lichess': 'https://lichess.org/@/',
        'ChessCom': 'https://www.chess.com/member/',
    }
    if platform in bases:
        return bases[platform] + q
    if platform == 'Twitch':
        return 'https://www.twitch.tv/' + q
    if platform == 'Xbox':
        return 'https://account.xbox.com/en-us/profile?gamertag=' + q
    if platform == 'HackerNews':
        return 'https://news.ycombinator.com/user?' + urlencode({'id': alias})
    if platform == 'Bluesky':
        if '_' in alias:
            return None
        return 'https://bsky.app/profile/' + q + ('' if '.' in alias else '.bsky.social')
    if platform == 'Steam':
        return (
            'https://steamcommunity.com/'
            + ('profiles/' if alias.isdigit() and len(alias) == 17 else 'id/')
            + q
        )
    if platform in instances():
        row = instances()[platform]
        prefix = {
            'gitea': '/',
            'forgejo': '/',
            'gitlab': '/',
            'discourse': '/u/',
            'wordpress': '/author/',
            'lemmy': '/u/',
            'mastodon': '/@',
            'peertube': '/accounts/',
            'mediawiki': '/wiki/User:',
            'nodebb': '/user/',
        }[row['engine']]
        return 'https://' + row['host'] + prefix + q
    return None
