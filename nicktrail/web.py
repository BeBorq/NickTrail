import json
import secrets
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .storage import Store
from .engine import scan
from .exporting import export


def serve(db_path, port=8765):
    token = secrets.token_urlsafe(32)
    stop = threading.Event()
    from .apikeys import load as load_api_keys
    load_api_keys()
    lock = threading.Lock()
    job = {"running": False, "error": "",'result':None}
    authority = f"127.0.0.1:{port}"
    avatar_cache={}

    def run(project, resume, options, targets=None, mode='scan', nickname=None, platforms=None, aliases=(), related=False, criteria=None, verify_top=0, auto_branches=False, branch_options=None, auto_resume=True, variants=False, scan_mode='CUSTOM', historical=None):
        store = Store(db_path)
        import time as _clock
        job.update(mode=mode,started=_clock.time())
        try:
            from .autoresume import search as finish_search,branches as finish_branches,ROUND_CAP
            resume_pause=lambda:stop.wait(2)
            if mode=='historical':
                from .archives import lookup as archive_lookup
                job['result']=archive_lookup(store,project,targets[0],options['date'],options.get('read_content',False),options.get('consent',False),stopped=stop.is_set)
            elif mode=='bridges':
                from .bridgeflow import run as bridge_run
                if len(targets)==1:job['result']=bridge_run(store,project,targets[0],options,platforms,stopped=stop.is_set)
                else:
                    from .bridgeflow import run_many
                    job['result']=run_many(store,project,targets,options,platforms,stopped=stop.is_set)
            elif mode=='branches':
                from .branches import explore
                branch_id=explore(store,project,targets,options,resume=resume,stopped=stop.is_set)
                if auto_resume:finish_branches(store,project,branch_id,options,stop.is_set,resume_pause)
            elif mode=='hints-mail':
                from .accounthints import import_mailbox
                job['result']={'kind':'MAIL_HINTS','project':project}|import_mailbox(store,project,options['path'])
            elif mode=='exposure':
                from .exposure import check
                check(store,project,options['account'],options['consent'])
            elif mode=='exposure-provider':
                from .exposureproviders import HIBP
                provider=HIBP(store)
                job['result']=(provider.list_incidents if options['operation']=='catalog' else provider.health)()
            elif mode=='discover':
                from .search import discover
                saved=store.rows('SELECT options FROM searches WHERE id=? AND project=?',(resume,project)) if resume else []
                if saved:scan_mode=json.loads(saved[0]['options']).get('_scan_mode','CUSTOM')
                from .scanmodes import policy
                rounds=policy(scan_mode)['continuations']
                if scan_mode!='CUSTOM':
                    configured_mode=policy(scan_mode);auto_branches=configured_mode['branches'];auto_resume=configured_mode['auto_resume'];verify_top=0;branch_options=configured_mode['branch_options'];options=configured_mode['options']
                if auto_branches or saved and '_pipeline' in json.loads(saved[0]['options']):
                    from .pipeline import run as staged_search
                    search_id=staged_search(store,project,nickname,platforms,options,aliases,related,criteria,resume,branch_options,auto_resume,stop.is_set,resume_pause,variants=variants,scan_mode=scan_mode)
                elif verify_top and not resume:
                    from .workflow import search_and_verify
                    search_id=search_and_verify(store,project,nickname,platforms,options,aliases,related,criteria,verify_top,stopped=stop.is_set,variants=variants,scan_mode=scan_mode)
                    if auto_resume:finish_search(store,project,search_id,stop.is_set,resume_pause,max_rounds=max(rounds,ROUND_CAP))
                else:
                    search_id=discover(store,project,nickname,platforms,options,stopped=stop.is_set,resume=resume,aliases=aliases,related=related,criteria=criteria,variants=variants,scan_mode=scan_mode)
                    if auto_resume:finish_search(store,project,search_id,stop.is_set,resume_pause,max_rounds=max(rounds,ROUND_CAP))
                if historical and not stop.is_set():
                    from .archives import after_search
                    job['result']=after_search(store,project,historical['date'],historical['limit'],stopped=stop.is_set)
            else: scan(store, project, options, resume, stopped=stop.is_set, targets=targets,focused=mode=='focused',rendered=mode=='browser')
        except Exception as e: job["error"] = str(e) if isinstance(e,ValueError) else type(e).__name__
        finally:
            store.db.close()
            with lock: job["running"] = False

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def send(self, data, status=200, content_type="application/json; charset=utf-8", cache="no-store"):
            if isinstance(data,(dict,list)) and self.headers.get('X-NickTrail-Language'):
                from .localization import localize_response
                data=localize_response(urlsplit(self.path).path,data,self.headers.get('X-NickTrail-Language'))
            body = data if isinstance(data,bytes) else data.encode() if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'nonce-" + token + "'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers(); self.wfile.write(body)

        def allowed(self):
            # Browsers mark requests started by another website (an <img> or a link on a
            # foreign page) as cross-site; the panel never needs those.
            if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"): return False
            return self.headers.get("Host") == authority and self.headers.get("Origin", "http://" + authority) == "http://" + authority

        def failed(self, store, where, error):
            # Unexpected errors still get a JSON answer (not a dropped connection) and a log entry.
            from .errorlog import write as log_error
            log_error(store, where, error)
            self.send({"error": "Błąd programu (" + type(error).__name__ + "). Szczegóły w pliku .errors.log obok bazy."}, 500)

        def do_GET(self):
            if not self.allowed(): self.send({"error": "Odmowa dostępu"}, 403); return
            path = urlsplit(self.path)
            if path.path == "/favicon.ico": self.send(b"", 204, "image/x-icon", cache="private, max-age=86400"); return
            if path.path == "/":
                from .localization import render_panel
                language=parse_qs(path.query).get("lang", ["en"])[0]
                self.send(render_panel(Path(__file__).with_name("panel.html").read_text(encoding="utf-8"),language).replace("__TOKEN__", token), content_type="text/html; charset=utf-8"); return
            store = Store(db_path)
            try:
                query = parse_qs(path.query)
                project = int(query.get("project", ["0"])[0])
                if path.path == '/api/profile-history':
                    from .profilehistory import timeline
                    self.send(timeline(store,project,int(query.get('node',['0'])[0])));return
                if path.path == '/api/exposure-capabilities':
                    from .exposureproviders import HIBP
                    provider=HIBP(store);self.send(provider.capabilities()|{'cooldowns':provider.rate_limit_state()});return
                if path.path == "/api/state":
                    from .search import results,hints
                    from .related import alias_suggestions
                    from .ranking import evaluate,focus_results,promoted_candidates
                    from .exposure import history
                    from .planning import suggestions
                    from .branches import history as branch_history
                    from .presentation import labels
                    # Never combine an earlier DB snapshot with a later "finished" flag.
                    with lock:
                        job_snapshot=dict(job)
                        response={"projects": store.rows("SELECT * FROM projects"), "snapshot": store.snapshot(project,scan_limit=25), "job": job_snapshot,'searches':results(store,project,limit=10),'hints':hints(store,project),'aliasSuggestions':alias_suggestions(store,project)}
                    from .independence import provenance
                    response['evidence_provenance']=provenance(response['snapshot'])
                    from .autoresume import progress
                    response['progress']=progress(response['searches'][0]['tasks']) if response['searches'] else progress([])
                    from .eta import estimate as search_eta
                    response['eta']=search_eta(store,response['searches'][0]['run']['id'],running=job['running']) if response['searches'] else None
                    from .cooldowns import waiting as cooldown_waiting
                    response['throttling']=cooldown_waiting(store)
                    latest=response['searches'][0]['run'] if response['searches'] else None
                    criteria=json.loads(latest['options']).get('_criteria',{}) if latest else {}
                    terms=json.loads(latest['options']).get('_terms',[latest['nickname']]) if latest else []
                    response['ranking']=evaluate(response['snapshot'],criteria,terms)
                    from .pools import classify as candidate_pools
                    from .diagnostics import completeness,manual_queue
                    response['pools']=candidate_pools(response['snapshot'],response['ranking'],terms,criteria)
                    response['scan_coverage']=completeness(response['searches'][0],store,response['snapshot'],response['pools']) if response['searches'] else None
                    response['manual_queue']=manual_queue(response['searches'][0],store) if response['searches'] else []
                    existing=[id for source in response['searches'][0]['sources'] for id in json.loads(source['nodes'])] if response['searches'] else []
                    response['relatedCandidates']=promoted_candidates(response['snapshot'],response['ranking'],existing)
                    response['focusResults']=focus_results(response['snapshot'],store)
                    from .archives import history as archive_history
                    response['historical']=archive_history(store,project)
                    response['exposure']=history(store,project)
                    response['suggestions']=suggestions(store,project)
                    from .investigation import prepare as review_plan
                    response['review_plan']=review_plan(store,project,snapshot=response['snapshot'],ranking=response['ranking'],criteria=criteria,terms=terms) if project else None
                    response['branches']=branch_history(store,project)
                    pending=[n['node'] for b in response['branches'][:1] for n in b['nodes'] if n['state'] in ('pending','searching')]
                    response['labels']=labels(response['snapshot'],criteria,pending,response['ranking']['nodes'])
                    from .entitylinks import view as identity_view
                    response['identity_clusters']=identity_view(response['snapshot'])
                    from .deadends import report as dead_end_report
                    response['dead_ends']=dead_end_report(store,project,response['snapshot']) if project else None
                    from .readstatus import report as read_status_report
                    response['read_status']=read_status_report(store,project,response['snapshot']['nodes']) if project else {}
                    import os,importlib.util
                    from .providers import describe
                    from .servicecatalog import summary
                    response['history_window']={'searches':10,'scans':25}
                    response['providers']=describe()
                    response['service_catalog']=summary()
                    from .coverage import describe as coverage_description
                    response['discovery_coverage']=coverage_description()
                    from .bridgeflow import history as discovery_history
                    response['discovery_leads']=discovery_history(store,project)
                    response['indexed_provenance']=store.rows('SELECT * FROM indexed_results WHERE project=? ORDER BY search DESC,observed DESC LIMIT 100',(project,))
                    from .accounthints import view as account_hints
                    response['account_hints']=account_hints(store,project) if project else {'services':[],'total':0,'nicks':[],'emails':[]}
                    response['features']={'hibp':bool(os.environ.get('NICKTRAIL_HIBP_KEY')),'browser_package':importlib.util.find_spec('playwright') is not None}
                    self.send(response)
                elif path.path=='/api/keys':
                    from .apikeys import describe as describe_keys
                    self.send(describe_keys())
                elif path.path=='/api/settings':
                    from .settings import describe as describe_settings
                    from .cooldowns import robots_schema
                    robots_schema(store);import time as _time
                    self.send(describe_settings(store)|{'remembered_refusals':store.rows('SELECT count(*) n FROM robots_decisions WHERE until_epoch>?',(_time.time(),))[0]['n']})
                elif path.path=='/api/capabilities':
                    from .capabilities import matrix,presets
                    self.send(matrix(store)|{'presets':presets()})
                elif path.path=='/api/health-report':
                    from .serviceaudit import report
                    allowed={'category','state','source','engine','tier','min_age','importance'}
                    self.send(report(store,{k:v[0] for k,v in query.items() if k in allowed},int(query.get('limit',['100'])[0])))
                elif path.path=='/api/avatar':
                    from .avatars import fetch
                    id=int(query['node'][0]);key=(id,store.node(id)['data'])
                    if key not in avatar_cache:
                        if len(avatar_cache)>=100:avatar_cache.clear()
                        avatar_cache[key]=fetch(store,id)
                    avatar=avatar_cache[key]
                    # Cached by the browser: the panel re-renders every few seconds during a search,
                    # and re-requesting (and logging a 404 for) every missing avatar each time
                    # filled the developer console with thousands of errors.
                    if avatar:self.send(avatar[0],content_type=avatar[1],cache='private, max-age=86400')
                    else:self.send(b'',204,'text/plain',cache='private, max-age=86400')
                elif path.path == "/api/export":
                    fmt = query.get("format", ["json"])[0]
                    excluded = [int(x) for x in query.get("exclude", [""])[0].split(",") if x]
                    self.send(export(store, project, fmt, query.get("omit_email") == ["1"], excluded, include_sensitive=query.get("include_sensitive") == ["1"], language=query.get("lang", ["en"])[0]), content_type="text/plain; charset=utf-8")
                elif path.path == "/api/compare": self.send(store.compare(int(query["first"][0]), int(query["second"][0])))
                else: self.send({"error": "Nie znaleziono"}, 404)
            except (ValueError, KeyError, TypeError, OverflowError): self.send({"error": "Nieprawidłowe dane"}, 400)
            except Exception as error: self.failed(store, 'GET ' + path.path, error)
            finally: store.db.close()

        def do_POST(self):
            if not self.allowed() or self.headers.get("X-NickTrail-Token") != token:
                self.send({"error": "Sesja panelu wygasła lub żądanie jest niedozwolone. Po aktualizacji odśwież kartę."}, 403); return
            store = Store(db_path)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1000000: raise ValueError("Za duże żądanie")
                data = json.loads(self.rfile.read(size))
                action = self.path
                if action == "/api/create": result = store.project(data["name"])
                elif action == '/api/context-plan':
                    from .context import criteria,plan
                    result={'criteria':criteria(data.get('criteria')), 'queries':plan(data.get('nickname',''),data.get('criteria'))}
                elif action == "/api/add":
                    result = store.add(int(data["project"]), data["value"], data.get("type", "url"), data.get("confirmed", False))
                    store.execute("UPDATE nodes SET user_added=1 WHERE id=?", (result,))
                elif action=='/api/settings':
                    from .settings import save as save_settings
                    save_settings(store,data.get('changes',{}));result='Zapisano ustawienia odczytu'
                elif action=='/api/keys':
                    from .apikeys import save as save_keys
                    save_keys(data.get('changes',{}));result='Zapisano klucze API'
                elif action=='/api/robots-forget':
                    from .cooldowns import forget_robots
                    result='Usunięto zapamiętane odmowy: '+str(forget_robots(store))
                elif action == "/api/decide": result = store.decide(int(data["id"]), data["decision"], data.get("relation", False))
                elif action == "/api/separate":
                    # The user's own statement that two accounts belong to different people.
                    # Stored as a typed contradiction so groups can never join across it;
                    # it can be withdrawn like any relation ("Odrzuć relację").
                    project=int(data["project"]);a=int(data["a"]);b=int(data["b"])
                    if a==b:raise ValueError("Wybierz dwa różne konta")
                    first,second=store.node(a),store.node(b)
                    if first["project"]!=project or second["project"]!=project:raise ValueError("Konto z innego projektu")
                    store.evidence(project,a,b,"identity_contradiction",first["url"],"user_declaration","Twoja deklaracja: to różne osoby","manual_declaration",context="user_supplied")
                    result="Zapisano: to różne osoby. Te konta nie zostaną połączone w jedną grupę."
                elif action == "/api/stop": stop.set(); result = "Zatrzymywanie po bieżącym odczycie"
                elif action=='/api/ai-packet':
                    from .aipacket import build
                    result=build(store,int(data['project']),data['ids'],data.get('redaction'),data.get('format','json'),language=self.headers.get('X-NickTrail-Language','pl'))
                elif action=='/api/planner-preview':
                    from .investigation import prepare as prepare_plan
                    result=prepare_plan(store,int(data['project']))
                elif action=='/api/manual-review':
                    from .manualreview import resolve
                    result=resolve(store,int(data['project']),int(data['search']),data['source_platform'],data['term'],data['mode'],data['decision'],data.get('url'))
                elif action=='/api/diagnose':
                    from .diagnostics import explain
                    result=explain(store,int(data['project']),data['url'])
                elif action=='/api/golden':
                    from .golden import evaluate as golden_evaluate
                    result=golden_evaluate(store,int(data['project']),data['benchmark'])
                elif action=='/api/historical':
                    from .archives import preview as archive_preview
                    project=int(data['project']);node=int(data['node']);plan=archive_preview(store,project,node,data['date'])
                    if data.get('preview') is True:result=plan
                    else:
                        if data.get('consent') is not True or type(data.get('read_content',False)) is not bool:raise ValueError('Potwierdź wysłanie wskazanego publicznego URL do archiwum')
                        with lock:
                            if job['running']:raise ValueError('Analiza już trwa')
                            stop.clear();job.update(running=True,error='')
                            threading.Thread(target=run,args=(project,None,{'date':data['date'],'read_content':data.get('read_content',False),'consent':True},[node],'historical'),daemon=True).start()
                        result='Uruchomiono ograniczony odczyt archiwum'
                elif action == '/api/bridges':
                    from .bridgeflow import preview
                    project=int(data['project'])
                    roots=data.get('roots',[data.get('root')])
                    if not isinstance(roots,list) or not 1<=len(roots)<=10 or any(type(r) is not int for r in roots):raise ValueError('Wybierz od 1 do 10 kont')
                    roots=list(dict.fromkeys(roots));root=roots[0]
                    for r in roots:
                        node=store.node(r)
                        if not node or node['project']!=project:raise ValueError('Konto spoza projektu')
                        if node['ownership']=='not_mine':raise ValueError('Odrzucone konto („Nie moje”) nie może być punktem wyjścia')
                        preview(store,project,r)
                    if data.get('preview',False):result=preview(store,project,root)
                    else:
                        options=data.get('options',{})
                        if not isinstance(options,dict) or set(options)-{'queries','seconds','per_domain'} or any(type(v) is not int or v<0 for v in options.values()) or not 1<=options.get('queries',80)<=300 or not 1<=options.get('seconds',180)<=600:raise ValueError('Nieprawidłowe limity pętli')
                        from .providers import REGISTRY
                        platforms=data.get('platforms')
                        if platforms is not None and (not isinstance(platforms,list) or not platforms or len(platforms)>40 or any(not isinstance(p,str) or p not in REGISTRY or p in ('Free','Catalog','Extended') for p in platforms)):raise ValueError('Wybierz API lub indeksy')
                        with lock:
                            if job['running']:raise ValueError('Analiza już trwa')
                            stop.clear();job.update(running=True,error='',result=None)
                            threading.Thread(target=run,args=(project,None,options,roots,'bridges'),kwargs={'platforms':platforms},daemon=True).start()
                        result='Uruchomiono ograniczoną pętlę odkrywania nowych tropów'+(f' dla {len(roots)} kont' if len(roots)>1 else '')
                elif action == '/api/branches':
                    if type(data.get('auto_resume',True)) is not bool:raise ValueError('Nieprawidłowy tryb wznawiania')
                    from .branches import schema
                    schema(store)
                    project=int(data['project']);options=data.get('options',{})
                    if not isinstance(options,dict) or set(options)-{'queries','seconds','per_domain'} or any(type(v) is not int or v<0 for v in options.values()) or options.get('seconds',1)==0:raise ValueError('Nieprawidłowe limity drzewa')
                    if not store.rows('SELECT id FROM projects WHERE id=?',(project,)):raise ValueError('Nieznany projekt')
                    roots=data.get('roots');resume=data.get('resume')
                    if resume:
                        if not store.rows('SELECT id FROM branch_runs WHERE id=? AND project=?',(resume,project)):raise ValueError('Nieznane drzewo')
                    elif not isinstance(roots,list) or not 1<=len(roots)<=200 or any(type(i) is not int or store.node(i)['project']!=project for i in roots):raise ValueError('Wybierz poprawne profile')
                    with lock:
                        if job['running']:raise ValueError('Analiza już trwa')
                        stop.clear();job.update(running=True,error='')
                        threading.Thread(target=run,args=(project,resume,options,roots,'branches'),kwargs={'auto_resume':data.get('auto_resume',True)},daemon=True).start()
                    result='Uruchomiono drzewo odnośników'
                elif action == '/api/exposure-provider':
                    if data.get('operation') not in ('catalog','subscription'):raise ValueError('Nieznana operacja metadanych')
                    with lock:
                        if job['running']:raise ValueError('Analiza już trwa')
                        job.update(running=True,error='',result=None)
                        threading.Thread(target=run,args=(0,None,{'operation':data['operation']},None,'exposure-provider'),daemon=True).start()
                    result='Uruchomiono odczyt metadanych HIBP, bez identyfikatora użytkownika'
                elif action == '/api/exposure':
                    from .identity import EMAIL
                    if data.get('consent') is not True or not isinstance(data.get('account'),str) or not EMAIL.fullmatch(data['account']):raise ValueError('Podaj własny e-mail i potwierdź wysłanie go do HIBP')
                    project=int(data['project'])
                    if not store.rows('SELECT id FROM projects WHERE id=?',(project,)):raise ValueError('Nieznany projekt')
                    with lock:
                        if job['running']:raise ValueError('Analiza już trwa')
                        job.update(running=True,error='',result=None)
                        threading.Thread(target=run,args=(project,None,{'account':data['account'],'consent':True},None,'exposure'),daemon=True).start()
                    result='Uruchomiono sprawdzenie ekspozycji'
                elif action == '/api/manual-link':
                    from .xprofile import manual_link
                    result=manual_link(store,int(data['source']),data['url'],data['note'])
                elif action == '/api/focus': result=store.set_focus(int(data['project']),data.get('id'))
                elif action in ('/api/posts','/api/maigret'):
                    from .imports import posts,maigret
                    if action=='/api/posts' and store.node(int(data['source']))['project']!=int(data['project']):raise ValueError('Autor z innego projektu')
                    result=posts(store,int(data['source']),data['entries']) if action=='/api/posts' else maigret(store,int(data['project']),data['entries'])
                elif action=='/api/hints-mail':
                    # Reads only message headers of the user's own mailbox file; runs as a job (large files).
                    project=int(data['project'])
                    if not store.rows('SELECT id FROM projects WHERE id=?',(project,)):raise ValueError('Nieznany projekt')
                    if not isinstance(data.get('path'),str) or not data['path'].strip():raise ValueError('Podaj ścieżkę do pliku .mbox, folderu .eml lub archiwum .zip')
                    from pathlib import Path as _Path
                    if not _Path(data['path'].strip().strip('"')).expanduser().exists():raise ValueError('Nie znaleziono pliku ani folderu: '+data['path'].strip())
                    with lock:
                        if job['running']:raise ValueError('Analiza już trwa')
                        stop.clear();job.update(running=True,error='',result=None)
                        threading.Thread(target=run,args=(project,None,{'path':data['path']},None,'hints-mail'),daemon=True).start()
                    result='Przeglądanie nagłówków poczty uruchomione'
                elif action=='/api/hints-passwords':
                    from .accounthints import import_passwords
                    result=import_passwords(store,int(data['project']),text=data.get('text') if isinstance(data.get('text'),str) else None,path=data.get('path') if isinstance(data.get('path'),str) and data.get('path').strip() else None)
                elif action=='/api/hints-decide':
                    from .accounthints import decide as decide_hint
                    result=decide_hint(store,int(data['project']),str(data['domain']),data['status'])
                elif action=='/api/hints-clear':
                    from .accounthints import clear as clear_hints
                    result=clear_hints(store,int(data['project']),data.get('source'))
                elif action=='/api/import-accounts':
                    from .imports import import_accounts
                    lines=data.get('lines') if isinstance(data.get('lines'),list) else str(data.get('text','')).split(chr(10))
                    result=import_accounts(store,int(data['project']),lines,mine=bool(data.get('mine')))
                elif action in ("/api/scan", "/api/search", "/api/check",'/api/discover','/api/focused-scan','/api/focus-discover','/api/browser-check'):
                    with lock:
                        if job["running"]: raise ValueError("Analiza już trwa")
                        project = int(data["project"])
                        if not store.rows("SELECT id FROM projects WHERE id=?", (project,)): raise ValueError("Nieznany projekt")
                        targets = None
                        declared_note = ''
                        if action=='/api/discover' and not data.get('resume'):
                            from .declarations import apply as apply_declarations,describe as describe_declarations
                            data['nickname'],data['aliases'],data['criteria'],used=apply_declarations(store,project,data.get('nickname'),data.get('aliases',[]),data.get('criteria'))
                            declared_note=describe_declarations(used)
                        if action=='/api/focus-discover':
                            from .related import alias_suggestions
                            from .search import validate_nickname
                            selection=store.snapshot(project)['focus']
                            if not selection:raise ValueError('Wybierz konto odniesienia')
                            root=store.node(selection[0]['node'])
                            if root['ownership']=='not_mine':raise ValueError('Wybrane konto jest odrzucone')
                            fields=json.loads(root['data']);suggestions=alias_suggestions(store,project)
                            alias=fields.get('alias') or (suggestions[0]['alias'] if suggestions else '')
                            try:validate_nickname(alias)
                            except ValueError:alias=''
                            display=str(fields.get('display') or '')[:160]
                            if not alias and not display:raise ValueError('Najpierw odczytaj źródło; brak nazwy do wyszukania')
                            previous=store.rows('SELECT options FROM searches WHERE project=? ORDER BY id DESC LIMIT 1',(project,))
                            context=json.loads(previous[0]['options']).get('_criteria',{}) if previous else {}
                            context={**context,'known_urls':[]}
                            if display and not context.get('keywords'):context['keywords']=display
                            if not alias and not any(context.get(k) for k in ('first_name','last_name','keywords')):context['keywords']=display
                            data.update(verify_top=data.get('verify_top',5),nickname=alias,aliases=[s['alias'] for s in suggestions if s['alias']!=alias][:4],related=True,criteria=context,platforms=['GitHub','GitLab','Roblox','Bluesky'],options={'queries':40,'seconds':120,'candidates':50})
                            action='/api/discover'
                        mode='focused' if action=='/api/focused-scan' else 'discover' if action=='/api/discover' else 'browser' if action=='/api/browser-check' else 'scan'
                        if mode=='focused' and not store.snapshot(project)['focus']: raise ValueError('Wybierz profil')
                        if type(data.get('verify_top',0)) is not int or not 0<=data.get('verify_top',0)<=10:raise ValueError('Weryfikacja: od 0 do 10 profili')
                        if mode=='discover' and not data.get('resume'):
                            from .scanmodes import apply as apply_scan_mode
                            data=apply_scan_mode(data)
                        if type(data.get('auto_resume',True)) is not bool:raise ValueError('Nieprawidłowy tryb wznawiania')
                        historical=data.get('historical')
                        if historical is not None:
                            import datetime as _dt
                            if mode!='discover' or not isinstance(historical,dict) or set(historical)-{'date','limit'} or type(historical.get('limit',5)) is not int or not 1<=historical.get('limit',5)<=10:raise ValueError('Nieprawidłowe ustawienia archiwum')
                            try:day=_dt.date.fromisoformat(str(historical.get('date')))
                            except ValueError:raise ValueError('Data archiwum: RRRR-MM-DD')
                            if day>_dt.date.today():raise ValueError('Data archiwum jest w przyszłości')
                            historical={'date':day.isoformat(),'limit':historical.get('limit',5)}
                        if type(data.get('variants',False)) is not bool:raise ValueError('Nieprawidłowy tryb wariantów')
                        if type(data.get('auto_branches',False)) is not bool:raise ValueError('Nieprawidłowy tryb drzewa')
                        branch_opts=data.get('branch_options',{})
                        if not isinstance(branch_opts,dict) or set(branch_opts)-{'queries','seconds','per_domain'} or any(type(v) is not int or v<0 for v in branch_opts.values()) or branch_opts.get('seconds',1)==0:raise ValueError('Nieprawidłowe limity drzewa')
                        opts=data.get('options',{})
                        from .engine import DEFAULTS
                        allowed={'queries','seconds','per_domain','candidates'} if mode=='discover' else set(DEFAULTS)
                        if not isinstance(opts,dict) or set(opts)-allowed or any(type(v) is not int or v<0 for v in opts.values()) or opts.get('seconds',1)==0:raise ValueError('Nieprawidłowe limity')
                        if mode=='discover' and not data.get('resume'):
                            from .search import validate_nickname,ACTIVE,LIMITED,OPTIN
                            from .related import terms_for
                            from .context import criteria,terms
                            validated=criteria(data.get('criteria'))
                            if data.get('nickname') or not terms(validated):terms_for(data.get('nickname'),data.get('aliases',[]))
                            elif data.get('aliases'):raise ValueError('Aliasy wymagają głównego nicku')
                            if type(data.get('related',False)) is not bool:raise ValueError('Nieprawidłowy tryb')
                            if data.get('platforms') is not None:
                                if not isinstance(data['platforms'],list) or not data['platforms']: raise ValueError('Nie wybrano źródła')
                                unknown=[p for p in data['platforms'] if not isinstance(p,str) or p not in ACTIVE and p not in LIMITED and p not in OPTIN]
                                if unknown: raise ValueError('Nieznane źródło: '+', '.join(map(str,unknown)))
                        if action == "/api/search":
                            from .discovery import prepare_nickname
                            targets = prepare_nickname(store, project, data["nickname"])
                        elif action in ('/api/check','/api/browser-check'):
                            targets = data["ids"]
                            if not isinstance(targets, list) or not 1 <= len(targets) <= 100: raise ValueError("Nieprawidłowy wybór")
                            if any(type(i) is not int or store.node(i)["project"] != project for i in targets): raise ValueError("Nieprawidłowy wybór")
                        stop.clear(); job.update(running=True, error="")
                        threading.Thread(target=run, args=(project, data.get("resume"), data.get("options"), targets, mode, data.get('nickname'), data.get('platforms'),data.get('aliases',[]),data.get('related',False),data.get('criteria'),data.get('verify_top',0),data.get('auto_branches',False),data.get('branch_options'),data.get('auto_resume',True),data.get('variants',False),data.get('scan_mode','CUSTOM')), kwargs={'historical':historical if mode=='discover' else None}, daemon=True).start()
                    result = ("Uruchomiono · Twoje deklaracje w wyszukiwaniu: " + declared_note) if declared_note else "Uruchomiono"
                elif action == "/api/delete":
                    with lock:
                        if job["running"]: raise ValueError("Najpierw zatrzymaj analizę")
                        store.execute("DELETE FROM projects WHERE id=?", (int(data["project"]),)); store.execute("VACUUM"); result = "Usunięto"
                elif action == "/api/edit":
                    node = store.node(int(data["id"]))
                    from .identity import identify, email_key
                    item = identify(data["value"]) if node["kind"] in ("profile", "page", "project") else {"url": data["value"].strip() if node["kind"] == "email" else data["value"], "kind": node["kind"], "platform": node["platform"]}
                    # A changed address is a new declaration: retain the old node/evidence for audit history.
                    result = store.add(node["project"], item["url"], "url" if node["kind"] in ("profile", "page", "project") else node["kind"], seed=True)
                    store.execute("UPDATE nodes SET seed=0,user_added=0 WHERE id=?", (node["id"],))
                    # The edited entry keeps the user's own label (e.g. "mine") and stays in their list.
                    store.execute("UPDATE nodes SET user_added=1 WHERE id=?", (result,))
                    if node["ownership"] == "mine" and store.node(result)["ownership"] != "mine": store.decide(result, "mine")
                else: self.send({"error": "Nie znaleziono"}, 404); return
                self.send({"result": result})
            except ValueError as error:self.send({'error':str(error)},400)
            except (KeyError, TypeError, AttributeError, OverflowError): self.send({"error": "Nieprawidłowe dane lub stan operacji"}, 400)
            except Exception as error: self.failed(store, 'POST ' + self.path, error)
            finally: store.db.close()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    try:
        from .runtime import exclusive_runtime,recover
        with exclusive_runtime(db_path):
            startup=Store(db_path)
            try:job['recovered']=recover(startup)
            finally:startup.db.close()
            print(f"Panel: http://{authority} — Ctrl+C stops the server", flush=True)
            server.serve_forever()
    except KeyboardInterrupt: pass
    finally: stop.set(); server.server_close()
