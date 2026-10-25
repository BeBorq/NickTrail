"""Information-value scheduling. Category preferences never establish identity."""

import json
from .context import compare
from .graphsignals import analyze
from .servicecatalog import services
from urllib.parse import urlsplit
from .accountentities import non_person

IDENTITY_HUBS = {
    'linktr.ee',
    'carrd.co',
    'about.me',
    'beacons.ai',
    'bento.me',
    'bio.site',
    'taplink.cc',
    'gravatar.com',
    'keybase.io',
    'lnk.bio',
    'many.link',
    'shor.by',
}


def bridge_bonus(url):
    host = (urlsplit(url).hostname or '').casefold()
    return 8 if any(host == site or host.endswith('.' + site) for site in IDENTITY_HUBS) else 0


PLATFORM_CATEGORY = {
    'PythonForum': 'developer',
    'BlenderForum': 'creative',
    'GitHub': 'developer',
    'GitLab': 'developer',
    'Codeberg': 'developer',
    'Gitea': 'developer',
    'DEV': 'developer',
    'HackerOne': 'security',
    'Roblox': 'gaming',
    'Steam': 'gaming',
}


def snapshot(store, project):
    return {
        'nodes': store.rows('SELECT * FROM nodes WHERE project=?', (project,)),
        'evidence': store.rows('SELECT * FROM evidence WHERE project=?', (project,)),
        'focus': store.rows('SELECT * FROM focus WHERE project=?', (project,)),
    }


def context(store, project):
    if not store.rows("SELECT name FROM sqlite_master WHERE type='table' AND name='searches'"):
        return {'active': False}
    row = store.rows('SELECT options FROM searches WHERE project=? ORDER BY id DESC LIMIT 1', (project,))
    opts = json.loads(row[0]['options']) if row else {}
    terms = opts.get('_terms', [])
    criteria = opts.get('_criteria', {})
    return {'active': bool(terms or any(criteria.values())), 'terms': terms, 'criteria': criteria}


def categories(data):
    chosen = {f['node'] for f in data.get('focus', [])}
    catalog = {s['id']: s['category'] for s in services()}
    out = set()
    for n in data['nodes']:
        if n['ownership'] == 'not_mine' or not (n['ownership'] == 'mine' or n['id'] in chosen):
            continue
        fields = json.loads(n['data'])
        category = catalog.get(fields.get('public_probe')) or PLATFORM_CATEGORY.get(n.get('platform'))
        if category:
            out.add(category)
    return out


def ordered_services(data):
    records = list(services())
    preferred = categories(data)
    if not preferred:
        return records
    favored = [s for s in records if s['category'] in preferred]
    other = [s for s in records if s['category'] not in preferred]
    out = []
    # Reserve exploration slots so cross-category discoveries are not starved.
    while favored or other:
        for _ in range(2):
            if favored:
                out.append(favored.pop(0))
        if other:
            out.append(other.pop(0))
    return out


def priorities(data, scope):
    graph = analyze(data)
    selected = {f['node'] for f in data.get('focus', [])}
    terms = {str(t).casefold() for t in scope.get('terms', [])}
    criteria = scope.get('criteria', {})
    known = set(criteria.get('known_urls', []))
    out = {}
    for n in data['nodes']:
        if n['kind'] not in ('profile', 'page'):
            continue
        fields = json.loads(n['data'])
        alias = str(fields.get('alias') or '').casefold()
        matches = compare(fields, criteria)
        score = 0
        reason = 'Brak wystarczających sygnałów do rozwijania'
        eligible = not scope.get('active')
        if n['ownership'] == 'mine' or n['id'] in selected:
            score = 100
            reason = 'Konto własne lub wybrany punkt odniesienia'
            eligible = True
        elif any(p['kind'] != 'incoming_link' for p in graph.get(n['id'], [])):
            score = 90
            reason = 'Publiczna ścieżka do punktu odniesienia'
            eligible = True
        elif n['url'] in known:
            score = 85
            reason = 'Adres podany w kryteriach'
            eligible = True
        elif alias and alias in terms:
            score = 80
            reason = 'Dokładny nick lub znany alias'
            eligible = True
        elif {'first_name', 'last_name'} <= set(compare({'display': fields.get('display')}, criteria)):
            score = 75
            reason = 'Zgodna pełna nazwa'
            eligible = True
        elif 'keywords' in matches or len(matches) >= 2:
            score = 60
            reason = 'Zgodne dodatkowe kryteria'
            eligible = True
        elif matches:
            score = 20
            reason = 'Pojedyncza słaba zgodność'
        outgoing = {
            e['target']
            for e in data['evidence']
            if e['source'] == n['id']
            and e.get('current', 1)
            and e['decision'] != 'rejected'
            and e['relation'] in ('links', 'claims_ownership')
            and e.get('method') != 'manual_observation'
        }
        score += min(5, len(outgoing))
        if eligible and n['state'] == 'found':
            score += bridge_bonus(n['url'])
        if non_person(n) and n['ownership'] != 'mine' and n['id'] not in selected:
            score = 0
            eligible = False
            reason = 'Konto organizacji/bota; rozwijanie wymaga jawnego wyboru lub deklaracji własności'
        if n['ownership'] == 'not_mine':
            score = -1
            eligible = False
            reason = 'Odrzucone przez użytkownika'
        out[n['id']] = {'priority': score, 'expand': eligible, 'reason': reason}
    return out


from .forums import HOSTS

PLATFORM_CATEGORY.update({id: 'developer' for id in HOSTS})
PLATFORM_CATEGORY.update(
    {
        'Lichess': 'gaming',
        'ChessCom': 'gaming',
        'StackOverflow': 'developer',
        'SecuritySE': 'security',
        'SuperUser': 'technical',
        'AskUbuntu': 'technical',
        'GameDevSE': 'gaming',
        'MathSE': 'technical',
        'ProcessingForum': 'creative',
        'BlenderForum': 'creative',
    }
)
