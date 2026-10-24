"""Controlled fictional web for end-to-end discovery measurements.

Everything here is invented.  Real platform hostnames are used only so the
existing adapters recognise the URLs; no network request is ever made.  The
scenario runs the production pipeline with the HTTP client replaced by
`FixtureWeb`, then scores what NickTrail found against a known truth set.
"""
import hashlib
import json
import os
import tempfile
from contextlib import ExitStack
from unittest.mock import patch

from nicktrail.network import Limit

PERSON_MAIL = 'adafictional@gmail.com'
GRAVATAR = hashlib.md5(PERSON_MAIL.encode()).hexdigest()

# Canonical URLs of accounts that belong to the fictional person.
TRUTH = {
    'https://github.com/adafict': 'seed nick',
    'https://gitlab.com/adaf-dev': 'different nick, linked from GitHub bio',
    'https://ada-fictional.example': 'personal website from GitHub blog field',
    'https://codeberg.org/ada-old': 'old nick, rel=me on personal site about page',
    'https://lichess.org/@/adachess': 'different nick, rel=me on about page',
    'https://linktr.ee/adafiction': 'identity hub, rel=me on about page',
    'https://dev.to/adawrites': 'different nick, only listed on the Linktree hub',
    'https://keybase.io/adakb': 'different nick, only reachable via reverse proof github:adafict',
    'https://x.com/ada_fx': 'declared twitter_username (reading X needs configuration)',
    'https://hackerone.com/adasec': 'security profile, rel=me on about page; bio links back to site (researcher pattern)',
}
# Same or similar nick, different fictional people.
DISTRACTORS = {
    'https://gitlab.com/adafict': 'same nick, unrelated bakery owner',
    'https://dev.to/adafict': 'same nick, unrelated newsletter',
    'https://lichess.org/@/adafict': 'same nick, unrelated player',
    'https://github.com/adafict2': 'similar nick from related-name search',
}


def _json(value):
    return {'type': 'application/json', 'body': json.dumps(value)}


def _html(value):
    return {'type': 'text/html', 'body': value}


SITE = 'https://ada-fictional.example'
PAGES = {
    # GitHub
    'https://api.github.com/users/adafict': _json({'id': 101, 'login': 'adafict', 'type': 'User', 'name': 'Ada F.',
        'bio': 'Compiler hobbyist. Code mirror: https://gitlab.com/adaf-dev', 'blog': 'ada-fictional.example',
        'email': None, 'twitter_username': 'ada_fx', 'location': 'Gdańsk',
        'avatar_url': 'https://www.gravatar.com/avatar/' + GRAVATAR}),
    'https://api.github.com/user/101': 'https://api.github.com/users/adafict',
    'https://api.github.com/users/adafict2': _json({'id': 102, 'login': 'adafict2', 'type': 'User',
        'bio': 'Photography. Friend of https://ada-fictional.example and https://github.com/adafict',
        'blog': '', 'location': 'Porto'}),
    'https://api.github.com/user/102': 'https://api.github.com/users/adafict2',
    'https://api.github.com/search/users?q=adafict%20in%3Alogin%20type%3Auser&per_page=10': _json({'total_count': 2,
        'incomplete_results': False, 'items': [{'id': 101, 'login': 'adafict', 'type': 'User'},
                                               {'id': 102, 'login': 'adafict2', 'type': 'User'}]}),
    # GitLab
    'https://gitlab.com/api/v4/users?username=adaf-dev': _json([{'id': 202, 'username': 'adaf-dev', 'name': 'Ada',
        'bio': 'Mirror of https://github.com/adafict', 'website_url': SITE, 'public_email': 'Ada.Fictional+gl@gmail.com'}]),
    'https://gitlab.com/api/v4/users/202': _json({'id': 202, 'username': 'adaf-dev', 'name': 'Ada',
        'bio': 'Mirror of https://github.com/adafict', 'website_url': SITE, 'public_email': 'Ada.Fictional+gl@gmail.com'}),
    'https://gitlab.com/api/v4/users?username=adafict': _json([{'id': 909, 'username': 'adafict', 'name': 'Ada Boulange',
        'bio': 'Bakery owner in Lyon', 'website_url': 'https://boulangerie.example'}]),
    'https://gitlab.com/api/v4/users/909': _json({'id': 909, 'username': 'adafict', 'name': 'Ada Boulange',
        'bio': 'Bakery owner in Lyon', 'website_url': 'https://boulangerie.example'}),
    # Personal website
    SITE + '/robots.txt': {'type': 'text/plain', 'body': 'User-agent: *\nAllow: /\n'},
    SITE + '/sitemap.xml': {'type': 'application/xml', 'body': '<urlset><url><loc>' + SITE + '/about</loc></url></urlset>'},
    SITE: _html('<html><body><h1>Ada F.</h1><p>Notes about compilers, chess and speedruns. '
                'Read more <a href="/about">about me</a>. Photos by my friend: '
                '<a href="https://github.com/adafict2">adafict2</a>.</p></body></html>'),
    SITE + '/about': _html('<html><body><p>Elsewhere: '
        '<a rel="me" href="https://codeberg.org/ada-old">Codeberg (old)</a> '
        '<a rel="me" href="https://lichess.org/@/adachess">Lichess</a> '
        '<a rel="me" href="https://linktr.ee/adafiction">all links</a> '
        '<a rel="me" href="https://hackerone.com/adasec">HackerOne</a></p>'
        '<p>Contact: adafictional@googlemail.com</p></body></html>'),
    # HackerOne (security researcher): served as the JSON the adapter expects; bio/website link back.
    'https://hackerone.com/robots.txt': {'type': 'text/plain', 'body': 'User-agent: *\nAllow: /\n'},
    'https://hackerone.com/adasec': _json({'id': 404101, 'username': 'adasec', 'name': 'Ada F.',
        'bio': 'Security research. Code at https://github.com/adafict', 'website': SITE,
        'profile_picture_urls': {'small': 'https://www.gravatar.com/avatar/' + GRAVATAR}}),
    # Codeberg
    'https://codeberg.org/api/v1/users/ada-old': _json({'id': 303, 'login': 'ada-old', 'full_name': 'Ada',
        'description': 'Old account, now at ' + SITE, 'website': SITE}),
    # Lichess
    'https://lichess.org/api/user/adachess': _json({'id': 'adachess', 'username': 'adachess',
        'profile': {'bio': 'Blitz on weekends', 'links': SITE}}),
    'https://lichess.org/api/user/adafict': _json({'id': 'adafict', 'username': 'adafict',
        'profile': {'bio': 'Correspondence chess only'}}),
    # Linktree hub
    'https://linktr.ee/robots.txt': {'type': 'text/plain', 'body': 'User-agent: *\nAllow: /\n'},
    'https://linktr.ee/adafiction': _html('<html><head><title>adafiction | Linktree</title>'
        '<meta property="og:title" content="adafiction"></head><body><h1>@adafiction</h1>'
        '<a href="https://github.com/adafict">GitHub</a> <a href="https://dev.to/adawrites">Blog</a>'
        '</body></html>'),
    # DEV
    'https://dev.to/api/users/by_username?url=adawrites': _json({'id': 707, 'username': 'adawrites', 'name': 'Ada',
        'summary': 'Writing about parsers', 'website_url': SITE}),
    'https://dev.to/api/users/707': 'https://dev.to/api/users/by_username?url=adawrites',
    'https://dev.to/api/users/by_username?url=adafict': _json({'id': 808, 'username': 'adafict', 'name': 'A. Fict',
        'summary': 'Rust newsletter', 'website_url': ''}),
    'https://dev.to/api/users/808': 'https://dev.to/api/users/by_username?url=adafict',
    # Keybase: no account named like the seed; reverse proof finds a different nick.
    'https://keybase.io/_/api/1.0/user/lookup.json?usernames=adafict&fields=basics%2Cprofile%2Cproofs_summary%2Cpictures':
        _json({'status': {'code': 0}, 'them': []}),
    'https://keybase.io/_/api/1.0/user/lookup.json?github=adafict&fields=basics%2Cprofile%2Cproofs_summary%2Cpictures':
        'keybase-adakb',
    'https://keybase.io/_/api/1.0/user/lookup.json?usernames=adakb&fields=basics%2Cprofile%2Cproofs_summary%2Cpictures':
        'keybase-adakb',
    'keybase-adakb': _json({'status': {'code': 0}, 'them': [{'id': 'a' * 32, 'basics': {'username': 'adakb', 'status': 0},
        'profile': {'bio': 'keys'}, 'proofs_summary': {'all': [{'proof_type': 'github', 'nametag': 'adafict', 'state': 1,
                                                                 'service_url': 'https://github.com/adafict'}]}}]}),
}


class FixtureWeb:
    """Drop-in for network.Client: serves PAGES, records every request."""
    log = []
    pages = PAGES

    def __init__(self, queries=40, seconds=120, per_domain=15, **_):
        self.maximum = queries
        self.count = 0
        self.cache = {}
        self.cooldowns = {}
        self.events = []

    def _serve(self, url):
        page = self.pages.get(url)
        while isinstance(page, str):
            page = self.pages.get(page)
        FixtureWeb.log.append(url)
        if page is None:
            return {'state': 'not_found', 'detail': 'HTTP 404'}
        return {'state': 'found', 'text': page['body'], 'url': url, 'content_type': page['type']}

    def get(self, url, headers=None):
        if self.count >= self.maximum:
            raise Limit('Limit zapytań lub czasu')
        self.count += 1
        return self._serve(url)

    def profile_get(self, url):
        return self.get(url)

    def post_json(self, url, payload):
        self.count += 1
        return {'state': 'found', 'text': json.dumps({'data': []}), 'url': url, 'content_type': 'application/json'}

    def defer_host(self, *args):
        pass

    def event(self, *args, **kwargs):
        pass

    def remember(self, key, result, ttl):
        return result


CLIENT_MODULES = ('nicktrail.network', 'nicktrail.branches', 'nicktrail.bridgeflow', 'nicktrail.engine', 'nicktrail.search')


def run(scan_mode='STANDARD', bridges=True, workdir=None, persona=None):
    """Run the real pipeline on the fictional web; return the store and project."""
    from nicktrail.storage import Store
    from nicktrail.pipeline import run as pipeline
    persona = persona or PERSONA
    FixtureWeb.log = []
    FixtureWeb.pages = persona['pages']
    directory = workdir or tempfile.mkdtemp()
    store = Store(os.path.join(directory, 'scenario.sqlite3'))
    project = store.project('Fictional scenario')
    if persona.get('before'):
        persona['before'](store, project)
    with ExitStack() as stack:
        for module in CLIENT_MODULES:
            stack.enter_context(patch(module + '.Client', FixtureWeb))
        pipeline(store, project, persona['nick'], scan_mode=scan_mode, auto_resume=True, aliases=persona.get('aliases', ()))
        seed = store.rows("SELECT id FROM nodes WHERE project=? AND url=?", (project, persona['seed']))
        if bridges and seed:
            # The user recognises the seed account as theirs and starts the bridge loop from it.
            store.decide(seed[0]['id'], 'mine')
            store.set_focus(project, seed[0]['id'])
            from nicktrail.bridgeflow import run as bridge_run
            bridge_run(store, project, seed[0]['id'], client=FixtureWeb(queries=120, seconds=180))
    return store, project


def score(store, project, persona=None):
    persona = persona or PERSONA
    TRUTH, DISTRACTORS = persona['truth'], persona['distractors']
    from nicktrail.entitylinks import view
    from nicktrail.ranking import evaluate
    snapshot = store.snapshot(project)
    nodes = {n['url']: n for n in snapshot['nodes']}
    found = {u for u, n in nodes.items() if n['state'] == 'found'}
    present = set(nodes)
    ranking = evaluate(snapshot, {}, [persona['nick'], *persona.get('aliases', ())])
    order = [n for n in ranking.get('order', [])]
    by_id = {n['id']: n['url'] for n in snapshot['nodes']}
    ranked = [by_id[i] for i in order if i in by_id]

    def rank(url):
        return ranked.index(url) + 1 if url in ranked else None
    clusters = view(snapshot, limit=50)
    seed_cluster = next((c for c in clusters['clusters'] if any(m['url'] == persona['seed'] for m in c['members'])), None)
    cluster_urls = {m['url'] for m in seed_cluster['members']} if seed_cluster else set()
    hits, precision_sum = 0, 0.0
    relevant = [u for u in ranked if u in TRUTH or u in DISTRACTORS]
    for position, url in enumerate(relevant, 1):
        if url in TRUTH:
            hits += 1
            precision_sum += hits / position
    review = [sorted(m['url'] for m in p['members']) for p in clusters['review_pairs']]
    from nicktrail.deadends import report as dead_end_report
    dead = dead_end_report(store, project, snapshot)
    return {
        'average_precision': round(precision_sum / len(TRUTH), 3),
        'precision_at_8': round(sum(1 for u in relevant[:8] if u in TRUTH) / 8, 3),
        'distractors_in_review_pairs': sorted({u for pair in review for u in pair if u in DISTRACTORS}),
        'truth_found': sorted(u for u in TRUTH if u in found),
        'truth_present_unread': sorted(u for u in TRUTH if u in present and u not in found),
        'truth_missing': sorted(u for u in TRUTH if u not in present),
        'distractors_found': sorted(u for u in DISTRACTORS if u in found),
        'truth_ranks': {u: rank(u) for u in TRUTH if u in present},
        'distractor_ranks': {u: rank(u) for u in DISTRACTORS if u in present},
        'seed_cluster_truth': sorted(cluster_urls & set(TRUTH)),
        'seed_cluster_false': sorted(cluster_urls - set(TRUTH)),
        'false_clusters': [[m['url'] for m in c['members']] for c in clusters['clusters']
                           if any(m['url'] in DISTRACTORS for m in c['members'])],
        'dead_ends': dead['counts'],
        'dead_end_items': sorted((d['kind'], d['url']) for d in dead['dead_ends']),
        'requests': len(FixtureWeb.log),
        'unserved_requests': len([u for u in FixtureWeb.log if u not in persona['pages']]),
    }


PERSONA = {'nick': 'adafict', 'seed': 'https://github.com/adafict', 'pages': PAGES, 'truth': TRUTH, 'distractors': DISTRACTORS}

BORYS_MAIL = 'borys.k@proton.me'
BORYS = {
    'nick': 'borysdev', 'aliases': ('bkowal',), 'seed': 'https://github.com/borysdev',
    'truth': {
        'https://github.com/borysdev': 'seed nick, public e-mail field',
        'https://gitlab.com/bkowal': 'user-supplied alias; no links, same mailbox written differently',
        'https://news.ycombinator.com/user?id=borysdev': 'same nick, about links Bluesky',
        'https://bsky.app/profile/borys.example': 'domain handle, links GitHub',
        'https://borys.example': 'personal domain reachable only as the Bluesky handle',
    },
    'distractors': {
        'https://codeberg.org/borysdev': 'same nick, different person',
        'https://dev.to/borysdev': 'same nick, different person',
        'https://github.com/borysdev-org': 'organization from related search',
        'https://gitlab.com/borysdev': 'same nick, different person',
    },
    'pages': {
        'https://api.github.com/users/borysdev': _json({'id': 501, 'login': 'borysdev', 'type': 'User', 'name': 'Borys K',
            'bio': 'Backend', 'blog': '', 'email': BORYS_MAIL, 'location': 'Kraków'}),
        'https://api.github.com/user/501': 'https://api.github.com/users/borysdev',
        'https://api.github.com/search/users?q=borysdev%20in%3Alogin%20type%3Auser&per_page=10': _json({'total_count': 2,
            'incomplete_results': False, 'items': [{'id': 501, 'login': 'borysdev', 'type': 'User'},
                                                   {'id': 502, 'login': 'borysdev-org', 'type': 'Organization'}]}),
        'https://api.github.com/users/borysdev-org': _json({'id': 502, 'login': 'borysdev-org', 'type': 'Organization',
            'bio': 'Team account', 'blog': '', 'email': BORYS_MAIL}),
        'https://api.github.com/user/502': 'https://api.github.com/users/borysdev-org',
        'https://gitlab.com/api/v4/users?username=bkowal': _json([{'id': 601, 'username': 'bkowal', 'name': 'B. K.',
            'bio': 'Go and SQL', 'website_url': '', 'public_email': 'Borys.K@pm.me'}]),
        'https://gitlab.com/api/v4/users/601': _json({'id': 601, 'username': 'bkowal', 'name': 'B. K.',
            'bio': 'Go and SQL', 'website_url': '', 'public_email': 'Borys.K@pm.me'}),
        'https://gitlab.com/api/v4/users?username=borysdev': _json([{'id': 602, 'username': 'borysdev', 'name': 'Boris D',
            'bio': 'Sysadmin in Riga', 'website_url': '', 'public_email': 'boris.d@example.lv'}]),
        'https://gitlab.com/api/v4/users/602': _json({'id': 602, 'username': 'borysdev', 'name': 'Boris D',
            'bio': 'Sysadmin in Riga', 'website_url': '', 'public_email': 'boris.d@example.lv'}),
        'https://codeberg.org/api/v1/users/borysdev': _json({'id': 701, 'login': 'borysdev', 'description': 'Rust games', 'website': ''}),
        'https://dev.to/api/users/by_username?url=borysdev': _json({'id': 801, 'username': 'borysdev', 'summary': 'Design', 'website_url': ''}),
        'https://dev.to/api/users/801': 'https://dev.to/api/users/by_username?url=borysdev',
        'https://hacker-news.firebaseio.com/v0/user/borysdev.json': _json({'id': 'borysdev', 'about': 'Elsewhere: https://bsky.app/profile/borys.example'}),
        'https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=borys.example': _json({'did': 'did:plc:fictionalborys',
            'handle': 'borys.example', 'displayName': 'Borys', 'description': 'Code at github.com/borysdev'}),
        'https://borys.example/robots.txt': {'type': 'text/plain', 'body': 'User-agent: *\nAllow: /\n'},
        'https://borys.example': _html('<html><body><h1>Borys K.</h1><p>Backend notes and talks. '
            '<a rel="me" href="https://github.com/borysdev">GitHub</a> <a rel="me" href="https://bsky.app/profile/borys.example">Bluesky</a></p></body></html>'),
        'https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=did%3Aplc%3Afictionalborys': 'https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=borys.example',
    },
}
def _cezary_history(store, project):
    # An earlier audit of this project read the same durable GitHub account under its old nick.
    store.apply_profile(project, 'https://github.com/cez1999', {'alias': 'cez1999', 'stable_id': '901'})


CEZARY = {
    'nick': 'cezarycodes', 'seed': 'https://github.com/cezarycodes', 'before': _cezary_history,
    'truth': {
        'https://github.com/cezarycodes': 'seed, renamed from cez1999 (same durable id)',
        'https://lichess.org/@/cez1999': 'forgotten old account under the old nick',
        'https://codeberg.org/cez1999': 'forgotten old account under the old nick',
    },
    'distractors': {'https://gitlab.com/cezarycodes': 'same current nick, different person'},
    'pages': {
        'https://api.github.com/users/cezarycodes': _json({'id': 901, 'login': 'cezarycodes', 'type': 'User', 'bio': 'Embedded'}),
        'https://api.github.com/user/901': 'https://api.github.com/users/cezarycodes',
        'https://lichess.org/api/user/cez1999': _json({'id': 'cez1999', 'username': 'cez1999', 'profile': {'bio': 'school chess club'}}),
        'https://codeberg.org/api/v1/users/cez1999': _json({'id': 902, 'login': 'cez1999', 'description': 'first projects'}),
        'https://gitlab.com/api/v4/users?username=cezarycodes': _json([{'id': 903, 'username': 'cezarycodes', 'bio': 'Marketing'}]),
        'https://gitlab.com/api/v4/users/903': _json({'id': 903, 'username': 'cezarycodes', 'bio': 'Marketing'}),
    },
}
PERSONAS = {'ada': PERSONA, 'borys': BORYS, 'cezary': CEZARY}


if __name__ == '__main__':
    import sys
    persona = PERSONAS[(sys.argv[1:2] or ['ada'])[0]]
    store, project = run(persona=persona)
    print(json.dumps(score(store, project, persona), indent=1))
