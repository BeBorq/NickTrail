"""Fair, resumable public-link exploration: at most ten descendants per root."""
from .storage import SCHEMA_LOCK
import json
import time
from .storage import now
from .network import Client
from .engine import scan

def schema(store):
    with SCHEMA_LOCK:
        initialized=getattr(store,'_initialized_schemas',set())
        if 'branches' in initialized:return
        store._initialized_schemas=initialized|{'branches'}
        store.db.executescript('''CREATE TABLE IF NOT EXISTS branch_runs(id INTEGER PRIMARY KEY,project INTEGER REFERENCES projects ON DELETE CASCADE,started TEXT,finished TEXT,status TEXT,requests INTEGER DEFAULT 0,options TEXT);
        CREATE TABLE IF NOT EXISTS branch_nodes(run INTEGER REFERENCES branch_runs ON DELETE CASCADE,root INTEGER REFERENCES nodes ON DELETE CASCADE,node INTEGER REFERENCES nodes ON DELETE CASCADE,parent INTEGER REFERENCES nodes ON DELETE CASCADE,depth INTEGER,state TEXT DEFAULT 'pending',detail TEXT DEFAULT '',PRIMARY KEY(run,root,node));''')

        if 'context' not in {r['name'] for r in store.rows('PRAGMA table_info(branch_runs)')}:store.execute("ALTER TABLE branch_runs ADD COLUMN context TEXT DEFAULT '{}'")
        if 'expanded' not in {r['name'] for r in store.rows('PRAGMA table_info(branch_nodes)')}:store.execute('ALTER TABLE branch_nodes ADD COLUMN expanded INTEGER DEFAULT 0')
        if 'origin_key' not in {r['name'] for r in store.rows('PRAGMA table_info(branch_runs)')}:store.execute('ALTER TABLE branch_runs ADD COLUMN origin_key TEXT')
        store.execute('CREATE UNIQUE INDEX IF NOT EXISTS branch_origin_key ON branch_runs(project,origin_key) WHERE origin_key IS NOT NULL')

def explore(store,project,roots=None,options=None,resume=None,client=None,stopped=lambda:False,context_override=None,origin_key=None):
    schema(store)
    from .frontier import context,snapshot,priorities
    opts={'queries':100,'seconds':180,'per_domain':30}|(options or {})
    if set(opts)!={'queries','seconds','per_domain'} or any(type(v) is not int or v<0 for v in opts.values()) or not opts['seconds']:raise ValueError('Nieprawidłowe limity drzewa')
    if origin_key is not None:
        if not isinstance(origin_key,str) or not origin_key or len(origin_key)>120:raise ValueError('Nieprawidłowy klucz kolejki drzewa')
        prior_run=store.rows('SELECT * FROM branch_runs WHERE project=? AND origin_key=?',(project,origin_key))
        if prior_run:
            if prior_run[0]['status']=='completed':return prior_run[0]['id']
            resume=prior_run[0]['id']
            if prior_run[0]['status']=='running':store.execute("UPDATE branch_runs SET status='paused' WHERE id=?",(resume,))
    if resume:
        row=store.rows('SELECT * FROM branch_runs WHERE id=? AND project=?',(resume,project))
        if not row or row[0]['status'] not in ('limited','paused','failed'):raise ValueError('Nie można wznowić drzewa')
        run=resume
        scope=json.loads(row[0].get('context') or '{}')
    else:
        if not isinstance(roots,list) or not 1<=len(roots)<=200 or any(type(v) is not int for v in roots):raise ValueError('Wybierz 1–200 korzeni')
        roots=list(dict.fromkeys(roots))
        for id in roots:
            node=store.node(id)
            if node['project']!=project or node['kind'] not in ('profile','page') or node['ownership']=='not_mine':raise ValueError('Nieprawidłowy korzeń drzewa')
        scope=context(store,project) if context_override is None else context_override
        # A durable origin and all roots commit together, before any HTTP request.
        with store.db:
            run=store.db.execute('INSERT INTO branch_runs(project,started,status,options,context,origin_key) VALUES(?,?,?,?,?,?)',(project,now(),'running',json.dumps(opts),json.dumps(scope),origin_key)).lastrowid
            store.db.executemany('INSERT INTO branch_nodes(run,root,node,parent,depth) VALUES(?,?,?,?,0)',[(run,id,id,None) for id in roots])
    session=client or Client(**opts)
    from .cooldowns import bind as bind_cooldowns
    bind_cooldowns(session,store)
    initial=session.count;prior=store.rows('SELECT requests FROM branch_runs WHERE id=?',(run,))[0]['requests']
    cache={n['node']:n['state'] for n in store.rows("SELECT * FROM branch_nodes WHERE run=? AND state NOT IN ('pending','searching')",(run,))}
    status='completed';started=time.monotonic()
    store.execute("UPDATE branch_runs SET status='running' WHERE id=?",(run,))
    try:
        while True:
            ranking=priorities(snapshot(store,project),scope) if scope.get('active') else {}
            # A late bridge can revive expansion of an already-read weak root without rereading it.
            for deferred in store.rows("SELECT * FROM branch_nodes WHERE run=? AND state='found' AND expanded=0 AND depth<3",(run,)):
                if not scope.get('active') or ranking.get(deferred['root'],{}).get('expand'):
                    store.execute("UPDATE branch_nodes SET state='pending' WHERE run=? AND root=? AND node=?",(run,deferred['root'],deferred['node']))
            pending=store.rows("SELECT * FROM branch_nodes WHERE run=? AND state IN ('pending','searching') ORDER BY depth,root,node",(run,))
            if not pending:break
            if ranking:
                def priority(task):
                    value=max(ranking.get(task['node'],{}).get('priority',0),ranking.get(task['root'],{}).get('priority',0)-task['depth']*5)
                    return (-value,task['depth'],task['root'],task['node'])
                task=min(pending,key=priority)
            else:task=pending[0]
            id=task['node'];node=store.node(id)
            if stopped():status='paused';break
            if session.count-initial>=opts['queries'] or time.monotonic()-started>=opts['seconds']:status='limited';break
            valid_path=True
            if task['parent'] is not None:
                parent=store.node(task['parent'])
                valid_path=parent['ownership']!='not_mine' and parent['state']=='found' and bool(store.rows("SELECT 1 FROM evidence WHERE source=? AND target=? AND current=1 AND decision!='rejected' AND relation IN ('links','claims_ownership') AND (method!='manual_observation' OR decision='accepted')",(task['parent'],id)))
            if not valid_path:state='skipped';detail='Ścieżka została odrzucona lub nie jest już aktualna'
            elif node['ownership']=='not_mine':state='rejected';detail='Odrzucone przez użytkownika'
            elif id in cache:state=cache[id];detail='Odczyt współdzielony z inną gałęzią tego przebiegu'
            else:
                store.execute("UPDATE branch_nodes SET state='searching' WHERE run=? AND root=? AND node=?",(run,task['root'],id))
                offset=session.count
                class View:
                    @property
                    def count(self):return session.count-offset
                    def get(self,*args,**kwargs):return session.get(*args,**kwargs)
                    # Profile pages must go through the robots.txt check of the real client.
                    def profile_get(self,url):return getattr(session,'profile_get',session.get)(url)
                    def post_json(self,*args,**kwargs):return session.post_json(*args,**kwargs)
                    def defer_host(self,*args):
                        if hasattr(session,'defer_host'):return session.defer_host(*args)
                scan_id=scan(store,project,{'queries':max(0,opts['queries']-(session.count-initial)),'seconds':max(1,int(opts['seconds']-(time.monotonic()-started))),'per_domain':opts['per_domain'],'profiles':1,'pages':1},targets=[id],client=View(),stopped=stopped)
                observations=store.rows('SELECT state,detail FROM observations WHERE scan=? AND node=?',(scan_id,id))
                if not observations:
                    store.execute("UPDATE branch_nodes SET state='pending' WHERE run=? AND root=? AND node=?",(run,task['root'],id));status='paused' if stopped() else 'limited';break
                state=observations[0]['state'];detail=observations[0]['detail'];cache[id]=state
            store.execute('UPDATE branch_nodes SET state=?,detail=? WHERE run=? AND root=? AND node=?',(state,detail,run,task['root'],id))
            can_expand=not scope.get('active') or ranking.get(task['root'],{}).get('expand',False)
            if state=='found' and not can_expand:
                store.execute('UPDATE branch_nodes SET detail=detail||? WHERE run=? AND root=? AND node=?',(' · Rozwijanie odłożone: brak wystarczającego powiązania lub kryteriów. Wybierz konto jako źródło, aby sprawdzić je ręcznie.',run,task['root'],id))
            if state=='found' and task['depth']<3 and can_expand:
                count=store.rows('SELECT COUNT(*) AS n FROM branch_nodes WHERE run=? AND root=? AND depth>0',(run,task['root']))[0]['n']
                for edge in store.rows("SELECT target FROM evidence WHERE source=? AND current=1 AND decision!='rejected' AND relation IN ('links','claims_ownership') AND (method!='manual_observation' OR decision='accepted') ORDER BY id",(id,)):
                    if count>=10:break
                    child=store.node(edge['target'])
                    if child['kind'] not in ('profile','page') or child['ownership']=='not_mine':continue
                    exists=store.rows('SELECT 1 FROM branch_nodes WHERE run=? AND root=? AND node=?',(run,task['root'],child['id']))
                    if exists:continue
                    store.execute('INSERT INTO branch_nodes(run,root,node,parent,depth) VALUES(?,?,?,?,?)',(run,task['root'],child['id'],id,task['depth']+1));count+=1
            if state=='found' and (can_expand or task['depth']>=3):store.execute('UPDATE branch_nodes SET expanded=1 WHERE run=? AND root=? AND node=?',(run,task['root'],id))
            store.execute('UPDATE branch_runs SET requests=? WHERE id=?',(prior+session.count-initial,run))
    except Exception:
        status='failed';raise
    finally:store.execute('UPDATE branch_runs SET status=?,finished=?,requests=? WHERE id=?',(status,now(),prior+session.count-initial,run))
    return run

def history(store,project):
    schema(store)
    rows=store.rows('SELECT * FROM branch_runs WHERE project=? ORDER BY id DESC LIMIT 5',(project,))
    return [{'run':r,'nodes':store.rows('SELECT * FROM branch_nodes WHERE run=? ORDER BY depth,root,node',(r['id'],))} for r in rows]
