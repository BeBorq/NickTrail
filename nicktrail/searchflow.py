"""Resumable per-source/per-term discovery tasks, with separate lead provenance."""
import json
import http.client
from .readstatus import note as note_read
from . import search as api
from .related import terms_for, search_related
from .engine import record
from .storage import now
from .network import Limit
from .indexes import INDEXES
from .community import STACK
from .stages import phase,exact_match,next_task,task_order


OWN='Moje konta'  # task label for reading the user's own confirmed accounts
MAX_DEFERRALS=3  # a service that refuses this many rounds in a row is left for a manual check

def defer_remote(store,search_id,platform,term,mode,detail):
    """Keep a rate-limited task for a later round, or give up on it after MAX_DEFERRALS.

    Returns True when the task stays pending (deferred), False when it was closed as blocked.
    Without this cap a single refusing service was retried first on every resume and
    kept the whole search from moving on."""
    row=store.rows('SELECT COALESCE(deferrals,0) n FROM search_tasks WHERE search=? AND platform=? AND term=? AND mode=?',(search_id,platform,term,mode))
    n=(row[0]['n'] if row else 0)+1
    if n>=MAX_DEFERRALS:
        store.execute("UPDATE search_tasks SET state='blocked',detail=?,deferrals=? WHERE search=? AND platform=? AND term=? AND mode=?",('Serwis odmówił '+str(n)+' razy z rzędu ('+(detail or 'limit zapytań')[:120]+'); pominięto, żeby nie blokować reszty wyszukiwania. Sprawdź ręcznie.',n,search_id,platform,term,mode))
        return False
    store.execute("UPDATE search_tasks SET state='pending',detail=?,deferrals=? WHERE search=? AND platform=? AND term=? AND mode=?",(detail,n,search_id,platform,term,mode))
    return True

def refresh_source(store,search_id,platform):
    tasks=store.rows('SELECT * FROM search_tasks WHERE search=? AND platform=? ORDER BY rowid',(search_id,platform))
    states=[t['state'] for t in tasks]
    ids=list(dict.fromkeys(i for t in tasks for i in json.loads(t['nodes'])))
    if not tasks:return
    if all(s=='pending' for s in states):state='partial' if ids else 'pending'
    elif any(s in ('pending','blocked','error','partial') for s in states) and (ids or len(set(states))>1):state='partial'
    elif 'partial' in states:state='partial'
    elif 'unverified' in states and all(v in ('unverified','not_found','unsupported') for v in states):state='unverified'
    elif ids:state='found'
    elif 'blocked' in states:state='blocked'
    elif 'error' in states:state='error'
    elif all(s=='unsupported' for s in states):state='unsupported'
    else:state='not_found'
    labels={'found':'znaleziono','not_found':'brak trafień','pending':'jeszcze nie sprawdzono','partial':'częściowo','blocked':'blokada','error':'błąd','unsupported':'nieobsługiwane'}
    detail=' | '.join(t['term']+' / '+('kryteria dodatkowe' if t['mode']=='context' else 'podobne nazwy' if t['mode']=='related' else 'nick lub alias')+': '+labels.get(t['state'],t['state'])+(' — '+t['detail'] if t['detail'] else '') for t in tasks)
    store.execute('UPDATE search_sources SET state=?,detail=?,nodes=? WHERE search=? AND platform=?',(state,detail,json.dumps(ids),search_id,platform))


def run(store,project,nickname=None,platforms=None,options=None,client=None,stopped=lambda:False,resume=None,aliases=(),related=False,criteria=None,lead_sources=None,stop_after_exact=False,variants=False,scan_mode='CUSTOM'):
    from .context import criteria as validate
    from .planning import words_queries as context_terms
    from .scanmodes import policy
    mode_policy=policy(scan_mode)
    if not resume and scan_mode not in ('CUSTOM','HISTORICAL'):
        platforms=mode_policy['platforms'];options=mode_policy['options'];related=mode_policy['related'];variants=mode_policy['variants']
    if scan_mode=='HISTORICAL':raise ValueError('Use the bounded historical endpoint')
    criteria=validate(criteria)
    api.schema(store)
    opts={'queries':40,'seconds':120,'per_domain':15,'candidates':50}|(options or {})
    if set(opts)!={'queries','seconds','per_domain','candidates'} or any(type(v) is not int or v<0 for v in opts.values()) or not opts['seconds']:raise ValueError('Nieprawidłowe limity wyszukiwania')
    if type(related) is not bool:raise ValueError('Nieprawidłowy tryb podobnych nazw')
    if type(variants) is not bool:raise ValueError('Nieprawidłowy tryb wariantów nicku')
    if not store.rows('SELECT id FROM projects WHERE id=?',(project,)):raise ValueError('Nieznany projekt')
    prior=0
    if resume:
        rows=store.rows('SELECT * FROM searches WHERE id=? AND project=?',(resume,project))
        if not rows or rows[0]['status'] not in ('paused','limited','running','failed','stage_ready'):raise ValueError('Nie można wznowić tego wyszukiwania')
        row=rows[0];search_id=resume;nickname=row['nickname'];opts=json.loads(row['options']);prior=row['requests']
        terms=opts.pop('_terms',[nickname]);related=opts.pop('_related',False)
        criteria=opts.pop('_criteria',validate())
        opts.pop('_verification',None)
        lead_sources=opts.pop('_lead_sources',None)
        opts.pop('_platforms',None)
        opts.pop('_pipeline',None)
        variants=opts.pop('_variants',False)
        scan_mode=opts.pop('_scan_mode','CUSTOM')
        if scan_mode!='CUSTOM':options=policy(scan_mode)['options']
        opts.setdefault('candidates',50)
        if options:
            saved=json.loads(row['options']);saved.update(options);store.execute('UPDATE searches SET options=? WHERE id=?',(json.dumps(saved),search_id));opts.update(options)
        if not store.rows('SELECT 1 FROM search_tasks WHERE search=?',(search_id,)):
            for source in store.rows("SELECT platform FROM search_sources WHERE search=? AND state='pending'",(search_id,)):
                store.execute("INSERT OR IGNORE INTO search_tasks(search,platform,term,mode) VALUES(?,?,?,'exact')",(search_id,source['platform'],nickname))
    else:
        if not nickname and context_terms(criteria):
            if aliases:raise ValueError('Aliasy wymagają głównego nicku')
            terms=[];nickname=context_terms(criteria)[0]
        else:
            terms=terms_for(nickname,aliases)
            nickname=terms[0]
        platforms=list(dict.fromkeys(platforms if platforms is not None else api.ACTIVE))
        unknown=[p for p in platforms if p not in api.ACTIVE and p not in api.LIMITED and p not in getattr(api,'OPTIN',())]
        if not platforms:raise ValueError('Nie wybrano źródła')
        if unknown:raise ValueError('Nieznane źródło: '+', '.join(map(str,unknown)))
        if not lead_sources:
            for term in terms:store.add(project,term,'alias')
        saved=opts|{'_terms':terms,'_related':related,'_criteria':criteria,'_platforms':platforms,'_variants':variants,'_scan_mode':scan_mode}
        if lead_sources:saved['_lead_sources']=lead_sources
        search_id=store.execute('INSERT INTO searches(project,nickname,started,status,options) VALUES(?,?,?,?,?)',(project,nickname,now(),'running',json.dumps(saved))).lastrowid
        from .providers import REGISTRY
        keyed=[id for id,provider in REGISTRY.items() if provider.available()]
        if platforms==list(api.ACTIVE):platforms+=[p for p in ('Steam','Mastodon') if p in keyed]
        for platform in dict.fromkeys(platforms+list(api.LIMITED)):
            disabled=platform in api.LIMITED and (platform not in keyed or platform not in platforms)
            store.execute('INSERT INTO search_sources(search,platform,state,detail) VALUES(?,?,?,?)',(search_id,platform,'unsupported' if disabled else 'pending',api.LIMITED.get(platform,'') if disabled else ''))
            if disabled:continue
            if platform=='Archive':
                # One archive-index query per (site, nick); slower than probes, so a later stage.
                from .archivesearch import sites as archive_sites
                batch=[(search_id,platform,site['id']+':'+alias,'archive') for site in archive_sites(store,project) for alias in terms]
                with store.db:
                    store.db.executemany('INSERT OR IGNORE INTO search_tasks(search,platform,term,mode) VALUES(?,?,?,?)',batch)
                if not terms:store.execute("UPDATE search_sources SET state='unsupported',detail='Podaj nick lub alias do wyszukania w archiwum.' WHERE search=? AND platform=?",(search_id,platform))
                continue
            if platform in ('Free','Extended','Sensitive'):
                from .frontier import ordered_services,snapshot
                ordered=ordered_services(snapshot(store,project)) if platform=='Free' else __import__('nicktrail.sensitive',fromlist=['sites']).sites() if platform=='Sensitive' else __import__('nicktrail.extended',fromlist=['services']).services()
                # Persist one complete platform batch before any HTTP; avoid a disk commit per definition/alias.
                batch=[(search_id,platform,service['id']+':'+alias,'probe') for service in ordered for alias in terms]
                with store.db:
                    store.db.executemany('INSERT OR IGNORE INTO search_tasks(search,platform,term,mode) VALUES(?,?,?,?)',batch)
                if not terms:store.execute("UPDATE search_sources SET state='unsupported',detail='Podaj nick lub alias do sprawdzania adresów profili.' WHERE search=? AND platform=?",(search_id,platform))
                continue
            if platform=='Catalog':
                from .catalog import queries
                for domain,query in queries(terms,criteria):store.execute('INSERT OR IGNORE INTO search_tasks(search,platform,term,mode) VALUES(?,?,?,?)',(search_id,platform,query,'context'))
                continue
            if not terms and platform not in ('GitHub','GitLab','Roblox','Bluesky')+INDEXES+tuple(STACK)+('Keybase',):
                store.execute("UPDATE search_sources SET state='unsupported',detail='Ten adapter wymaga nicku; brak wyszukiwania po nazwie.' WHERE search=? AND platform=?",(search_id,platform))
                continue
            for term in terms:
                modes=['exact','related'] if related and platform in ('GitHub','GitLab','Roblox','Bluesky') else ['exact']
                for mode in modes:store.execute('INSERT INTO search_tasks(search,platform,term,mode) VALUES(?,?,?,?)',(search_id,platform,term,mode))
        for platform in platforms:
            if platform not in ('GitHub','GitLab','Roblox','Bluesky')+INDEXES+tuple(STACK)+('Keybase',) or (platform in INDEXES and platform not in keyed):continue
            for term in context_terms(criteria):
                store.execute('INSERT OR IGNORE INTO search_tasks(search,platform,term,mode) VALUES(?,?,?,?)',(search_id,platform,term,'context'))
        for url in criteria['known_urls']:store.execute('UPDATE nodes SET user_added=1 WHERE id=?',(store.add(project,url),))
        if not lead_sources:
            # Read the user's own confirmed accounts first: their public links are the
            # strongest connections the map and the grouping can use.
            own=store.rows("SELECT id FROM nodes WHERE project=? AND ownership='mine' AND kind IN ('profile','page') AND platform!='Deklaracja' ORDER BY id LIMIT 25",(project,))
            for row in own:store.execute("INSERT OR IGNORE INTO search_tasks(search,platform,term,mode) VALUES(?,?,?,'enrich')",(search_id,OWN,str(row['id'])))
        if variants:
            from .variants import schedule
            schedule(store,search_id,terms,platforms)
    client=client or api.Client(queries=opts['queries'],seconds=opts['seconds'],per_domain=opts['per_domain'])
    from .cooldowns import bind as bind_cooldowns,flush as flush_writes
    bind_cooldowns(client,store)
    from .network import setting
    from .prefetch import Prefetcher
    local=getattr(client,'local',None)
    parallel=setting('parallel_hosts') if local is not None and callable(getattr(client,'host_lock',None)) else 1
    prefetcher=Prefetcher(client,parallel,lambda t:api.lookup(t['platform'],t['term'],client)) if parallel>1 else None
    status='completed';deferred=set();local_deferred=set();cooling=set()
    store.execute('INSERT OR IGNORE INTO search_runtime_metrics(search,peak_pending,measurement_started) VALUES(?,?,?)',(search_id,0,now()))
    peak_pending=store.rows('SELECT peak_pending FROM search_runtime_metrics WHERE search=?',(search_id,))[0]['peak_pending']
    seen={h['node'] for h in store.rows('SELECT DISTINCT node FROM candidate_hints WHERE search=?',(search_id,))}
    try:
        store.execute("UPDATE searches SET status='running' WHERE id=?",(search_id,))
        while True:
            task=None
            try:
                pending=store.rows("SELECT rowid AS ordinal,* FROM search_tasks WHERE search=? AND state='pending' ORDER BY rowid",(search_id,))
                if len(pending)>peak_pending:
                    peak_pending=len(pending);store.execute('UPDATE search_runtime_metrics SET peak_pending=? WHERE search=?',(peak_pending,search_id))
                # Weaker searches on a service that is pausing us would only hit the same limit.
                task=next_task([t for t in pending if (t['platform'],t['term'],t['mode']) not in deferred and not (t['platform'] in cooling and phase(t['platform'],t['mode']) not in ('A_EXACT','B_ENRICH'))])
                if not task:
                    if deferred:status='limited' if local_deferred else 'paused'
                    break
                if stopped():status='paused';break
                exact_stage=phase(task['platform'],task['mode']) in ('A_EXACT','B_ENRICH')
                # Cooling exact work is still unfinished exact work. Do not spend its
                # budget on broad fuzzy/name search merely because it is deferred.
                # Exact work waiting only for a service's own pause (HTTP 429) no longer
                # stops everything: weaker stages continue and the paused task is retried
                # next round (at most MAX_DEFERRALS times).
                if not exact_stage and any(phase(t['platform'],t['mode']) in ('A_EXACT','B_ENRICH') and (t['platform'],t['term'],t['mode']) in local_deferred for t in pending):status='limited';break
                if stop_after_exact and not exact_stage:status='stage_ready';break
                # Exact supplied aliases have their own request budget, never a fuzzy candidate cap.
                weak_seen={h['node'] for h in store.rows("SELECT DISTINCT node FROM candidate_hints WHERE search=? AND basis='service_search'",(search_id,))}
                if not exact_stage and len(weak_seen)>=opts['candidates']:status='limited';break
                platform,term,task_mode=task['platform'],task['term'],task['mode']
                from .protocol import begin as protocol_begin,record as protocol_record
                protocol_start=protocol_begin(client)
                parts=task_mode.split('|',2);mode=parts[0];page=int(parts[1]) if len(parts)>1 else 1;cursor=parts[2] if len(parts)>2 else None
                if mode=='enrich':
                    task_count=client.count
                    id=int(term);node=store.node(id)
                    if node['ownership']=='not_mine':result={'state':'unsupported','detail':'Odrzucone przez użytkownika'}
                    else:
                        from .engine import scan
                        start_count=client.count
                        class View:
                            @property
                            def count(self):return client.count-start_count
                            def get(self,*a,**kw):return client.get(*a,**kw)
                            def profile_get(self,url):return getattr(client,'profile_get',client.get)(url)
                            def post_json(self,*a,**kw):return client.post_json(*a,**kw)
                        scan_id=scan(store,project,{'queries':max(0,opts['queries']-client.count),'profiles':1,'pages':1},targets=[id],client=View(),stopped=stopped)
                        observed=store.rows('SELECT state,detail FROM observations WHERE scan=? AND node=?',(scan_id,id))
                        if not observed:
                            store.execute('UPDATE search_tasks SET requests=COALESCE(requests,0)+? WHERE search=? AND platform=? AND term=? AND mode=?',(client.count-task_count,search_id,platform,term,task_mode))
                            protocol_record(store,search_id,platform,term,task_mode,client,protocol_start)
                            status='paused' if stopped() else 'limited';break
                        result=observed[0]
                    store.execute('UPDATE search_tasks SET requests=COALESCE(requests,0)+? WHERE search=? AND platform=? AND term=? AND mode=?',(client.count-task_count,search_id,platform,term,task_mode))
                    protocol_record(store,search_id,platform,term,task_mode,client,protocol_start)
                    detail=result.get('detail','').casefold()
                    local_wait=result['state']=='blocked' and 'limit domeny' in detail
                    remote_wait=result['state']=='blocked' and any(text in detail for text in ('http 429','rate_limited','przerwa zalecona przez api','retry-after'))
                    if local_wait:
                        key=(platform,term,task_mode);deferred.add(key);local_deferred.add(key)
                        store.execute("UPDATE search_tasks SET state='pending',detail=?,nodes=? WHERE search=? AND platform=? AND term=? AND mode=?",('LOCAL_DOMAIN_BUDGET: '+result.get('detail',''),json.dumps([id]),search_id,platform,term,task_mode))
                        refresh_source(store,search_id,platform);continue
                    if remote_wait:
                        if defer_remote(store,search_id,platform,term,task_mode,result.get('detail','')):deferred.add((platform,term,task_mode));cooling.add(platform)
                        refresh_source(store,search_id,platform);continue
                    store.execute('UPDATE search_tasks SET state=?,detail=?,nodes=? WHERE search=? AND platform=? AND term=? AND mode=?',(result['state'],result.get('detail',''),json.dumps([id]),search_id,platform,term,task_mode))
                    note_read(store,id,result['state'],result.get('detail',''))
                    refresh_source(store,search_id,platform)
                    store.execute('UPDATE searches SET requests=? WHERE id=?',(prior+client.count,search_id))
                    continue
                checkpoint=store.rows('SELECT * FROM search_task_payloads WHERE search=? AND platform=? AND term=? AND mode=?',(search_id,platform,term,task_mode))
                offset=checkpoint[0]['offset'] if checkpoint else 0
                task_count=client.count;task_key=(platform,term,task_mode);prefetched=None;task_requests=None
                if local is not None:local.task,local.count=task_key,0
                if prefetcher and task_mode=='probe' and not checkpoint:
                    upcoming=sorted((t for t in pending if t['mode']=='probe' and (t['platform'],t['term'],t['mode']) not in deferred),key=task_order)
                    prefetcher.schedule(upcoming[:parallel*2])
                    prefetched=prefetcher.take(task_key)
                try:
                    if checkpoint:result=json.loads(checkpoint[0]['result'])
                    elif prefetched:
                        kind,value,task_requests=prefetched
                        if kind=='raise':raise value
                        result=value
                    else:result=(api.bluesky_search(term,client) if platform=='Bluesky' else api.lookup(platform,term,client) if platform in ('Catalog',)+INDEXES+tuple(STACK)+('Keybase',) else search_related(platform,term,client,contextual=True,page=page,cursor=cursor)) if mode=='context' else (api.bluesky_search(term,client) if platform=='Bluesky' else search_related(platform,term,client,page=page,cursor=cursor)) if mode=='related' else api.lookup(platform,term,client)
                except Limit:status='limited';break
                except (OSError,ValueError,KeyError,TypeError,http.client.HTTPException) as error:result={'state':'error','detail':type(error).__name__}
                finally:
                    used=task_requests if task_requests is not None else getattr(local,'count',None) if local is not None else client.count-task_count
                    store.execute('UPDATE search_tasks SET requests=COALESCE(requests,0)+? WHERE search=? AND platform=? AND term=? AND mode=?',(used if used is not None else client.count-task_count,search_id,platform,term,task_mode))
                    protocol_record(store,search_id,platform,term,task_mode,client,(0,0) if prefetched and protocol_start is not None else protocol_start,bool(checkpoint),task=task_key if local is not None else None)
                    if local is not None:local.task=None
                    flush_writes(client,store)
                remote_rate_limited=result['state']=='blocked' and any(text in result.get('detail','').casefold() for text in ('http 429','rate_limited','przerwa zalecona przez api','retry-after'))
                if result['state']=='blocked' and 'limit domeny' in result.get('detail','').casefold():
                    key=(platform,term,task_mode);deferred.add(key);local_deferred.add(key)
                    store.execute("UPDATE search_tasks SET state='pending',detail='LOCAL_DOMAIN_BUDGET: limit domeny tej rundy; zadanie oczekuje na wznowienie' WHERE search=? AND platform=? AND term=? AND mode=?",(search_id,platform,term,task_mode))
                    refresh_source(store,search_id,platform);continue
                if remote_rate_limited:
                    if defer_remote(store,search_id,platform,term,task_mode,result.get('detail','')):deferred.add((platform,term,task_mode));cooling.add(platform)
                    refresh_source(store,search_id,platform);continue
                if platform=='Catalog' and result.get('detail','').endswith('Limit domeny'):status='limited';break
                if exact_stage and platform=='Bluesky':
                    result=dict(result);result['matches']=[m for m in result.get('matches',[]) if exact_match(m.get('data',{}),[term],'Bluesky')]
                    if result['state']=='found' and not result['matches']:result['state']='not_found'
                    result['detail']=result.get('detail','')+' Etap A: tylko dokładny nick/handle; podobne nazwy osobno.'
                if result.get('matches') and not checkpoint:
                    payload={key:result[key] for key in ('state','detail','matches','next_page','cursor') if key in result}
                    store.execute('INSERT OR REPLACE INTO search_task_payloads(search,platform,term,mode,result,offset) VALUES(?,?,?,?,?,0)',(search_id,platform,term,task_mode,json.dumps(payload)))
                # Search-result absence cannot invalidate an account. Only an exact lookup can.
                if mode=='exact' and result['state'] in ('not_found','blocked','error') and platform not in ('Bluesky','Catalog')+INDEXES+tuple(STACK)+('Keybase',):
                    previous=store.rows("SELECT nodes FROM search_tasks t JOIN searches s ON s.id=t.search WHERE s.project=? AND t.term=? COLLATE NOCASE AND t.platform=? AND t.mode='exact' AND t.search!=?",(project,term,platform,search_id))
                    if not previous:
                        previous=store.rows('SELECT ss.nodes FROM search_sources ss JOIN searches s ON s.id=ss.search WHERE s.project=? AND s.nickname=? COLLATE NOCASE AND ss.platform=? AND s.id!=?',(project,term,platform,search_id))
                    for old in previous:
                        for id in json.loads(old['nodes']):
                            store.execute('UPDATE nodes SET state=? WHERE id=?',(result['state'],id))
                            note_read(store,id,result['state'],result.get('detail',''))
                ids=json.loads(task['nodes'])
                for match_index,match in enumerate(result.get('matches',[])[offset:],start=offset):
                    if not exact_stage and len(weak_seen)>=opts['candidates']:
                        result['state']='partial';result['detail']=result.get('detail','')+' Osiągnięto limit kandydatów; część trafień pominięta.'
                        status='limited';break
                    previous_state=store.rows('SELECT state FROM nodes WHERE project=? AND url=?',(project,match['url']))
                    if platform not in INDEXES+('Catalog','Archive') and result['state'] in ('found','partial'):match['data']=match['data']|{'indexed_only':False}
                    try:id=store.apply_profile(project,match['url'],match['data'],partial=True)
                    except ValueError as error:
                        result['state']='error';result['detail']=str(error)
                        store.execute('UPDATE search_task_payloads SET offset=? WHERE search=? AND platform=? AND term=? AND mode=?',(match_index+1,search_id,platform,term,task_mode));continue
                    if platform in INDEXES+('Catalog','Archive') or result['state']=='unverified':store.execute('UPDATE nodes SET state=? WHERE id=?',((previous_state[0]['state'] if previous_state else 'unverified'),id))
                    if platform in INDEXES+('Catalog','Archive'):
                        indexed=match['data']
                        store.execute('INSERT OR REPLACE INTO indexed_results VALUES(?,?,?,?,?,?,?,?)',(project,id,search_id,platform,term,str(indexed.get('search_title',''))[:300],str(indexed.get('search_snippet',''))[:500],now()))
                    node=store.node(id)
                    if node['ownership']!='not_mine':record(store,node,match.get('evidence',[]))
                    basis='derived_public_lead' if lead_sources else 'separator_variant' if mode=='variant' else 'service_search' if mode in ('related','context') or platform in ('Catalog',)+INDEXES+tuple(STACK) else 'exact_nickname' if term.lower()==nickname.lower() else 'provided_alias'
                    store.execute('INSERT OR IGNORE INTO candidate_hints(project,node,search,term,basis,created) VALUES(?,?,?,?,?,?)',(project,id,search_id,term,basis,now()))
                    if exact_stage and platform in ('Roblox','Bluesky') and not match.get('enriched'):
                        store.execute("INSERT OR IGNORE INTO search_tasks(search,platform,term,mode) VALUES(?,?,?,'enrich')",(search_id,platform,str(id)))
                    seen.add(id)
                    if not exact_stage:weak_seen.add(id)
                    ids.append(id)
                    store.execute('UPDATE search_task_payloads SET offset=? WHERE search=? AND platform=? AND term=? AND mode=?',(match_index+1,search_id,platform,term,task_mode))
                store.execute('UPDATE search_tasks SET state=?,detail=?,nodes=? WHERE search=? AND platform=? AND term=? AND mode=?',('pending' if status=='limited' else result['state'],result.get('detail',''),json.dumps(list(dict.fromkeys(ids))),search_id,platform,term,task_mode))
                if status!='limited':store.execute('DELETE FROM search_task_payloads WHERE search=? AND platform=? AND term=? AND mode=?',(search_id,platform,term,task_mode))
                if status!='limited' and result.get('next_page') and mode in ('related','context') and platform in ('GitHub','GitLab','Roblox'):
                    next_mode=mode+'|'+str(result['next_page'])+('|' + result['cursor'] if result.get('cursor') else '')
                    store.execute('INSERT OR IGNORE INTO search_tasks(search,platform,term,mode) VALUES(?,?,?,?)',(search_id,platform,term,next_mode))
                refresh_source(store,search_id,platform)
                store.execute('UPDATE searches SET requests=? WHERE id=?',(prior+client.count,search_id))
                if status=='limited':break
            except Limit:
                # The round's request or time budget ran out mid-task: the task stays pending.
                status='limited';break
            except Exception as error:
                if task is None:raise
                # One site or one odd response must not end the whole search.
                from .errorlog import write as log_error
                log_error(store,'search #'+str(search_id)+' '+str(task['platform'])+' '+str(task['term'])+' '+str(task['mode']),error)
                store.execute('UPDATE search_tasks SET state=?,detail=? WHERE search=? AND platform=? AND term=? AND mode=?',('error','Błąd programu przy tym serwisie ('+type(error).__name__+'); pominięto, wyszukiwanie trwa dalej. Szczegóły w pliku .errors.log obok bazy.',search_id,task['platform'],task['term'],task['mode']))
                refresh_source(store,search_id,task['platform']);continue
    except KeyboardInterrupt:status='paused'
    except Exception as error:
        status='failed'
        from .errorlog import write as log_error
        log_error(store,'search #'+str(search_id),error)
        raise
    finally:
        if prefetcher:prefetcher.close()
        flush_writes(client,store)
        store.execute('UPDATE searches SET status=?,finished=?,requests=? WHERE id=?',(status,now(),prior+client.count,search_id))
    return search_id
