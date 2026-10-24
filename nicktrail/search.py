"""Stage one: bounded public discovery; no ownership inference or recursion."""
from .storage import SCHEMA_LOCK
import json
import http.client
import re
from urllib.parse import quote
from .adapters import read, extract
from .engine import record
from .network import Client, Limit
from .storage import now

ACTIVE = ('GitHub','Roblox','GitLab','Bluesky','DEV','Codeberg','Gitea')
OPTIN = ('Sensitive',)  # opt-in sources: valid when selected, never in a default list
LIMITED = {'SearXNG':'Opcjonalny indeks: NICKTRAIL_SEARXNG_URL, publiczny HTTPS i włączone JSON.','Mojeek':'Opcjonalny indeks: NICKTRAIL_MOJEEK_KEY.','GoogleCSE':'Opcjonalny indeks: NICKTRAIL_GOOGLE_KEY i NICKTRAIL_GOOGLE_CX.','PythonForum':'Publiczny profil forum Python po nicku; bez pełnotekstowej wyszukiwarki.','BlenderForum':'Publiczny profil Blender Artists po nicku; bez pełnotekstowej wyszukiwarki.','Free':'Bezpłatne sprawdzanie publicznych profili po nicku — bez klucza.','Catalog':'Katalog 180 domen: wyszukiwanie indeksu wymaga NICKTRAIL_BRAVE_KEY; bez klucza dostępny plan ręczny.','Web':'Wyszukiwanie indeksu WWW wymaga NICKTRAIL_BRAVE_KEY. Wyniki pozostają niezweryfikowane.', 'Steam':'Odczyt API wymaga klucza NICKTRAIL_STEAM_KEY.',
           'Mastodon':'Aktualny lookup wymaga tokenu i wskazanej instancji.',
           'YouTube':'Brak skonfigurowanego dostępu do API wyszukiwania.',
           'Twitch':'API wymaga uwierzytelnienia aplikacji.',
           'Xbox':'Publiczny profil Xbox przez OpenXBL; wymaga NICKTRAIL_XBOX_KEY.',
           'HackerOne':'Odczyt publicznego profilu po wskazaniu adresu; brak wyszukiwarki nazw.',
           'itch.io':'Tylko rozpoznawanie adresów i import.',
           'Linktree':'Tylko rozpoznawanie adresów i import.',
           'X':'Tylko rozpoznawanie adresów i import.',
           'Instagram':'Tylko rozpoznawanie adresów i import.',
           'Facebook':'Tylko rozpoznawanie adresów i import.'}


def schema(store):
    with SCHEMA_LOCK:
        initialized=getattr(store,'_initialized_schemas',set())
        if 'search' in initialized:return
        store._initialized_schemas=initialized|{'search'}
        store.db.executescript('''
        CREATE TABLE IF NOT EXISTS searches(id INTEGER PRIMARY KEY,project INTEGER REFERENCES projects ON DELETE CASCADE,
          nickname TEXT,started TEXT,finished TEXT,status TEXT,options TEXT,requests INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS search_sources(search INTEGER REFERENCES searches ON DELETE CASCADE,
          platform TEXT,state TEXT DEFAULT 'pending',detail TEXT DEFAULT '',nodes TEXT DEFAULT '[]',
          PRIMARY KEY(search,platform));
        CREATE TABLE IF NOT EXISTS search_tasks(search INTEGER REFERENCES searches ON DELETE CASCADE,
          platform TEXT,term TEXT,mode TEXT,state TEXT DEFAULT 'pending',detail TEXT DEFAULT '',nodes TEXT DEFAULT '[]',
          PRIMARY KEY(search,platform,term,mode));
        CREATE TABLE IF NOT EXISTS search_task_payloads(search INTEGER REFERENCES searches ON DELETE CASCADE,platform TEXT,term TEXT,mode TEXT,result TEXT,offset INTEGER DEFAULT 0,PRIMARY KEY(search,platform,term,mode));
        CREATE TABLE IF NOT EXISTS search_task_protocol(search INTEGER REFERENCES searches ON DELETE CASCADE,platform TEXT,term TEXT,mode TEXT,invocations INTEGER DEFAULT 0,counts TEXT,PRIMARY KEY(search,platform,term,mode));
        CREATE TABLE IF NOT EXISTS search_runtime_metrics(search INTEGER PRIMARY KEY REFERENCES searches ON DELETE CASCADE,peak_pending INTEGER,measurement_started TEXT,browser_renders INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS indexed_results(project INTEGER REFERENCES projects ON DELETE CASCADE,node INTEGER REFERENCES nodes ON DELETE CASCADE,search INTEGER REFERENCES searches ON DELETE CASCADE,platform TEXT,term TEXT,title TEXT,snippet TEXT,observed TEXT,PRIMARY KEY(search,platform,term,node));
        CREATE TABLE IF NOT EXISTS search_variants(search INTEGER REFERENCES searches ON DELETE CASCADE,alias TEXT,source_alias TEXT,rule TEXT,PRIMARY KEY(search,alias));
        CREATE TABLE IF NOT EXISTS candidate_hints(id INTEGER PRIMARY KEY,project INTEGER REFERENCES projects ON DELETE CASCADE,
          node INTEGER REFERENCES nodes ON DELETE CASCADE,search INTEGER REFERENCES searches ON DELETE CASCADE,
          term TEXT,basis TEXT,created TEXT,UNIQUE(node,search,term,basis));
        ''')

        task_columns={r['name'] for r in store.rows('PRAGMA table_info(search_tasks)')}
        if 'requests' not in task_columns:store.execute('ALTER TABLE search_tasks ADD COLUMN requests INTEGER')
        if 'deferrals' not in task_columns:store.execute('ALTER TABLE search_tasks ADD COLUMN deferrals INTEGER DEFAULT 0')
        from .eta import schema as eta_schema
        eta_schema(store)


def validate_nickname(nickname):
    if isinstance(nickname,str):nickname=nickname.strip()
    if not isinstance(nickname,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}',nickname):
        raise ValueError('Nick: 1–63 znaków ASCII: litery, cyfry, kropka, łącznik lub podkreślenie')
    return nickname


def lookup(platform,nickname,client):
    from .providers import lookup as provider_lookup
    return provider_lookup(platform,nickname,client)


def _lookup_builtin(platform, nickname, client):
    if platform in ('Steam','Mastodon'):
        from .keyed import steam_lookup,mastodon_lookup
        result=(steam_lookup if platform=='Steam' else mastodon_lookup)(nickname,client)
        return result | {'matches':[{'url':result['url'],'data':result['data'],'evidence':result.get('evidence',[])}] if result['state']=='found' else []}
    if platform in ('Twitch','Xbox'):
        from .gaming import twitch_lookup,xbox_lookup,configured
        if not configured(platform):return {'state':'unsupported','matches':[],'detail':'Brak klucza API: dodaj go w sekcji „Klucze API”.'}
        result=(twitch_lookup if platform=='Twitch' else xbox_lookup)(nickname,client)
        return result | {'matches':[{'url':result['url'],'data':result['data'],'evidence':result.get('evidence',[])}] if result['state']=='found' else result.get('matches',[])}
    if platform in ('GitHub','GitLab','DEV','Codeberg','Gitea'):
        host = {'GitHub':'github.com','GitLab':'gitlab.com','DEV':'dev.to','Codeberg':'codeberg.org','Gitea':'gitea.com'}[platform]
        from .identity import identify
        node = identify('https://' + host + '/' + nickname)
        if node['kind'] != 'profile': return {'state':'unsupported','detail':'Nick jest zastrzeżoną ścieżką serwisu'}
        result = read(node,client)
        return result | {'matches':[{'url':result.get('canonical_url',node['url']),'data':result.get('data',{}),'evidence':result.get('evidence',[])}] if result['state']=='found' else []}
    if platform == 'Roblox':
        response = client.post_json('https://users.roblox.com/v1/usernames/users', {'usernames':[nickname],'excludeBannedUsers':False})
        if response['state'] != 'found': return response
        body = json.loads(response['text'])
        if not isinstance(body,dict) or not isinstance(body.get('data'),list): raise ValueError('Nieprawidłowy wynik Roblox')
        matches = []
        for d in body['data'][:10]:
            if not isinstance(d,dict) or type(d.get('id')) is not int: raise ValueError('Nieprawidłowe ID Roblox')
            if str(d.get('name','')).lower()!=nickname.lower(): continue
            matches.append({'url':f"https://www.roblox.com/users/{d['id']}/profile",'data':{'stable_id':str(d['id']),'alias':d['name'],'display':d.get('displayName')},'evidence':[]})
        return {'state':'found' if matches else 'not_found','matches':matches,'detail':'Dokładny nick; publiczny resolver nazw. Opis profilu dopiero po wybraniu konta.'}
    if platform=='Bluesky':
        actor=nickname if '.' in nickname else nickname+'.bsky.social'
        result=read({'platform':'Bluesky','kind':'profile','url':'https://bsky.app/profile/'+actor},client)
        matches=[]
        if result['state']=='found':
            data=result.get('data',{})
            if str(data.get('alias','')).casefold()!=actor.casefold():return {'state':'partial','matches':[],'detail':'Resolver zwrócił inny handle; nie jest dokładnym trafieniem'}
            matches=[{'url':result.get('canonical_url','https://bsky.app/profile/'+actor),'data':data,'evidence':result.get('evidence',[]),'enriched':True}]
        return result|{'matches':matches}
    return {'state':'unsupported','matches':[],'detail':'Nieznany adapter'}


def bluesky_search(nickname,client):
    response = client.get('https://public.api.bsky.app/xrpc/app.bsky.actor.searchActors?q='+quote(nickname,safe='')+'&limit=10')
    if response['state'] != 'found': return response
    body = json.loads(response['text'])
    if not isinstance(body,dict) or not isinstance(body.get('actors'),list): raise ValueError('Nieprawidłowy wynik Bluesky')
    matches = []
    for d in body['actors'][:10]:
        if not isinstance(d,dict) or not isinstance(d.get('handle'),str) or not isinstance(d.get('did'),str): raise ValueError('Nieprawidłowy profil Bluesky')
        if not re.fullmatch(r'[a-zA-Z0-9.-]+',d['handle']): raise ValueError('Nieprawidłowy handle Bluesky')
        url = 'https://bsky.app/profile/'+d['handle']
        matches.append({'url':url,'data':{'avatar_url':d.get('avatar'),'stable_id':d['did'],'alias':d['handle'],'display':d.get('displayName')},
                        'evidence':extract(d.get('description') or '',url,'description')})
    return {'state':'found' if matches else 'not_found','matches':matches,'detail':'Do 10 wyników wyszukiwania Bluesky, także podobne nazwy. Brak paginacji; to nie jest pełna lista.'}


def discover(store, project, nickname=None, platforms=None, options=None, client=None, stopped=lambda:False, resume=None, aliases=(), related=False, criteria=None,lead_sources=None,stop_after_exact=False,variants=False,scan_mode='CUSTOM'):
    from .searchflow import run
    return run(store,project,nickname,platforms,options,client,stopped,resume,aliases,related,criteria,lead_sources,stop_after_exact,variants,scan_mode)


def results(store, project,limit=None):
    schema(store)
    searches=store.rows('SELECT * FROM searches WHERE project=? ORDER BY id DESC',(project,)) if limit is None else store.rows('SELECT * FROM searches WHERE project=? ORDER BY id DESC LIMIT ?',(project,int(limit)))
    from .context import compare
    context_matches={}
    nodes=store.rows('SELECT * FROM nodes WHERE project=?',(project,))
    for index,row in enumerate(searches):
        if limit is not None and index>0:
            context_matches[row['id']]={};continue
        criteria=json.loads(row['options']).get('_criteria',{})
        context_matches[row['id']]={str(n['id']):compare(json.loads(n['data']),criteria) for n in nodes}
    return [{'context_matches':context_matches[row['id']],'run':row,'sources':store.rows('SELECT * FROM search_sources WHERE search=? ORDER BY rowid',(row['id'],)),
             'tasks':store.rows('SELECT * FROM search_tasks WHERE search=? ORDER BY rowid',(row['id'],))} for row in searches]


def hints(store,project):
    schema(store)
    return store.rows('SELECT * FROM candidate_hints WHERE project=? ORDER BY id',(project,))

from .forums import HOSTS
from .community import STACK
LIMITED.update({id:'Publiczny profil Discourse; dostęp anonimowy zależy od forum.' for id in HOSTS})
LIMITED.update({id:'Publiczne wyszukiwanie nazwy, do 10 profili z opisem i witryną.' for id in STACK})
LIMITED.update({'Lichess':'Publiczne API po nicku, opis i linki.','ChessCom':'Publiczne API po nicku, metadane profilu.'})

LIMITED.update({'Keybase':'Publiczne API i odwrotne deklaracje github:/domain:/twitter:/reddit:/hackernews:.','HackerNews':'Publiczne aktywne konto HN po dokładnym nicku.'})

LIMITED['Archive']='Archiwum internetu (Wayback): adresy profili z numerem lub tagiem, np. shinden.pl/user/123-nick; bez klucza.'
LIMITED['Extended']='Opcjonalny katalog Sherlock (MIT); niezweryfikowane definicje, robots i rygorystyczne metadane.'

from .native15 import SITES as NATIVE_SITES
LIMITED.update({id:'Dokładny publiczny profil API; bez pełnego wyszukiwania osób.' for id in NATIVE_SITES})

from .engineconfig import instances as engine_instances
LIMITED.update({id:'Publiczna instancja '+row['engine']+'; stan walidacji: '+row['live_status'] for id,row in engine_instances().items()})

from .native17 import SITES as NATIVE17_SITES
LIMITED.update({id:'Publiczny profil API po dokładnym nicku; bez klucza.' for id in NATIVE17_SITES})
