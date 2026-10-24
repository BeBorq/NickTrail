"""Offline service inventory and evidence-backed maintenance priorities, not a support claim."""
import json,time
from collections import Counter
from urllib.parse import urlsplit
from .capabilities import matrix
from .servicecatalog import services as native
from .extended import services as imported
from .providers import REGISTRY
from .engineconfig import instances
from .forums import HOSTS

STATES=('HEALTHY','PARTIAL','UNTESTED','BROKEN','BLOCKED','LOGIN_REQUIRED','RATE_LIMITED','MANUAL_ONLY','DISABLED','UNKNOWN')
BRIDGES={'linktree','carrd','aboutme','beacons','bento','biosite','taplink','gravatar','keybase'}

def inventory(store,clock=None):
 now=time.time() if clock is None else clock
 trials={}
 # Bounded recent operational history; fixture/invalid-control trials are excluded.
 from .health import schema
 schema(store)
 for trial in store.rows("SELECT service,record FROM service_health_runs WHERE validation_kind='live' ORDER BY id DESC LIMIT 5000"):
  record=json.loads(trial['record']);sample=trials.setdefault(trial['service'],{'samples':0,'nonpassing':0});sample['samples']+=1;sample['nonpassing']+=int(not(record.get('positive_passed') and record.get('negative_passed')))
 raw=matrix(store);definitions={('Free',r['id']):r for r in native()};definitions.update({('Extended',r['id']):r for r in imported()})
 native_names={r['name'].casefold().replace('.','').replace(' ',''):r for r in native()};engines=instances();rows=[]
 for item in raw['rows']:
  if item['group']=='provider' and item['id'] in ('Free','Extended'):continue
  row=dict(item);d=definitions.get((row['group'],row['id']),{});provenance=d.get('provenance',{});name=d.get('name',row['id']);key=name.casefold().replace('.','').replace(' ','')
  family=row['id'].split('.',1)[0] if row['group']=='Extended' else 'NickTrail'
  source=family if family in ('Sherlock','Maigret','WhatsMyName') else ('Other' if row['group']=='Extended' else 'NickTrail')
  category=d.get('category') or native_names.get(key,{}).get('category','native_api' if row['group']=='provider' else 'unknown')
  if category=='imported':category=native_names.get(key,{}).get('category','unclassified_import')
  importance=100 if key in BRIDGES or category=='links' else 85 if row['group']=='provider' and row['exact_username'] else 80 if row['group']=='Free' else 70 if key in native_names else 40
  from .engineconfig import HTML_ENGINES
  html_instance=engines.get(row['id'],{}).get('engine') in HTML_ENGINES
  if html_instance:category='configured_public_html'
  expected_rule=d.get('profile_url') or engines.get(row['id'],{}).get('profile_url') or ('exact public API contract' if row['exact_username'] else 'index/manual')
  detector=d.get('detection',{}).get('strategy') or ('configured_strict_public_metadata' if html_instance else 'native_exact_api' if row['exact_username'] else 'index')
  h=row['health'];live=h.get('validation_kind')=='live' or h.get('confidence')=='paired_live_controls'
  status={'FULL':'HEALTHY','EXACT_ONLY':'HEALTHY','MANUAL':'MANUAL_ONLY'}.get(h.get('status'),h.get('status','UNTESTED')) if live else 'UNTESTED'
  if not row['configured']:status='DISABLED'
  elif row['status']=='INDEX_ONLY' and status=='UNTESTED':status='MANUAL_ONLY'
  if status not in STATES:status='UNKNOWN'
  from .healthrevision import fingerprint
  revision_state='UNTRACKED_LEGACY' if not h.get('definition_hash') else 'CURRENT' if h['definition_hash']==fingerprint(row['health_key']) else 'CHANGED'
  row['validation_definition_state']=revision_state
  if live and revision_state=='CHANGED' and status=='HEALTHY':status='PARTIAL'
  checked=h.get('checked_at') if live else None;age=max(0,(now-checked)/86400) if checked else None
  telemetry=json.loads(h.get('telemetry') or '{}') if live else {}
  if telemetry.get('soft_404_coverage')=='negative_rejected':telemetry['soft_404_coverage']='not_exercised_legacy'
  capabilities=['MANUAL_FALLBACK']
  if row['exact_username']:capabilities+=['EXACT_LOOKUP','PROFILE_VERIFICATION']
  if row['context_search']:capabilities.append('USERNAME_SEARCH')
  if row['enrichment']:capabilities.append('ENRICHMENT')
  if row['outbound_links']:capabilities.append('OUTBOUND_LINK_EXTRACTION')
  if row['stable_id']=='supported':capabilities.append('PERSISTENT_ID')
  if row['status']=='INDEX_ONLY':capabilities.append('INDEX_ONLY')
  if 'JS_REQUIRED' in str(h.get('reason','')):capabilities.append('JS_REQUIRED')
  score=importance*3+{'BROKEN':120,'UNTESTED':65,'PARTIAL':80,'UNKNOWN':55,'BLOCKED':25,'RATE_LIMITED':20,'LOGIN_REQUIRED':15,'MANUAL_ONLY':10,'HEALTHY':0,'DISABLED':-150}[status]+min(30,int(age or 0))
  trial=trials.get(row['health_key'],{'samples':0,'nonpassing':0});frequency=trial['nonpassing']/trial['samples'] if trial['samples'] else None
  score+=int(40*(frequency or 0))
  row.update(recorded_live_trials=trial['samples'],nonpassing_trial_frequency=frequency,validated_capabilities=['EXACT_LOOKUP','PROFILE_VERIFICATION'] if live and h.get('positive_passed') and h.get('negative_passed') else [],capabilities=capabilities,name=name,category=category,definition_source=source,native=row['group']!='Extended',provenance={'upstream':provenance.get('repository'),'revision':provenance.get('revision'),'imported_at':provenance.get('imported_at'),'license':provenance.get('license','MIT'),'modifications':'NickTrail strict verifier, public-only request policy; upstream probes/regex not executed' if provenance else 'NickTrail native adapter/definition'},engine_type=engines.get(row['id'],{}).get('engine','discourse' if row['id'] in HOSTS and row['group']=='provider' else 'native_api' if row['group']=='provider' else 'strict_html'),importance=importance,health_state=status,last_live_test=checked,last_success=h.get('last_success') if live else None,validation_age_days=round(age,2) if age is not None else None,positive_result=h.get('positive_state') if live else None,negative_result=h.get('negative_state') if live else None,detector_result={'positive_passed':h.get('positive_passed'),'negative_passed':h.get('negative_passed')} if live else None,telemetry=telemetry,expected_profile_rule=expected_rule,detector_strategy=detector,failure_reason=h.get('reason') if live else None,maintenance_score=score,manual_fallback=True,capability_is_declared=True,retry_at=h.get('retry_at') if live else None,validation_action='wait_for_cooldown' if live and (h.get('retry_at') or 0)>now else 'manual_only' if status in ('MANUAL_ONLY','LOGIN_REQUIRED','DISABLED','BLOCKED') else 'paired_public_controls')
  template=d.get('profile_url') or native_names.get(key,{}).get('profile_url','')
  from .identity import SERVICES
  known_hosts=sorted((host for host,platform in SERVICES.items() if platform==row['id']),key=lambda h:(h.startswith('www.'),len(h),h))
  host=d.get('domain') or native_names.get(key,{}).get('domain') or urlsplit(template).hostname or engines.get(row['id'],{}).get('host') or (HOSTS.get(row['id']) if row['group']=='provider' else None) or (known_hosts[0] if known_hosts else None)
  row['deduplication_host']=host.casefold().removeprefix('www.') if isinstance(host,str) else None
  if revision_state=='CHANGED':row['validated_capabilities']=[];row['failure_reason']='DETECTOR_CHANGED_SINCE_VALIDATION; last recorded result: '+str(h.get('reason',''))[:500]
  if status=='UNTESTED':row['validation_gap']='NO_VALID_LIVE_CONTROL_PAIR_RECORDED'
  if row['group']=='provider' and not row['exact_username'] and row['validation_action']=='paired_public_controls':
   row['validation_action']='search_controls_required'
   row['validation_gap']='CONTEXT_SEARCH_REQUIRES_SEPARATE_RETRIEVAL_CONTROLS; exact-alias health tests are not applicable'
  from .healthdiagnosis import diagnose
  row['repair_diagnosis']=diagnose(h,telemetry,revision_state)
  from . import __version__
  row['provenance']['native_version']=__version__ if source=='NickTrail' else None
  row['provenance']['import_time_status']='recorded' if provenance.get('imported_at') else 'not_applicable_native' if source=='NickTrail' else 'legacy_not_recorded'
  row['repair_bucket']=0 if importance>=80 and status=='BROKEN' else 1 if importance>=80 and status=='PARTIAL' else 2 if importance>=80 and status=='UNTESTED' else 3 if status=='BROKEN' else 4 if age is not None and age>=30 else 5
  rows.append(row)
 # Tiers are an explicit engineering policy, not measured worldwide popularity.
 ranked=sorted(rows,key=lambda r:(-r['importance'],r['health_key']))
 for i,row in enumerate(ranked):row['tier']='A' if i<150 else 'B' if i<400 else 'C'
 return rows

def report(store,filters=None,limit=100,clock=None):
 if type(limit) is not int or not 1<=limit<=2000:raise ValueError('Limit 1–2000')
 filters=filters or {}
 if set(filters)-{'category','state','source','engine','tier','min_age','importance'}:raise ValueError('Nieznany filtr')
 rows=inventory(store,clock);counts=Counter(r['health_state'] for r in rows);origins=Counter(r['definition_source'] for r in rows)
 for source in ('NickTrail','Sherlock','Maigret','WhatsMyName','Other'):origins.setdefault(source,0)
 selected=rows
 for field,key in (('category','category'),('state','health_state'),('source','definition_source'),('engine','engine_type'),('tier','tier')):
  if filters.get(field):selected=[r for r in selected if r[key]==(str(filters[field]).upper() if field in ('state','tier') else filters[field])]
 if filters.get('min_age') is not None:
  age=float(filters['min_age'])
  if not 0<=age<=36500:raise ValueError('Nieprawidłowy wiek walidacji')
  selected=[r for r in selected if r['validation_age_days'] is None or r['validation_age_days']>=age]
 if filters.get('importance') is not None:selected=[r for r in selected if r['importance']>=int(filters['importance'])]
 selected.sort(key=lambda r:(r['repair_bucket'],-r['maintenance_score'],r['health_key']))
 return {'total_definitions':len(rows),'deduplicated_known_hosts':len({r['deduplication_host'] for r in rows if r['deduplication_host']}),'definitions_without_host':sum(not r['deduplication_host'] for r in rows),'health_counts':{s:counts[s] for s in STATES},'definition_sources':dict(origins),'matched':len(selected),'rows':selected[:limit],'truncated':len(selected)>limit,'health_by_family':{family:{state:sum(r['group']==family and r['health_state']==state for r in rows) for state in STATES} for family in ('provider','Free','Extended')},'filters':filters,'facets':{key:sorted({r[field] for r in rows}) for key,field in (('category','category'),('state','health_state'),('source','definition_source'),('engine','engine_type'),('tier','tier'))},'tier_counts':dict(Counter(r['tier'] for r in rows)),'network_calls':0,'note':'Definicje mogą obejmować ten sam serwis. HEALTHY dotyczy zapisanej pary dokładnych kontroli na żywo; inne możliwości pozostają deklarowane. Testy atrap nie są sprawnością; historia częstości obejmuje do 5000 ostatnich poprawnie zdefiniowanych prób na żywo. Priorytety służą kolejności napraw, nie ocenie tożsamości. Raport nie wysyła zapytań.'}
