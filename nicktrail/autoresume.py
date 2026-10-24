"""Bounded continuation of budget-limited queues, with cancellation and stall detection."""
import json
import time

COOLDOWN_WAIT = 300   # wait for a provider's own pause only when it ends soon
COOLDOWN_ROUNDS = 3   # and only a few times, so a service that keeps refusing is left alone
ROUND_CAP = 200       # continuation is driven by progress; this only guards against a runaway loop
LIMIT_WORDS = ('http 429','rate_limited','przerwa zalecona przez api','retry-after')

def cooldown_end(store,id):
 """When the provider pause blocking the remaining tasks ends, if it ends soon."""
 pending=store.rows("SELECT detail FROM search_tasks WHERE search=? AND state='pending'",(id,))
 if not pending or not any(any(w in (r['detail'] or '').casefold() for w in LIMIT_WORDS) for r in pending):return None
 if not store.rows("SELECT name FROM sqlite_master WHERE name='provider_cooldowns'"):return None
 now=time.time();ends=[r['until_epoch'] for r in store.rows('SELECT until_epoch FROM provider_cooldowns WHERE until_epoch>?',(now,))]
 if not ends:return now  # the pause is already over: retry right away
 short=[e for e in ends if e-now<=COOLDOWN_WAIT]
 return max(short) if short else None

def wait_out(store,id,stopped,pause):
 """Wait for a short provider pause; True when the search may continue."""
 end=cooldown_end(store,id)
 if end is None:return False
 while time.time()<end+1:
  if pause() or stopped():return False
 store.execute("UPDATE searches SET status='limited' WHERE id=? AND status IN ('paused','limited')",(id,))
 return True

def release_cooling(store,id):
 """Close tasks that still wait for a service's pause, so the rest of the search can finish."""
 rows=store.rows("SELECT platform,term,mode,detail FROM search_tasks WHERE search=? AND state='pending'",(id,))
 waiting=[r for r in rows if any(w in (r['detail'] or '').casefold() for w in LIMIT_WORDS)]
 for r in waiting:
  store.execute("UPDATE search_tasks SET state='blocked',detail=? WHERE search=? AND platform=? AND term=? AND mode=?",('Serwis wciąż wstrzymuje zapytania ('+(r['detail'] or '')[:100]+'); pominięto, żeby dokończyć resztę. Sprawdź ręcznie albo wznów później.',id,r['platform'],r['term'],r['mode']))
 if waiting:store.execute("UPDATE searches SET status=? WHERE id=?",('limited' if len(waiting)<len(rows) else 'completed',id))
 return len(waiting)<len(rows) if waiting else False

def search(store,project,id,stopped=lambda:False,pause=lambda:False,max_rounds=50,stop_after_exact=False):
 from .search import discover
 waits=0
 for _ in range(max_rounds):
  row=store.rows('SELECT * FROM searches WHERE id=? AND project=?',(id,project))[0]
  pending=store.rows("SELECT COUNT(*) n FROM search_tasks WHERE search=? AND state='pending'",(id,))[0]['n']
  opts=json.loads(row['options'])
  from .stages import phase
  pending_exact=any(phase(t['platform'],t['mode'])in ('A_EXACT','B_ENRICH') for t in store.rows("SELECT platform,mode FROM search_tasks WHERE search=? AND state='pending'",(id,)))
  weak=store.rows("SELECT COUNT(DISTINCT node) n FROM candidate_hints WHERE search=? AND basis='service_search'",(id,))[0]['n']
  if row['status']=='paused' and pending and not stopped():
   # Only tasks waiting for a service's pause are left: sit out a short pause a few
   # times, then close those tasks so the remaining work is not held up by one site.
   if waits<COOLDOWN_ROUNDS:
    waits+=1
    if wait_out(store,id,stopped,pause):continue
   if stopped():break
   if release_cooling(store,id):continue
  if stopped() or row['status']!='limited' or not pending or (not pending_exact and weak>=opts.get('candidates',50)):break
  if pause() or stopped():break
  discover(store,project,resume=id,stopped=stopped,stop_after_exact=stop_after_exact)
  after=store.rows("SELECT COUNT(*) n FROM search_tasks WHERE search=? AND state='pending'",(id,))[0]['n']
  current=store.rows('SELECT requests FROM searches WHERE id=?',(id,))[0]['requests']
  if after>=pending and current<=row['requests']:
   # No progress. If every remaining task only waits for a service's own short pause
   # (HTTP 429 / Retry-After), wait it out instead of leaving the search at 99%.
   if waits>=COOLDOWN_ROUNDS:break
   waits+=1
   if not wait_out(store,id,stopped,pause):break
 return id

def branches(store,project,id,options=None,stopped=lambda:False,pause=lambda:False,max_rounds=50):
 from .branches import explore
 for _ in range(max_rounds):
  row=store.rows('SELECT * FROM branch_runs WHERE id=? AND project=?',(id,project))[0]
  pending=store.rows("SELECT COUNT(*) n FROM branch_nodes WHERE run=? AND state IN ('pending','searching')",(id,))[0]['n']
  if stopped() or row['status']!='limited' or not pending or pause() or stopped():break
  explore(store,project,options=options,resume=id,stopped=stopped)
  after=store.rows('SELECT requests,status FROM branch_runs WHERE id=?',(id,))[0]
  remaining=store.rows("SELECT COUNT(*) n FROM branch_nodes WHERE run=? AND state IN ('pending','searching')",(id,))[0]['n']
  if remaining>=pending and after['requests']<=row['requests']:break
 return id

def progress(tasks):
 total=len(tasks);done=sum(t['state'] not in ('pending','searching') for t in tasks)
 counts={state:sum(t['state']==state for t in tasks) for state in ('found','not_found','blocked','error','partial','unsupported','pending','searching')}
 groups={}
 for t in tasks:
  platform=t.get('platform','nieznane');term=t.get('term','')
  site=term.split(':',1)[0] if platform in ('Free','Extended','Archive') else term.split(' ',1)[0] if platform=='Catalog' else platform
  groups.setdefault((platform,site),[]).append(t['state'])
 sites_done=sum(all(state not in ('pending','searching') for state in values) for values in groups.values())
 percent=round(100*done/total,1) if total else 0
 return {'sites_total':len(groups),'sites_done':sites_done,'total':total,'done':done,'percent':percent,'remaining_percent':round(100-percent,1),'counts':counts}
