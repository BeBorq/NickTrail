"""Opt-in checks for sensitive-category sites (adult platforms).

Purpose is self-audit: these sites are common in username-lookup tools, and a
person cleaning up their footprint benefits from knowing a public profile with
their handle exists there so they can remove or lock it.

Safety and privacy rules for this module:
  * OFF by default.  Nothing here runs unless the user explicitly selects the
    "Sensitive" source for a search.
  * A found profile is a candidate, exactly like any other platform: a matching
    username never proves the account is the person's.
  * Results are tagged `sensitive` so the panel can hide them by default and the
    exports and the AI packet leave them out unless the user opts in.
  * It uses the ordinary public username-existence probe and the normal robots
    and rate-limit policy.  It bypasses nothing; many of these sites return a
    block or challenge, which simply becomes a manual-check item.
"""

import re
from urllib.parse import quote

CATEGORY = 'adult'
PATTERN = r'[A-Za-z0-9][A-Za-z0-9_.-]{1,62}'

# id -> (display name, profile URL template, live-test status)
SITES = {
    'Pornhub': ('Pornhub', 'https://www.pornhub.com/users/{nick}', 'UNTESTED'),
    'Xvideos': ('XVideos', 'https://www.xvideos.com/profiles/{nick}', 'UNTESTED'),
    'Xhamster': ('xHamster', 'https://xhamster.com/users/{nick}', 'UNTESTED'),
    'Xnxx': ('XNXX', 'https://www.xnxx.com/profiles/{nick}', 'UNTESTED'),
}


HOSTS = {'pornhub.com', 'xvideos.com', 'xhamster.com', 'xnxx.com'}


def is_sensitive_url(url):
    """True for an address on one of the sensitive-category sites (www. ignored)."""
    from urllib.parse import urlsplit

    host = (urlsplit(str(url)).hostname or '').lower()
    return host.removeprefix('www.') in HOSTS


def sites():
    return [
        {
            'id': k,
            'name': v[0],
            'profile_url': v[1],
            'category': CATEGORY,
            'username_pattern': PATTERN,
            'validation': {'live_status': v[2]},
        }
        for k, v in SITES.items()
    ]


def lookup(term, client):
    """Probe one sensitive site for a username; tag any match as sensitive."""
    from .search import validate_nickname
    from .freeprofiles import probe

    site, alias = term.split(':', 1)
    if site not in SITES:
        raise ValueError('Nieznany serwis z kategorii wrażliwej')
    alias = validate_nickname(alias)
    if not re.fullmatch(PATTERN, alias):
        return {'state': 'unsupported', 'detail': 'Nick nie spełnia reguł serwisu', 'matches': []}
    name, template, status = SITES[site]
    service = {
        'id': site,
        'name': name,
        'profile_url': template,
        'username_pattern': PATTERN,
        'detection': {
            'not_found_titles': [
                '404',
                'not found',
                'page not found',
                'user not found',
                'no longer available',
            ]
        },
    }
    result = probe(service, alias, client)
    for match in result.get('matches', []):
        match.setdefault('data', {})
        match['data']['sensitive'] = True
        match['data']['sensitive_category'] = CATEGORY
    return result
