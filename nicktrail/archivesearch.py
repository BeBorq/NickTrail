"""Find old or forgotten profile addresses in the public Wayback Machine index.

Many sites put a number or a tag into the profile address
(`shinden.pl/user/123456-yournick`, `op.gg/lol/summoners/euw/Nick-TAG`), so the
address cannot be built from the nick alone.  The Wayback CDX index lists every
archived address under a prefix; asking it for addresses under one profile
prefix that contain the nick finds such profiles without a key and without
touching the site itself.

Rules:
  * one request per (site, nick), bounded result size, the normal client budget;
  * a hit is an archived address, never proof that the account still exists or
    that it is the user's: it is stored as an unverified candidate;
  * only the nick is sent to archive.org, never e-mail addresses or names.
"""
import json
import re
from urllib.parse import quote, urlencode, urlsplit

API = 'https://web.archive.org/cdx/search/cdx'
LIMIT = 10
NICK = r'[A-Za-z0-9][A-Za-z0-9_.-]{1,62}'

# id -> (display name, CDX prefix).  Prefixes are profile sections only, so a
# match cannot be an unrelated page that merely mentions the nick.
SITES = {
    'shinden': ('Shinden', 'shinden.pl/user/'),
    'opgg': ('OP.GG (LoL)', 'op.gg/lol/summoners/'),
    'opgg-old': ('OP.GG (LoL, stary adres)', 'www.op.gg/summoners/'),
    'leagueofgraphs': ('League of Graphs', 'www.leagueofgraphs.com/summoner/'),
    'ugg': ('U.GG', 'u.gg/lol/profile/'),
    'trackergg': ('Tracker.gg (Valorant)', 'tracker.gg/valorant/profile/riot/'),
    'lubimyczytac': ('Lubimyczytać', 'lubimyczytac.pl/profil/'),
    'steam-id': ('Steam (własny adres)', 'steamcommunity.com/id/'),
    'myanimelist': ('MyAnimeList', 'myanimelist.net/profile/'),
    'filmweb': ('Filmweb', 'www.filmweb.pl/user/'),
}
MAX_USER_SITES = 10


def _user_sites(store, project):
    """Domains the user marked "I have an account here" in mailbox/password hints."""
    if store is None or project is None:
        return {}
    try:
        rows = store.rows("SELECT DISTINCT domain FROM account_hints WHERE project=? AND status='mine' ORDER BY domain LIMIT ?", (project, MAX_USER_SITES))
    except Exception:
        return {}
    out = {}
    for row in rows:
        domain = str(row['domain']).lower()
        if re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}', domain):
            out['domain-' + domain] = (domain, domain + '/')
    return out


def sites(store=None, project=None):
    known = dict(SITES)
    known.update(_user_sites(store, project))
    return [{'id': key, 'name': name, 'prefix': prefix} for key, (name, prefix) in known.items()]


def pattern(nick):
    """Java regex for the CDX filter: the nick as its own part of the address."""
    return '(?i).*[/=_-]' + re.escape(nick).replace('\\-', '-') + '(?:[/_?#&.-].*)?'


def query(prefix, nick):
    return API + '?' + urlencode([('url', prefix), ('matchType', 'prefix'), ('output', 'json'),
                                  ('fl', 'original,timestamp,statuscode'), ('filter', 'statuscode:200'),
                                  ('filter', 'original:' + pattern(nick)), ('collapse', 'urlkey'), ('limit', str(LIMIT))])


def _address(original, prefix, nick):
    """Archived address -> https profile address (cut after the part with the nick), or None."""
    if not isinstance(original, str):
        return None
    raw = original if '://' in original else 'http://' + original
    try:
        p = urlsplit(raw)
        host = (p.hostname or '').lower()
    except ValueError:
        return None
    if not host or p.username or p.password:
        return None
    want_host, _, want_path = prefix.lower().partition('/')
    if host.removeprefix('www.') != want_host.removeprefix('www.'):
        return None
    segments = [s for s in p.path.split('/') if s]
    base = [s for s in want_path.split('/') if s]
    if [s.lower() for s in segments[:len(base)]] != base:
        return None
    own = re.compile(r'(?i)(?<![A-Za-z0-9])' + re.escape(nick) + r'(?![A-Za-z0-9])')
    for index in range(len(base), len(segments)):
        if own.search(segments[index]):
            path = '/' + '/'.join(segments[:index + 1])
            return 'https://' + host + quote(path, safe="/-_.~%@!$&'()*+,;=:")
    return None


def _entry(site):
    if site in SITES:
        return {'name': SITES[site][0], 'prefix': SITES[site][1]}
    domain = site.removeprefix('domain-') if site.startswith('domain-') else ''
    if re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}', domain):
        return {'name': domain, 'prefix': domain + '/'}
    raise ValueError('Nieznana witryna archiwum')


def lookup(term, client):
    from .search import validate_nickname
    site, nick = term.split(':', 1)
    entry = _entry(site)
    nick = validate_nickname(nick)
    if not re.fullmatch(NICK, nick):
        return {'state': 'unsupported', 'matches': [], 'detail': 'Nick za krótki dla wyszukiwania w archiwum'}
    response = client.get(query(entry['prefix'], nick))
    if response['state'] != 'found':
        return response | {'matches': []}
    try:
        rows = json.loads(response['text'] or '[]')
    except ValueError:
        return {'state': 'error', 'matches': [], 'detail': 'Archiwum zwróciło nieczytelną odpowiedź'}
    if not isinstance(rows, list):
        return {'state': 'error', 'matches': [], 'detail': 'Archiwum zwróciło nieczytelną odpowiedź'}
    matches, seen = [], set()
    for row in rows[1:] if rows and rows[0] and rows[0][0] == 'original' else rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        url = _address(row[0], entry['prefix'], nick)
        if not url:
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        stamp = str(row[1])[:8]
        archived = stamp[:4] + '-' + stamp[4:6] + '-' + stamp[6:8] if re.fullmatch(r'\d{8}', stamp) else ''
        matches.append({'url': url, 'evidence': [],
                        'data': {'indexed_only': True, 'discovery_provider': 'Wayback', 'archived_at': archived,
                                 'search_title': entry['name'] + ' — adres w archiwum internetu',
                                 'search_snippet': 'Zapisany w archiwum ' + archived + '. Konto mogło zostać usunięte; nie potwierdza właściciela.'}})
        if len(matches) >= LIMIT:
            break
    if not matches:
        return {'state': 'not_found', 'matches': [], 'detail': entry['name'] + ': brak adresu z tym nickiem w archiwum'}
    return {'state': 'unverified', 'matches': matches,
            'detail': entry['name'] + ': ' + str(len(matches)) + ' adres(y) z archiwum internetu; do sprawdzenia ręcznie'}
