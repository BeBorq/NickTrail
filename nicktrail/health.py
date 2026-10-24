"""Explicit low-volume paired service validation, cached for at least one day."""
import datetime,hashlib,json,time,re,http.client
from .storage import SCHEMA_LOCK

def schema(store):
 with SCHEMA_LOCK:
  store.db.execute('''CREATE TABLE IF NOT EXISTS service_health(service TEXT PRIMARY KEY,checked_at REAL,last_success REAL,status TEXT,positive_state TEXT,negative_state TEXT,reason TEXT,confidence TEXT,requests INTEGER,control_hash TEXT,positive_passed INTEGER,negative_passed INTEGER)''');store.db.commit()
  columns={r[1] for r in store.db.execute('PRAGMA table_info(service_health)')}
  for name,kind in (('validation_kind',"TEXT DEFAULT 'unknown'"),('telemetry',"TEXT DEFAULT '{}'"),('retry_at','REAL'),('definition_hash','TEXT')):
   if name not in columns:store.db.execute('ALTER TABLE service_health ADD COLUMN '+name+' '+kind)
  store.db.execute('''CREATE TABLE IF NOT EXISTS service_health_runs(id INTEGER PRIMARY KEY,service TEXT,checked_at REAL,validation_kind TEXT,record TEXT)''');store.db.commit()

def latest(store):
 schema(store)
 return {row['service']:row for row in store.rows('SELECT * FROM service_health')}

def validate(store,service,positive,negative,client=None):
 from .search import validate_nickname
 from .providers import REGISTRY,lookup
 from .network import Client,Limit
 from .stages import exact_match
 from .diagnostics import reason
 from .identity import identify
 if not isinstance(service,str) or ':' not in service:raise ValueError('Use provider:ID, Free:ID or Extended:ID')
 family,id=service.split(':',1);positive=validate_nickname(positive);negative=validate_nickname(negative)
 if positive.casefold()==negative.casefold():raise ValueError('Positive and negative controls must differ')
 if family=='provider':
  if id not in REGISTRY or not REGISTRY[id].supports_exact or not REGISTRY[id].available():raise ValueError('Health checks require a configured exact public API')
  if not all(REGISTRY[id].valid_username(alias) for alias in (positive,negative)):raise ValueError('Kontrola nie spełnia reguł nicku serwisu; nie wysłano zapytania')
  platform=id;term=lambda alias:alias
 elif family in ('Free','Extended'):
  definitions=__import__('nicktrail.servicecatalog',fromlist=['services']).services() if family=='Free' else __import__('nicktrail.extended',fromlist=['services']).services()
  definition=next((row for row in definitions if row['id']==id),None)
  if definition is None:raise ValueError('Unknown service definition')
  if not all(re.fullmatch(definition['username_pattern'],alias) for alias in (positive,negative)):raise ValueError('Kontrola nie spełnia reguł definicji; nie wysłano zapytania')
  platform=family;term=lambda alias:id+':'+alias
 else:raise ValueError('Unsupported health family')
 from .healthrevision import fingerprint
 revision=fingerprint(service)
 schema(store);cached=store.rows('SELECT * FROM service_health WHERE service=?',(service,));digest=hashlib.sha256((positive+'\0'+negative).encode()).hexdigest()
 if cached and (time.time()-cached[0]['checked_at']<86400 or (cached[0].get('retry_at') or 0)>time.time()):
  # A fixture must not prevent the first real validation; live cooldowns always apply.
  if client is not None or cached[0]['confidence']!='control_response_tested':return cached[0]|{'cached':True,'requested_controls_match':cached[0]['control_hash']==digest,'definition_matches':cached[0].get('definition_hash')==revision}
 session=client or Client(queries=8,seconds=45,per_domain=8,timeout=8,delay=1)
 from .cooldowns import bind as bind_cooldowns
 bind_cooldowns(session,store)
 responses=[];control_events=[];initial=session.count;event_start=len(getattr(session,'events',[]));started=time.monotonic()
 for alias in (positive,negative):
  control_start=len(getattr(session,'events',[]))
  try:r=lookup(platform,term(alias),session)
  except Limit:r={'state':'error','detail':'HEALTH_BUDGET_EXHAUSTED'}
  except (ValueError,KeyError,TypeError,OSError,http.client.HTTPException) as e:r={'state':'error','detail':type(e).__name__}
  responses.append(r)
  control_events.append(getattr(session,'events',[])[control_start:])
  if r['state']=='blocked' or reason(r['state'],r.get('detail','')) in ('RATE_LIMITED','LOGIN_REQUIRED','CAPTCHA','NETWORK_ERROR','DNS_ERROR'):
   if len(responses)==1:
    responses.append({'state':'not_tested','detail':'Second control skipped after access restriction'});control_events.append([])
   break
 a,b=responses
 passed_a=a['state']=='found' and any(exact_match(m.get('data',{}),[positive],id) for m in a.get('matches',[]))
 passed_b=b['state']=='not_found' and not b.get('matches')
 codes=[reason(r['state'],r.get('detail','')) for r in responses]
 if passed_a and passed_b:
  state='EXACT_ONLY' # The paired test validates exact detection, not all declared enrichment capabilities.
 elif b['state']=='found' and b.get('matches') or a['state']=='not_found':state='BROKEN'
 elif 'UPSTREAM_INPUT_ERROR' in codes or 'USERNAME_RULE_REJECTED' in codes or 'API_REQUEST_REJECTED' in codes and not passed_a:state='UNKNOWN'
 elif 'RATE_LIMITED' in codes:state='RATE_LIMITED'
 elif 'LOGIN_REQUIRED' in codes:state='LOGIN_REQUIRED'
 elif any(r['state']=='blocked' for r in responses):state='BLOCKED'
 elif passed_a:state='PARTIAL'
 elif any(r['state']=='error' for r in responses):state='BROKEN'
 else:state='MANUAL'
 checked=time.time();success=checked if passed_a and passed_b else (cached[0]['last_success'] if cached and cached[0].get('validation_kind')!='fixture' else None)
 detail='paired controls passed' if passed_a and passed_b else '; '.join(c for c in codes if c!='UNKNOWN') or 'Controls did not conclusively validate the detector'
 row={'service':service,'checked_at':checked,'last_success':success,'status':state,'positive_state':a['state'],'negative_state':b['state'],'reason':detail,'confidence':('control_response_tested' if client is not None else 'paired_live_controls') if passed_a and passed_b else 'unconfirmed','requests':session.count-initial,'control_hash':digest,'positive_passed':int(passed_a),'negative_passed':int(passed_b)}
 events=getattr(session,'events',[])[event_start:];http_statuses=[e['status'] for e in events if e['kind']=='response'];wait=max((e['retry_after_seconds'] for e in events if e['kind']=='rate_limit'),default=0)
 telemetry={'elapsed_seconds':round(time.monotonic()-started,3),'http_status_counts':{str(s):http_statuses.count(s) for s in sorted(set(http_statuses))},'average_response_status':sum(http_statuses)/len(http_statuses) if http_statuses else None,'requests_sent':sum(e['kind']=='request_sent' for e in events),'responses_received':len(http_statuses),'cache_hits':sum(e['kind']=='cache_hit' for e in events),'redirect_responses':sum(bool(e.get('redirect')) for e in events),'events_truncated':getattr(session,'events_truncated',0),'positive_detail':str(a.get('detail',''))[:1000],'negative_detail':str(b.get('detail',''))[:1000],'redirect_coverage':'observed' if any(e.get('redirect') for e in events) else 'not_exercised','soft_404_coverage':'rejected_http_200_control' if passed_b and any(e['kind']=='response' and e['status']==200 for e in control_events[1]) else 'not_exercised','case_coverage':'not_exercised'}
 telemetry['controls']=[{'control':label,'state':r['state'],'http_statuses':[e['status'] for e in events if e['kind']=='response'],'requests_sent':sum(e['kind']=='request_sent' for e in events),'cache_hits':sum(e['kind']=='cache_hit' for e in events)} for label,r,events in zip(('positive','negative'),responses,control_events)]
 row.update(validation_kind='fixture' if client is not None else 'live',telemetry=json.dumps(telemetry),retry_at=checked+wait if wait else None,definition_hash=revision)
 store.execute('INSERT OR REPLACE INTO service_health('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
 store.execute('INSERT INTO service_health_runs(service,checked_at,validation_kind,record) VALUES(?,?,?,?)',(service,checked,row['validation_kind'],json.dumps(row)))
 return row|{'cached':False,'positive_passed':passed_a,'negative_passed':passed_b}
