"""Offline imports of your own posts and of Maigret reports. No network calls."""
from .adapters import extract
from .engine import record
from .identity import URL, normalize, identify


def posts(store, source, entries):
    node = store.node(source)
    if not isinstance(entries, list) or len(entries) > 1000: raise ValueError("Wymagana lista do 1000 postów")
    # Validate the whole batch before making changes.
    for post in entries:
        if not isinstance(post, dict) or not isinstance(post.get("text"), str) or len(post["text"]) > 100000:
            raise ValueError("Nieprawidłowy post")
        if post.get("context", "own") not in ("own", "quote", "repost", "reply"):
            raise ValueError("Nieznany kontekst postu")
        for field in ("author", "date", "url"):
            if field in post and not isinstance(post[field], str): raise ValueError("Nieprawidłowe metadane")
        if post.get("url"): normalize(post["url"])
    for post in entries:
        items = extract(post["text"], post.get("url") or node["url"], "imported_post", post.get("context", "own"))
        for item in items:
            item.update(author=post.get("author", ""), date=post.get("date", ""), source_url=post.get("url") or node["url"], context=post.get("context", "own"), method="import_rule")
        record(store, node, items)


def maigret(store, project, report):
    if not isinstance(report, dict): raise ValueError("Oczekiwany obiekt raportu Maigret")
    count = 0
    for entry in report.values():
        if not isinstance(entry, dict): continue
        url = entry.get("url_user")
        if not isinstance(url, str): continue
        try: store.add(project, url, seed=False)
        except ValueError: continue
        count += 1
    return count


# Known service names (any casing) → platform id, for "service: handle" lines.
def _service_map():
    from .routes import profile_url
    from .native15 import SITES as a
    from .native17 import SITES as b
    from .forums import HOSTS
    names = set(a) | set(b) | set(HOSTS) | {'GitHub', 'GitLab', 'DEV', 'Codeberg', 'Gitea', 'HackerNews',
        'Bluesky', 'Steam', 'HackerOne', 'Lichess', 'ChessCom', 'Mastodon', 'Roblox'}
    out = {}
    for n in names:
        out[n.lower()] = n
    # A few friendly aliases people type.
    # Services with a fallback URL builder are recognised by name too.
    for platform in _FALLBACK:
        out[platform.lower()] = platform
    out.update({'twitter': 'X', 'x': 'X', 'hn': 'HackerNews', 'hackernews': 'HackerNews',
                'chess.com': 'ChessCom', 'h1': 'HackerOne'})
    return out


# Profile-URL patterns for services routes.profile_url does not build.
_FALLBACK = {'HackerOne': 'https://hackerone.com/{}', 'Bugcrowd': 'https://bugcrowd.com/{}',
             'X': 'https://x.com/{}', 'ChessCom': 'https://www.chess.com/member/{}'}


def import_accounts(store, project, lines, mine=False):
    """Add the user's own declared accounts in bulk.

    Each line is a public profile URL, or `service: handle`.  URLs are the strong
    case: a declared profile the user confirms as theirs becomes an anchor the
    graph links other accounts to.  Marking `mine` is the user's declaration; it
    never triggers an automatic read and never follows links by itself.
    """
    import re as _re
    from .archives import public_url
    from .identity import identify
    from .routes import profile_url
    if not store.rows("SELECT id FROM projects WHERE id=?", (project,)):
        raise ValueError("Nieznany projekt")
    if not isinstance(lines, list):
        raise ValueError("Oczekiwano listy wierszy")
    services = _service_map()
    added = confirmed = duplicates = 0
    invalid = []
    seen = set()
    for raw in lines[:500]:
        if not isinstance(raw, str):
            continue
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        match = _re.search(r'https?://\S+', line)
        url = None
        if match:
            url = match.group(0).rstrip('.,);]')
        else:
            parts = _re.split(r'\s*[:=]\s*|\s+@\s+|\s+', line, 1)
            if len(parts) == 2:
                platform = services.get(parts[0].strip().lower())
                handle = parts[1].strip().lstrip('@')
                if platform and _re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}', handle):
                    url = profile_url(platform, handle) or _FALLBACK.get(platform, '{}').replace('{}', handle) if platform in _FALLBACK or profile_url(platform, handle) else None
        if not url:
            invalid.append(line[:120])
            continue
        try:
            normalized = public_url(url)
            target = identify(normalized)
        except ValueError:
            invalid.append(line[:120])
            continue
        if target['kind'] not in ('profile', 'page'):
            invalid.append(line[:120])
            continue
        if normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        existed = store.rows("SELECT id FROM nodes WHERE project=? AND url=?", (project, normalized))
        try:
            node = store.add(project, normalized, seed=True)
            store.execute('UPDATE nodes SET user_added=1 WHERE id=?', (node,))
        except ValueError:
            invalid.append(line[:120])
            continue
        if existed:
            duplicates += 1
        else:
            added += 1
        if mine:
            store.decide(node, 'mine')
            confirmed += 1
    return {'added': added, 'confirmed': confirmed, 'duplicates': duplicates,
            'invalid': invalid[:20], 'invalid_count': len(invalid)}
