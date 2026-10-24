"""Dead-end diagnostics: useful public identifiers that no later step used.

A dead end is a node connected to your accounts (suggested group, review pair
or public graph path) whose identifier could open a new branch, but nothing in
the stored searches, bridge leads or reads used it.  The report only suggests
user-visible next steps; it never queries anything, and e-mail addresses are
never turned into external searches (only consented own-address checks or
manual review are suggested).
"""
import json
from urllib.parse import urlsplit

from .entitylinks import IDENTITY_HUBS, build, known_domains

READ_STATES = ('found',)
CONFIG_PLATFORMS = {'X': 'NICKTRAIL_X_BEARER_TOKEN', 'Steam': 'klucz Steam Web API', 'Mastodon': 'konfiguracja instancji'}


def _data(node):
    try:
        value = json.loads(node.get('data') or '{}')
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _searched(store, project):
    terms = set()
    if store.rows("SELECT name FROM sqlite_master WHERE type='table' AND name='search_tasks'"):
        for row in store.rows('SELECT t.term FROM search_tasks t JOIN searches s ON s.id=t.search WHERE s.project=?', (project,)):
            term = str(row['term'] or '')
            terms.add(term.split(':', 1)[1].casefold() if ':' in term else term.casefold())
        for row in store.rows('SELECT nickname FROM searches WHERE project=?', (project,)):
            if row['nickname']:
                terms.add(row['nickname'].casefold())
    leads = set()
    if store.rows("SELECT name FROM sqlite_master WHERE type='table' AND name='discovery_leads'"):
        for row in store.rows("SELECT kind,value FROM discovery_leads WHERE project=? AND state!='interrupted'", (project,)):
            leads.add((row['kind'], row['value'].casefold()))
            if row['kind'] == 'alias':
                terms.add(row['value'].casefold())
    return terms, leads


def connected(snapshot):
    """Accounts linked to your accounts: suggested groups, review pairs, graph paths."""
    from .graphsignals import analyze
    nodes = {n['id']: n for n in snapshot['nodes']}
    anchors = {n['id'] for n in snapshot['nodes'] if n.get('ownership') == 'mine'}
    anchors |= {f['node'] for f in snapshot.get('focus', []) if f['node'] in nodes and nodes[f['node']].get('ownership') != 'not_mine'}
    identity = build(snapshot, known_domains())
    group = set()
    for cluster in identity['clusters']:
        ids = set(cluster['members']) | {p for pages in cluster['site_pages'].values() for p in pages}
        if ids & anchors:
            group |= ids
    review = {x for p in identity['pairs'] if p['tier'] == 'review' and {p['a'], p['b']} & (group | anchors) for x in (p['a'], p['b'])}
    paths = {i for i, signals in analyze(snapshot).items() if any(s['kind'] != 'incoming_link' for s in signals)}
    reach = {}
    for i in anchors:
        reach[i] = 'anchor'
    for i in group - anchors:
        reach[i] = 'group'
    for i in (review | paths) - group - anchors:
        reach.setdefault(i, 'review' if i in review else 'path')
    return {i: r for i, r in reach.items() if nodes.get(i, {}).get('ownership') != 'not_mine'}, identity


def report(store, project, snapshot=None):
    snapshot = snapshot or store.snapshot(project)
    nodes = {n['id']: n for n in snapshot['nodes']}
    reach, identity = connected(snapshot)
    terms, leads = _searched(store, project)
    domains = known_domains()
    out = []

    def add(kind, node, reach_kind, suggestion, detail):
        out.append({'kind': kind, 'node': node['id'], 'url': node['url'], 'platform': node.get('platform'),
                    'connection': reach_kind, 'suggestion': suggestion, 'detail': detail})

    grouped_mail = {f_ids for p in identity['pairs'] if p['tier'] == 'cluster'
                    for f in p['facts'] if f['kind'] in ('shared_email', 'shared_email_hash') for f_ids in f['evidence']}
    for i, how in sorted(reach.items()):
        n = nodes[i]
        data = _data(n)
        host = (urlsplit(n['url']).hostname or '').removeprefix('www.').lower()
        if n['kind'] == 'profile' and n.get('state') in READ_STATES:
            alias = data.get('alias')
            if isinstance(alias, str) and 2 <= len(alias) <= 63 and alias.casefold() not in terms:
                add('ALIAS_DEAD_END', n, how, 'Szukaj tego nicku dokładnie w innych serwisach (pętla mostów lub nowe wyszukiwanie).',
                    'Nick „' + alias + '” odczytany z połączonego konta nie był jeszcze szukany.')
            for old in store.rows('SELECT url FROM profile_addresses WHERE node=? AND url!=?', (i, n['url'])):
                previous = urlsplit(old['url']).path.strip('/').split('/')[-1]
                if previous and previous.casefold() not in terms and previous.casefold() != str(alias or '').casefold():
                    add('PERSISTENT_ID_DEAD_END', n, how, 'Sprawdź dawny nick tego samego trwałego konta w innych serwisach; może dziś należeć do kogoś innego.',
                        'Historyczny adres tego konta: ' + old['url'])
        if any(host == h or host.endswith('.' + h) for h in IDENTITY_HUBS) and n.get('state') not in READ_STATES:
            add('IDENTITY_HUB_DEAD_END', n, how, 'Otwórz tę stronę-wizytówkę ręcznie i dodaj widoczne odnośniki jako obserwację.',
                'Strona z odnośnikami nie została odczytana (stan: ' + str(n.get('state')) + ').')
        if n.get('platform') == 'Strona' and n.get('state') in READ_STATES and host and host not in domains:
            root = urlsplit(n['url']).path.strip('/') == ''
            pages = [m for m in nodes.values() if m.get('platform') == 'Strona' and m['id'] != i
                     and (urlsplit(m['url']).hostname or '').removeprefix('www.').lower() == host]
            if root and not pages and ('domain', host) not in leads and ('proof', 'domain:' + host) not in leads:
                add('DOMAIN_DEAD_END', n, how, 'Uruchom pętlę mostów: odczyt stron „o mnie/kontakt” tej domeny i wyszukiwanie domeny.',
                    'Domena osobista bez odczytu stron tożsamości ani wyszukiwania domeny.')
        if n.get('state') == 'unsupported' and n.get('platform') in CONFIG_PLATFORMS:
            add('DECLARED_NEEDS_CONFIGURATION', n, how, 'Skonfiguruj ' + CONFIG_PLATFORMS[n['platform']] + ' albo sprawdź profil ręcznie.',
                'Konto zadeklarowane przez połączony profil, ale bez dostępnego odczytu.')
        if n['kind'] == 'discord':
            add('DISCORD_MANUAL', n, how, 'Discord nie ma publicznego wyszukiwania; oceń tę deklarację ręcznie.', 'Zadeklarowany identyfikator Discord.')

    # E-mail: published on a connected account but not used by any bridge.
    for e in snapshot['evidence']:
        if e.get('relation') != 'public_contact_occurrence' or e['source'] not in reach or not e.get('current', 1) or e.get('decision') == 'rejected':
            continue
        target = nodes.get(e['target'])
        if not target or target['kind'] != 'email' or e.get('id') in grouped_mail:
            continue
        if any(d['node'] == target['id'] for d in out):
            continue
        add('EMAIL_DEAD_END', target, reach[e['source']],
            'Jeśli to Twój adres: sprawdź go za zgodą w panelu ekspozycji (HIBP) i przejrzyj ręcznie konta zakładane na ten adres. NickTrail nie wysyła odkrytych adresów do wyszukiwarek.',
            'Publiczny e-mail z połączonego konta nie łączy się z żadnym innym kontem.')
    order = {'anchor': 0, 'group': 1, 'review': 2, 'path': 3}
    out.sort(key=lambda d: (order.get(d['connection'], 9), d['kind'], d['node']))
    counts = {}
    for d in out:
        counts[d['kind']] = counts.get(d['kind'], 0) + 1
    return {'dead_ends': out, 'counts': counts, 'connected_accounts': len(reach),
            'note': 'Diagnostyka nie wykonuje zapytań. Połączenie nie potwierdza własności.'}
