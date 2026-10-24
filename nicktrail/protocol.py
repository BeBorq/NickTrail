"""Persistent aggregate HTTP accounting. No query/URL/body/header retention."""
import json
KINDS=('request_sent','response','cache_hit','policy_block','budget_block','rate_cooldown','rate_limit','network_error','timeout')

def begin(client):
 events=getattr(client,'events',None)
 return (len(events),getattr(client,'events_truncated',0)) if isinstance(events,list) else None

def record(store,search,platform,term,mode,client,start,payload_reuse=False,task=None):
 if start is None:return
 events=client.events[start[0]:]
 # With parallel reads, events carry the task that caused them.
 if task is not None:events=[e for e in events if e.get('task',task)==task]
 counts={kind:sum(e['kind']==kind for e in events) for kind in KINDS}
 counts['policy_requests_sent']=sum(e['kind']=='request_sent' and e.get('purpose')=='policy' for e in events)
 counts['content_requests_sent']=sum(e['kind']=='request_sent' and e.get('purpose')=='content' for e in events)
 counts['uncategorized_requests_sent']=sum(e['kind']=='request_sent' and e.get('purpose') not in ('policy','content') for e in events)
 counts['payload_reuse']= int(payload_reuse);counts['events_truncated']=max(0,getattr(client,'events_truncated',0)-start[1])
 counts['response_body_bytes']=sum(e.get('bytes',0) for e in events if e['kind']=='body_bytes')
 counts['transport_v2_invocations']=int(getattr(client,'metrics_v2',False))
 previous=store.rows('SELECT * FROM search_task_protocol WHERE search=? AND platform=? AND term=? AND mode=?',(search,platform,term,mode))
 old=json.loads(previous[0]['counts']) if previous else {}
 combined={key:old.get(key,0)+counts.get(key,0) for key in set(old)|set(counts)}
 store.execute('INSERT OR REPLACE INTO search_task_protocol VALUES(?,?,?,?,?,?)',(search,platform,term,mode,(previous[0]['invocations'] if previous else 0)+1,json.dumps(combined)))

def summary(store,search,tasks):
 rows=store.rows('SELECT * FROM search_task_protocol WHERE search=?',(search,)) if store else []
 totals={kind:0 for kind in KINDS+('policy_requests_sent','content_requests_sent','uncategorized_requests_sent','payload_reuse','events_truncated')}
 for row in rows:
  for key,value in json.loads(row['counts']).items():totals[key]=totals.get(key,0)+value
 from .stages import phase
 stages={}
 for row in rows:
  stage=stages.setdefault(phase(row['platform'],row['mode']),{'invocations':0,'events':{}});stage['invocations']+=row['invocations']
  for key,value in json.loads(row['counts']).items():stage['events'][key]=stage['events'].get(key,0)+value
 keys={(r['platform'],r['term'],r['mode']) for r in rows}
 terminal=[t for t in tasks if t['state'] not in ('pending','searching')]
 missing=sum((t['platform'],t['term'],t['mode']) not in keys for t in terminal)
 runtime=store.rows('SELECT * FROM search_runtime_metrics WHERE search=?',(search,)) if store and store.rows("SELECT name FROM sqlite_master WHERE name='search_runtime_metrics'") else []
 detailed=bool(rows) and all(json.loads(r['counts']).get('transport_v2_invocations',0)==r['invocations'] for r in rows) and not totals['events_truncated'] and not missing
 return {'runtime_metrics':runtime[0] if runtime else None,'runtime_metrics_scope':'since instrumentation began, not a reconstruction of older invocations','detailed_transport_complete':detailed,'by_phase':stages,'scope':'discovery task invocations; branch HTTP attribution is separate/legacy','recorded_tasks':len(rows),'terminal_tasks_without_protocol':missing,'attribution_complete':not missing and not totals['events_truncated'] and not any(t['state'] in ('pending','searching') for t in tasks),'scheduled_tasks':len(tasks),'terminal_tasks':len(terminal),'skipped_unsupported_tasks':sum(t['state']=='unsupported' for t in terminal),'events':totals,'note':'HTTP events include redirects and policy requests; content requests are separate from robots. Outcomes, policy/cache events and task counts overlap and must not be added as disjoint populations. Legacy or unsupported clients remain unknown, never zero.'}
