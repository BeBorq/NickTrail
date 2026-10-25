"""Explicit bounded discover/enrich/query loop. No inferred ownership or email queries."""

import json, re, time
from urllib.parse import urlsplit
from .storage import SCHEMA_LOCK, now
from .frontier import snapshot
from .graphsignals import analyze
from .indexes import INDEXES
from .network import Client, Limit

LEAD_COST = {'proof': 0, 'alias': 1, 'domain': 2}
DEFAULT_PROVIDERS = (
    'GitHub',
    'GitLab',
    'DEV',
    'Codeberg',
    'RustForum',
    'GNOMEForum',
    'StackOverflow',
    'Lichess',
    'Keybase',
    'HackerNews',
)


def schema(store):
    with SCHEMA_LOCK:
        store.db.execute(
            "CREATE TABLE IF NOT EXISTS discovery_leads(project INTEGER REFERENCES projects ON DELETE CASCADE,root INTEGER REFERENCES nodes ON DELETE CASCADE,kind TEXT,value TEXT,source INTEGER REFERENCES nodes ON DELETE CASCADE,provenance TEXT,state TEXT,search INTEGER REFERENCES searches ON DELETE CASCADE,created TEXT,PRIMARY KEY(project,root,kind,value))"
        )
        store.db.commit()


def preview(store, project, root):
    node = store.node(root)
    if (
        node['project'] != project
        or node['ownership'] == 'not_mine'
        or node['kind'] not in ('profile', 'page')
    ):
        raise ValueError('Wybierz poprawny punkt odniesienia')
    data = snapshot(store, project)
    data['focus'] = [{'node': root}]
    # Mine labels are not additional anchors in this explicitly scoped loop.
    data['nodes'] = [
        dict(n, ownership='unknown') if n['id'] != root and n['ownership'] == 'mine' else n
        for n in data['nodes']
    ]
    graph = analyze(data)
    out = []
    credible = []
    seen = set()
    from .search import schema as search_schema

    search_schema(store)
    schema(store)
    used = {
        (l['kind'], l['value'])
        for l in store.rows(
            "SELECT kind,value FROM discovery_leads WHERE project=? AND root=? AND state!='interrupted'",
            (project, root),
        )
    }
    historical_leads = []
    for n in data['nodes']:
        paths = graph.get(n['id'], [])
        eligible = n['id'] == root or any(
            p['strength'] >= 12 and p['kind'] not in ('incoming_link', 'shared_website') for p in paths
        )
        proof_edges = [
            e
            for e in data['evidence']
            if n['platform'] == 'Keybase'
            and e['source'] == n['id']
            and e.get('current', 1)
            and e['decision'] != 'rejected'
            and e.get('method') == 'parser'
            and e.get('context') == 'own'
            and e['location'].startswith('keybase.proof.')
            and (
                e['target'] == root
                or any(
                    p['strength'] >= 12 and p['kind'] not in ('incoming_link', 'shared_website')
                    for p in graph.get(e['target'], [])
                )
            )
        ]
        eligible = eligible or bool(proof_edges)
        if not eligible or n['state'] != 'found' or n['ownership'] == 'not_mine':
            continue
        fields = json.loads(n['data'])
        kind = None
        value = None
        if (
            n['kind'] == 'profile'
            and isinstance(fields.get('alias'), str)
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}', fields['alias'])
        ):
            kind = 'alias'
            value = fields['alias']
        elif n['platform'] == 'Strona':
            host = urlsplit(n['url']).hostname
            if host and '.' in host:
                kind = 'domain'
                value = host
        historical = []
        if n['kind'] == 'profile' and fields.get('stable_id'):
            # The same durable account used another nick before: old accounts elsewhere often still carry it.
            for old in store.rows(
                'SELECT url FROM profile_addresses WHERE node=? AND url!=? ORDER BY first_seen',
                (n['id'], n['url']),
            ):
                name = urlsplit(old['url']).path.strip('/').split('/')[-1]
                if (
                    re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}', name)
                    and name.casefold() != str(value or '').casefold()
                ):
                    historical.append((name, old['url']))
        evidence_ids = list(
            dict.fromkeys([e['id'] for p in paths[:1] for e in p['edges']] + [e['id'] for e in proof_edges])
        )
        for name, old_url in historical[:3]:
            if ('alias', name) in seen:
                continue
            seen.add(('alias', name))
            old_lead = {
                'kind': 'alias',
                'value': name,
                'source': n['id'],
                'url': n['url'],
                'historical': old_url,
                'reason': 'Dawny nick tego samego trwałego konta; w innych serwisach może dziś należeć do kogoś innego',
                'evidence': evidence_ids,
            }
            if ('alias', name) not in used and not store.rows(
                'SELECT 1 FROM search_tasks t JOIN searches s ON s.id=t.search WHERE s.project=? AND t.term=? AND t.state!=? LIMIT 1',
                (project, name, 'pending'),
            ):
                historical_leads.append(old_lead)
        if not value or (kind, value) in seen:
            continue
        seen.add((kind, value))
        lead = {
            'kind': kind,
            'value': value,
            'source': n['id'],
            'url': n['url'],
            'reason': (
                'Odczytany punkt odniesienia'
                if n['id'] == root
                else 'Odczytany profil połączony publicznymi dowodami; tylko trop'
            ),
            'evidence': evidence_ids,
        }
        credible.append(lead)
        if (kind, value) in used:
            continue
        if kind == 'alias' and store.rows(
            'SELECT 1 FROM search_tasks t JOIN searches s ON s.id=t.search WHERE s.project=? AND t.term=? AND t.state!=? LIMIT 1',
            (project, value, 'pending'),
        ):
            continue
        out.append(lead)
    # Official reverse proof directory offers bridges without username similarity or Brave.
    for lead in credible:
        source = store.node(lead['source'])
        prefix = {'GitHub': 'github', 'X': 'twitter', 'HackerNews': 'hackernews', 'Reddit': 'reddit'}.get(
            source['platform']
        )
        value = (
            ('domain:' + lead['value'])
            if lead['kind'] == 'domain'
            else prefix + ':' + lead['value'] if prefix else None
        )
        if value and ('proof', value) not in used:
            out.append(
                lead
                | {
                    'kind': 'proof',
                    'value': value,
                    'reason': 'Odwrotne wyszukiwanie publicznej deklaracji w Keybase; bez weryfikacji podpisu',
                }
            )
    out += historical_leads
    return out[:12]


class View:
    def __init__(self, client):
        self.client = client
        self.initial = client.count

    @property
    def count(self):
        return self.client.count - self.initial

    def get(self, *a, **kw):
        return self.client.get(*a, **kw)

    def profile_get(self, url):
        return getattr(self.client, 'profile_get', self.client.get)(url)

    def post_json(self, *a, **kw):
        return self.client.post_json(*a, **kw)

    def defer_host(self, *a):
        return self.client.defer_host(*a)


def run(store, project, root, options=None, platforms=None, client=None, stopped=lambda: False):
    opts = {'queries': 80, 'seconds': 180, 'per_domain': 15} | (options or {})
    if (
        set(opts) != {'queries', 'seconds', 'per_domain'}
        or any(type(v) is not int or v < 0 for v in opts.values())
        or not 1 <= opts['queries'] <= 300
        or not 1 <= opts['seconds'] <= 600
    ):
        raise ValueError('Pętla: 1–300 zapytań i 1–600 sekund')
    from .providers import REGISTRY
    from .search import discover, schema as search_schema
    from .branches import explore
    from .personal import crawl

    search_schema(store)
    schema(store)
    preview(store, project, root)
    platforms = list(dict.fromkeys(DEFAULT_PROVIDERS if platforms is None else platforms))
    if (
        not platforms
        or len(platforms) > 40
        or any(p not in REGISTRY or p in ('Free', 'Catalog', 'Extended') for p in platforms)
    ):
        raise ValueError('Wybierz API lub indeksy; pełne katalogi nie są rozwijane rekurencyjnie')
    platforms = [p for p in platforms if REGISTRY[p].available()]
    if not platforms:
        raise ValueError('Brak skonfigurowanych wybranych dostawców')
    store.execute(
        "UPDATE discovery_leads SET state='interrupted' WHERE project=? AND root=? AND state='planned' AND search IS NULL",
        (project, root),
    )
    session = client or Client(**opts, xml_resources=True)
    initial = session.count
    deadline = time.monotonic() + opts['seconds']
    from .cooldowns import bind as bind_cooldowns

    bind_cooldowns(session, store)
    searches = []
    trees = []
    pages = []
    leads = []
    discovered = []
    status = 'completed'
    candidate_start = {n['id'] for n in snapshot(store, project)['nodes']}

    def remaining():
        return {
            'queries': max(0, opts['queries'] - (session.count - initial)),
            'seconds': max(1, int(deadline - time.monotonic())),
            'per_domain': opts['per_domain'],
        }

    try:
        trees.append(
            explore(
                store,
                project,
                [root],
                remaining(),
                client=View(session),
                stopped=stopped,
                context_override={
                    'active': True,
                    'terms': [],
                    'criteria': {'known_urls': [store.node(root)['url']]},
                },
            )
        )
        # At most two feedback rounds and six new queries/aliases per invocation.
        for round in range(2):
            if stopped():
                status = 'paused'
                break
            if not remaining()['queries'] or time.monotonic() >= deadline:
                status = 'limited'
                break
            derived = preview(store, project, root)
            sites = [l['source'] for l in derived if l['kind'] == 'domain'][:2]
            pages += crawl(store, project, sites, session, stopped)
            followups = []
            for page in pages[-6:]:
                if page.get('state') != 'found' or not page.get('node'):
                    continue
                for edge in store.rows(
                    "SELECT target FROM evidence WHERE source=? AND current=1 AND decision!='rejected' AND relation IN ('links','claims_ownership') AND method='parser' AND context='own'",
                    (page['node'],),
                ):
                    target = store.node(edge['target'])
                    if target['kind'] == 'profile' and target['ownership'] != 'not_mine':
                        followups.append(target['id'])
            if followups and remaining()['queries'] and not stopped():
                trees.append(
                    explore(
                        store,
                        project,
                        list(dict.fromkeys(followups))[:5],
                        remaining(),
                        client=View(session),
                        stopped=stopped,
                    )
                )
            derived = preview(store, project, root)
            # Cheapest high-value first: a reverse proof lookup is one request that
            # returns declared accounts; an alias fans out to every chosen provider.
            from .deadends import connected

            reach = connected(snapshot(store, project))[0]
            rank = {'anchor': 0, 'group': 1, 'review': 2, 'path': 3}
            # Leads from your accounts and their suggested group before leads that
            # only share a short public path (e.g. a friend linked from your site).
            derived = sorted(
                derived, key=lambda l: (rank.get(reach.get(l['source']), 4), LEAD_COST.get(l['kind'], 9))
            )
            for lead in derived:
                if len(leads) >= 6:
                    break
                if stopped():
                    status = 'paused'
                    break
                if not remaining()['queries'] or time.monotonic() >= deadline:
                    status = 'limited'
                    break
                chosen = (
                    ['Keybase']
                    if lead['kind'] == 'proof' and 'Keybase' in platforms
                    else [
                        p
                        for p in platforms
                        if lead['kind'] == 'alias' or lead['kind'] == 'domain' and p in INDEXES
                    ]
                )
                if not chosen:
                    continue
                newcount = len({n['id'] for n in snapshot(store, project)['nodes']} - candidate_start)
                if newcount >= 100:
                    status = 'limited'
                    break
                # Durable deduplication and provenance; ordinary search is resumable on limits.
                store.execute(
                    'INSERT OR IGNORE INTO discovery_leads VALUES(?,?,?,?,?,?,?,?,?)',
                    (
                        project,
                        root,
                        lead['kind'],
                        lead['value'],
                        lead['source'],
                        json.dumps(lead),
                        'planned',
                        None,
                        now(),
                    ),
                )
                criteria = (
                    {'keywords': '"' + lead['value'] + '" -site:' + lead['value']}
                    if lead['kind'] == 'domain'
                    else {'keywords': lead['value']} if lead['kind'] == 'proof' else None
                )
                search = discover(
                    store,
                    project,
                    lead['value'] if lead['kind'] == 'alias' else None,
                    chosen,
                    remaining() | {'candidates': min(30, 100 - newcount)},
                    client=View(session),
                    stopped=stopped,
                    criteria=criteria,
                    lead_sources=[lead],
                )
                store.execute(
                    "UPDATE discovery_leads SET search=?,state='searched' WHERE project=? AND root=? AND kind=? AND value=?",
                    (search, project, root, lead['kind'], lead['value']),
                )
                searches.append(search)
                leads.append(lead)
                ids = list(
                    dict.fromkeys(
                        i
                        for t in store.rows('SELECT nodes FROM search_tasks WHERE search=?', (search,))
                        for i in json.loads(t['nodes'])
                    )
                )
                discovered += ids
                roots = [
                    i
                    for i in ids
                    if store.node(i)['ownership'] != 'not_mine'
                    and store.node(i)['kind'] in ('profile', 'page')
                ][:10]
                if roots and remaining()['queries'] and not stopped():
                    trees.append(
                        explore(store, project, roots, remaining(), client=View(session), stopped=stopped)
                    )
            if len(leads) >= 6 or status != 'completed':
                break
            # Only graph-linked newly read accounts can seed the next round.
            if not preview(store, project, root):
                break
    except Limit:
        status = 'limited'
    return {
        'project': project,
        'root': root,
        'status': status,
        'requests': session.count - initial,
        'searches': searches,
        'discoveries': list(dict.fromkeys(discovered))[:100],
        'trees': trees,
        'pages': pages,
        'leads': leads,
        'limits': {'rounds': 2, 'leads': 6, 'new_search_candidates': 100},
        'detail': 'Tropy nie potwierdzają własności. Wyszukiwania/drzewa zatrzymane limitem można wznowić osobno.',
    }


def run_many(store, project, roots, options=None, platforms=None, client=None, stopped=lambda: False):
    """The same bounded loop for several accounts the user picked, sharing one budget.

    Each account gets an equal slice of queries and seconds, so picking more
    accounts never raises the total network cost."""
    roots = list(dict.fromkeys(roots))
    if not 1 <= len(roots) <= 10:
        raise ValueError('Wybierz od 1 do 10 kont')
    opts = {'queries': 80, 'seconds': 180, 'per_domain': 15} | (options or {})
    share = {
        'queries': max(1, opts['queries'] // len(roots)),
        'seconds': max(1, opts['seconds'] // len(roots)),
        'per_domain': opts['per_domain'],
    }
    runs = []
    for root in roots:
        if stopped():
            break
        if store.node(root)['ownership'] == 'not_mine':
            runs.append({'root': root, 'status': 'skipped', 'error': 'Konto oznaczone jako „Nie moje”'})
            continue
        try:
            runs.append(
                run(store, project, root, share, platforms, client=client, stopped=stopped) | {'root': root}
            )
        except ValueError as error:
            runs.append({'root': root, 'status': 'skipped', 'error': str(error)})
    return {
        'kind': 'MULTI_BRIDGES',
        'project': project,
        'roots': roots,
        'runs': runs,
        'budget_per_account': share,
        'status': 'paused' if stopped() else 'completed',
    }


def history(store, project, root=None):
    if not store.rows("SELECT name FROM sqlite_master WHERE type='table' AND name='discovery_leads'"):
        return []
    return store.rows(
        'SELECT * FROM discovery_leads WHERE project=?'
        + (' AND root=?' if root is not None else '')
        + ' ORDER BY created DESC LIMIT 60',
        (project, root) if root is not None else (project,),
    )
