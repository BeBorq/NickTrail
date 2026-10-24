"""Private local, run-scoped discovery benchmark. Labels never train the evaluator."""
import copy,json,hashlib,datetime
from .identity import identify,EMAIL
from .search import schema,validate_nickname
CLASSES={'DISCOVERABLE_FROM_CURRENT_SEEDS','BRIDGE_DISCOVERABLE','KNOWN_TRUE_BUT_NOT_DERIVABLE','MANUAL_ONLY','BLOCKED','HISTORICAL_ONLY','UNASSESSED'}
CLASS_ALIASES={'SEED_DISCOVERABLE':'DISCOVERABLE_FROM_CURRENT_SEEDS','KNOWN_TRUE_NOT_DERIVABLE':'KNOWN_TRUE_BUT_NOT_DERIVABLE'}
HARD_NEGATIVES={'SIMILAR_USERNAME','EXACT_USERNAME_DIFFERENT_OWNER','SAME_NAME','SAME_CITY','GENERIC_INTERESTS','AVATAR_STYLE','SIMILAR_BIO','SAME_PROJECT_TOPIC','ONE_CHARACTER_USERNAME','OTHER_USER_CONFIRMED'}

def normalize(payload):
 if not isinstance(payload,dict) or set(payload)-{'schema_version','case_id','seeds','aliases','true_profiles','false_profiles','search_id','ks','identity_reference_url'}:raise ValueError('Nieprawidłowy benchmark')
 seeds=payload.get('seeds',{})
 if not isinstance(seeds,dict) or set(seeds)-{'usernames','aliases','full_name','location','known_public_domain','public_email'}:raise ValueError('Nieprawidłowe dane wejściowe benchmarku')
 aliases=[]
 for values in (payload.get('aliases',[]),seeds.get('usernames',[]),seeds.get('aliases',[])):
  if not isinstance(values,list) or len(values)>20:raise ValueError('Maksymalnie 20 aliasów')
  for alias in values:
   alias=validate_nickname(alias)
   if alias.casefold() not in {a.casefold() for a in aliases}:aliases.append(alias)
 if len(aliases)>20:raise ValueError('Maksymalnie 20 aliasów')
 for field in ('full_name','location','known_public_domain','public_email'):
  if field in seeds and (not isinstance(seeds[field],str) or len(seeds[field])>240):raise ValueError('Nieprawidłowe pole '+field)
 if seeds.get('public_email') and not EMAIL.fullmatch(seeds['public_email']):raise ValueError('Nieprawidłowy dobrowolnie podany email')
 if seeds.get('known_public_domain'):
  from .identity import normalize as url_normalize
  url_normalize('https://'+seeds['known_public_domain'])
 groups=[]
 for key in ('true_profiles','false_profiles'):
  values=payload.get(key,[])
  if not isinstance(values,list) or len(values)>2000 or key=='true_profiles' and not values:raise ValueError('Wymagane 1–2000 znanych profili')
  result={}
  for value in values:
   row={'url':value} if isinstance(value,str) else value
   if not isinstance(row,dict) or set(row)-{'url','platform','expected_username','notes','discovery_class','derivability_reason','hard_negative_category'} or not isinstance(row.get('url'),str):raise ValueError('Nieprawidłowy profil benchmarku')
   if 'hard_negative_category' in row and (key!='false_profiles' or row['hard_negative_category'] not in HARD_NEGATIVES):raise ValueError('Nieprawidłowa kategoria potwierdzonego negatywu')
   target=identify(row['url'])
   if target['kind'] not in ('profile','page') or target['kind']=='page' and target['platform'] in ('X','Facebook','GitHub'):raise ValueError('Benchmark wymaga publicznych profili')
   for field in ('platform','expected_username','notes','derivability_reason'):
    if field in row and (not isinstance(row[field],str) or len(row[field])>2000):raise ValueError('Nieprawidłowy opis profilu')
   classification=row.get('discovery_class','DISCOVERABLE_FROM_CURRENT_SEEDS' if row.get('expected_username','').casefold() in {a.casefold() for a in aliases} and row.get('expected_username') else 'UNASSESSED')
   classification=CLASS_ALIASES.get(classification,classification)
   if classification not in CLASSES:raise ValueError('Nieprawidłowa klasa osiągalności')
   if classification in ('KNOWN_TRUE_BUT_NOT_DERIVABLE','MANUAL_ONLY','HISTORICAL_ONLY') and not row.get('derivability_reason'):raise ValueError('Podaj uzasadnienie klasy osiągalności')
   result[target['url']]=row|{'url':target['url'],'platform':row.get('platform',target['platform']),'discovery_class':classification}
  groups.append(list(result.values()))
 if {r['url'] for r in groups[0]}&{r['url'] for r in groups[1]}:raise ValueError('Ten sam URL ma sprzeczne etykiety')
 reference=payload.get('identity_reference_url')
 if reference is not None:
  if not isinstance(reference,str):raise ValueError('Nieprawidłowa referencja tożsamości')
  reference=identify(reference)['url']
  if reference not in {r['url'] for r in groups[0]}:raise ValueError('Referencja wymaga jawnej pozytywnej etykiety benchmarku')
 ks=payload.get('ks',[1,3,5,10,20])
 if not isinstance(ks,list) or not ks or len(ks)>20 or any(type(k) is not int or not 1<=k<=1000 for k in ks):raise ValueError('Nieprawidłowe K')
 search_id=payload.get('search_id')
 if search_id is not None and (type(search_id) is not int or search_id<1):raise ValueError('Nieprawidłowy przebieg')
 return {'identity_reference_url':reference,'schema_version':3,'case_id':str(payload.get('case_id','local'))[:120],'seeds':seeds|{'aliases':aliases},'true_profiles':groups[0],'false_profiles':groups[1],'search_id':search_id,'ks':sorted(set(ks)|{1,3,5})}

def evaluate(store,project,payload,search_id=None):
 case=normalize(payload);schema(store);aliases=case['seeds']['aliases'];search_id=search_id or case['search_id']
 from .search import results
 runs=results(store,project);item=next((r for r in runs if r['run']['id']==search_id),None) if search_id else (runs[0] if runs else None)
 if search_id and item is None:raise ValueError('Przebieg nie należy do projektu')
 raw=store.snapshot(project);snapshot=copy.deepcopy(raw);tasks=item['tasks'] if item else []
 scoped=search_id is not None
 selected={id for t in tasks for id in json.loads(t['nodes'])}
 if scoped:
  snapshot['nodes']=[n for n in snapshot['nodes'] if n['id'] in selected]
  snapshot['evidence']=[e for e in snapshot['evidence'] if e['source'] in selected and e['target'] in selected]
 # Ownership labels, accepted manual edges and user focus are held out, not features.
 snapshot['focus']=[]
 for n in snapshot['nodes']:n['ownership']='unknown'
 snapshot['evidence']=[e for e in snapshot['evidence'] if e.get('method','parser') in ('parser','rendered_public_page')]
 for e in snapshot['evidence']:e['decision']='unknown'
 from .ranking import evaluate as rank
 from .pools import classify
 criteria={};words=case['seeds'].get('full_name','').split()
 if len(words)>1:criteria|={'first_name':words[0],'last_name':' '.join(words[1:])}
 if case['seeds'].get('location'):criteria['location']=case['seeds']['location']
 ranking=rank(snapshot,criteria,aliases);pools=classify(snapshot,ranking,aliases,criteria)
 nodes={n['id']:n for n in snapshot['nodes']};true={r['url'] for r in case['true_profiles']};false={r['url'] for r in case['false_profiles']}
 from .identity import reference_matches
 references=true|false;resolved={}
 for n in nodes.values():
  matches={url for url in references if reference_matches(n,url)}
  if matches&true and matches&false:raise ValueError('Conflicting reference labels for one API-validated account')
  if matches:resolved[n['url']]=sorted(matches)[0]
 observed={resolved.get(n['url'],n['url']) for n in nodes.values() if n['state']=='found' and n['kind'] in ('profile','page') and not json.loads(n['data']).get('indexed_only') and not json.loads(n['data']).get('definition_only')}
 ordered=sorted(ranking['order'],key=lambda id:0 if pools[str(id)]['pool']=='STRONG_RESULTS' else 1)
 order=list(dict.fromkeys(resolved.get(nodes[id]['url'],nodes[id]['url']) for id in ordered if nodes[id]['kind'] in ('profile','page') and pools[str(id)]['primary_visible']))
 found=true&observed;first=next((i+1 for i,u in enumerate(order) if u in true),None)
 retrieved={resolved.get(n['url'],n['url']) for n in nodes.values()};retrieved_false=false&retrieved
 eligible={r['url'] for r in case['true_profiles'] if r.get('expected_username','').casefold() in {a.casefold() for a in aliases} and r.get('expected_username') and r['discovery_class'] not in ('KNOWN_TRUE_BUT_NOT_DERIVABLE','MANUAL_ONLY','HISTORICAL_ONLY','BRIDGE_DISCOVERABLE')}
 exact_tasks=[t for t in tasks if __import__('nicktrail.stages',fromlist=['phase']).phase(t['platform'],t['mode'])=='A_EXACT']
 attempted=[t for t in exact_tasks if t['state'] not in ('pending','searching','unsupported')]
 manual_true={url for url in true for n in raw['nodes'] if n['ownership']=='mine' and reference_matches(n,url)}
 blocked_true=set()
 for r in case['true_profiles']:
  if r['url'] in found:continue
  platform=identify(r['url'])['platform'];expected=r.get('expected_username','')
  for t in tasks:
   if t['state']!='blocked':continue
   relevant=t['platform']==platform and expected and t['term'].casefold()==expected.casefold()
   if t['platform'] in ('Free','Extended') and ':' in t['term']:
    service,alias=t['term'].split(':',1)
    from .freeprofiles import TEMPLATES
    templates=TEMPLATES if t['platform']=='Free' else {s['id']:s['profile_url'] for s in __import__('nicktrail.extended',fromlist=['services']).services()}
    try:relevant=service in templates and identify(templates[service].format(nick=alias))['url']==r['url']
    except ValueError:relevant=False
   if relevant:blocked_true.add(r['url'])
 metrics={'exact_username_recall':len(found&eligible)/len(eligible) if eligible else None,'automatic_coverage':len(found)/len(true),'manual_coverage':len(manual_true)/len(true),'blocked_coverage':len(blocked_true)/len(true),'recall_primary':len(true&set(order))/len(true),'mrr':1/first if first else 0,'false_negative_rate':1-len(found)/len(true),'false_positive_rate':len(false&set(order))/len(retrieved_false) if retrieved_false else None,'known_false_positive_rate':len(false&set(order))/len(false) if false else None,'exact_sources_attempted':len({(t['platform'],t['term'].split(':',1)[0] if t['platform'] in ('Free','Extended') else t['platform']) for t in attempted})}
 for k in case['ks']:
  top=set(order[:k]);tp=len(top&true);unknown=len(top-true-false)
  metrics['precision_at_'+str(k)]=tp/k;metrics['recall_at_'+str(k)]=tp/len(true)
  metrics['judged_precision_at_'+str(k)]=tp/len(top&(true|false)) if top&(true|false) else None
  metrics['unjudged_at_'+str(k)]=unknown
  metrics['precision_at_'+str(k)+'_lower_bound']=tp/k
  metrics['judged_label_coverage_at_'+str(k)]=len(top&(true|false))/len(top) if top else None
 discoverable={r['url'] for r in case['true_profiles'] if r['discovery_class']=='DISCOVERABLE_FROM_CURRENT_SEEDS'}
 class_counts={c:sum(r['discovery_class']==c for r in case['true_profiles']) for c in sorted(CLASSES)}
 bridge={r['url'] for r in case['true_profiles'] if r['discovery_class']=='BRIDGE_DISCOVERABLE'}
 strong_urls={resolved.get(nodes[int(id)]['url'],nodes[int(id)]['url']) for id,p in pools.items() if p['identity_evidence']=='STRONG'}
 from .identitybenchmark import evaluate as identity_evaluate
 identity_report=identity_evaluate(snapshot,case.get('identity_reference_url'),true,false,resolved)
 metrics.update(bridge_discoverable_recall=len(found&bridge)/len(bridge) if bridge else None,bridge_discoverable_profiles=len(bridge),search_false_positive_rate=len(false&set(order))/len(retrieved_false) if retrieved_false else None,identity_false_positive_rate=identity_report['false_positive_rate'],strong_graph_negative_rate=len(false&strong_urls)/len(retrieved_false) if retrieved_false else None,strong_graph_negative_count=len(false&strong_urls))
 hard_negative_metrics={}
 for category in sorted(HARD_NEGATIVES):
  cohort={r['url'] for r in case['false_profiles'] if r.get('hard_negative_category')==category};encountered=cohort&retrieved
  if cohort:hard_negative_metrics[category]={'labelled':len(cohort),'retrieved':len(encountered),'search_visible':len(cohort&set(order)),'strong_graph_count':len(cohort&strong_urls),'strong_graph_negative_rate':len(cohort&strong_urls)/len(encountered) if encountered else None}
  if cohort:
   identity_rows=[r for r in identity_report.get('classifications',[]) if r['url'] in cohort]
   hard_negative_metrics[category]['identity_false_positive_rate']=sum(r['classification'] in ('SAME_PERSON_STRONG','LIKELY_SAME') for r in identity_rows)/len(identity_rows) if identity_rows else None
   hard_negative_metrics[category]['identity_abstention_rate']=sum(r['classification'] in ('AMBIGUOUS','INSUFFICIENT_EVIDENCE') for r in identity_rows)/len(identity_rows) if identity_rows else None
 metrics.update(seed_discoverable_recall=len(found&discoverable)/len(discoverable) if discoverable else None,seed_discoverable_false_negative_rate=1-len(found&discoverable)/len(discoverable) if discoverable else None,total_known_profile_coverage=len(found)/len(true),non_derivable_known_profiles=class_counts['KNOWN_TRUE_BUT_NOT_DERIVABLE'],seed_discoverable_profiles=len(discoverable),visible_candidate_count=len(order),weak_candidate_count=sum(p['identity_evidence']!='STRONG' for p in pools.values()),strong_graph_candidate_count=sum(p['identity_evidence']=='STRONG' for p in pools.values()))
 requests=item['run']['requests'] if item else None
 elapsed=None
 if item and item['run'].get('started') and item['run'].get('finished'):
  try:elapsed=max(0,(datetime.datetime.fromisoformat(item['run']['finished'])-datetime.datetime.fromisoformat(item['run']['started'])).total_seconds())
  except (ValueError,TypeError):pass
 metrics.update(scan_seconds=elapsed,requests=requests,requests_per_known_useful_profile=requests/len(found) if requests is not None and found else None)
 metrics['strong_candidate_count']=sum(p['pool']=='STRONG_RESULTS' for p in pools.values())
 metrics.update(known_negative_reference_visibility_rate=len(false&set(order))/len(false) if false else None,known_negative_references_retrieved=len(retrieved_false),known_negative_retrieval_coverage=len(retrieved_false)/len(false) if false else None,known_negative_references_visible=len(false&set(order)),false_positive_rate_among_retrieved_known_negatives=len(false&set(order))/len(retrieved_false) if retrieved_false else None)
 metrics['seed_inputs_match_scan']=set(a.casefold() for a in aliases)==set(str(a).casefold() for a in json.loads(item['run']['options']).get('_terms',[])) if item else None
 pollution={'visible':len(order),'visible_unjudged':len(set(order)-true-false),'quarantined':sum(not p['primary_visible'] for p in pools.values()),'exact_suppressed':sum(p['exact_supplied_alias'] and not p['primary_visible'] for p in pools.values()),'name_only':0,'fuzzy_only':0,'exact_matches':sum(p['exact_supplied_alias'] for p in pools.values()),'per_source':{}}
 origins={};full_name=' '.join(filter(None,(criteria.get('first_name'),criteria.get('last_name')))).casefold()
 for task in tasks:
  kind=task['mode'].split('|')[0]
  if kind=='context' and full_name and task['term'].casefold() in {full_name,(full_name+' '+criteria.get('location','')).strip()}:kind='name_context'
  for id in json.loads(task['nodes']):origins.setdefault(id,set()).add(kind)
 for id in ordered:
  n=nodes[id];p=pools[str(id)];r=ranking['nodes'][str(id)];features=set(r['weights']);kinds=origins.get(id,set())-{'enrich'}
  weak=not p['exact_supplied_alias'] and p['identity_evidence']!='STRONG'
  name_only=weak and kinds=={'name_context'}
  fuzzy_only=weak and kinds=={'related'}
  pollution['name_only']+=int(name_only);pollution['fuzzy_only']+=int(fuzzy_only)
  source=pollution['per_source'].setdefault(n['platform'],{'total':0,'visible':0,'quarantined':0,'exact':0,'graph_strong':0,'name_only':0,'fuzzy_only':0})
  for key,value in {'total':1,'visible':int(p['primary_visible']),'quarantined':int(not p['primary_visible']),'exact':int(p['exact_supplied_alias']),'graph_strong':int(p['identity_evidence']=='STRONG'),'name_only':int(name_only),'fuzzy_only':int(fuzzy_only)}.items():source[key]+=value
 pollution['source_domination']=[{'source':key,'visible_share':r['visible']/len(order),'visible':r['visible']} for key,r in pollution['per_source'].items() if order and r['visible']/len(order)>.5]
 from .diagnostics import explain,reason
 missing=[];hidden=[]
 for url in sorted(true-set(order)):
  explanation=explain(store,project,url,pools,search_id=item['run']['id'] if scoped and item else None)
  if url in found:
   explanation|={'code':'PROFILE_FOUND_BUT_HIDDEN','reason':'Detected but not primary-visible in neutral benchmark ranking'};hidden.append(explanation)
  else:missing.append(explanation)
 concentration={}
 for id in ordered:
  if pools[str(id)]['primary_visible']:concentration[nodes[id]['platform']]=concentration.get(nodes[id]['platform'],0)+1
 return {'schema_version':3,'metric_protocol':'retrieval-and-explicit-reference-identity-v3','case_id':case['case_id'],'search_id':item['run']['id'] if item else None,'scope':'selected_search' if scoped else 'project_snapshot','metrics':metrics,'known_true':len(true),'known_false':len(false),'hard_negative_metrics':hard_negative_metrics,'identity_evaluation':identity_report,'discovery_classes':class_counts,'seed_reference_classifications':[{'url':r['url'],'discovery_class':r['discovery_class'],'reason':r.get('derivability_reason','')} for r in case['true_profiles']],'found_known_true':len(found),'missing':missing,'detected_but_hidden':hidden,'exact_audit':{'scheduled':len(exact_tasks),'attempted':len(attempted),'pending':sum(t['state'] in ('pending','searching') for t in exact_tasks),'unsupported':sum(t['state']=='unsupported' for t in exact_tasks),'sources_attempted':metrics['exact_sources_attempted'],'known_http_task_attempts':sum((t.get('requests') or 0)>0 for t in exact_tasks),'legacy_tasks_without_request_attribution':sum(t.get('requests') is None and t['state'] not in ('pending','searching') for t in exact_tasks),'failures':[{'platform':t['platform'],'term':t['term'],'state':t['state'],'reason':reason(t['state'],t.get('detail','')),'detail':t.get('detail','')} for t in attempted if t['state']!='found']},'pollution':pollution|{'per_source_visible':concentration},'ordered_urls':order,'completeness':__import__('nicktrail.diagnostics',fromlist=['completeness']).completeness(item,store,snapshot,pools) if item else None,'assumptions':['Known labels are held out: ownership, focus and manual decisions do not train or rank the benchmark.','Precision@K is a pessimistic fixed-K lower bound; unknown profiles are unjudged, not proven false. Judged precision and unknown counts are separate.','FPR uses explicitly labelled negatives actually present in the evaluated candidate cohort; null if none encountered. All-reference negative visibility remains a separate metric. Seed recall uses explicitly seed-discoverable references; total coverage/FNR retain all known references. Visible precision includes unread visible leads, not only verified discoveries.','Run scope excludes prior unrelated discoveries; node metadata is the currently saved observation, not an immutable historical replay.','Public email is optional private benchmark metadata and never sent as a search query.','Private local evaluation; no automatic publication or network calls.']}


def snapshot_schema(store):
 from .storage import SCHEMA_LOCK
 with SCHEMA_LOCK:
  store.execute('CREATE TABLE IF NOT EXISTS golden_snapshots(id INTEGER PRIMARY KEY,project INTEGER REFERENCES projects ON DELETE CASCADE,case_id TEXT,created TEXT,search_id INTEGER,case_hash TEXT,scope_hash TEXT,report TEXT)')

def save_snapshot(store,project,payload,search_id=None):
 from .storage import now
 case=normalize(payload);result=evaluate(store,project,case,search_id)
 snapshot_schema(store)
 # Hash reference/seed definitions; truth remains in the user's local input file.
 case_hash=hashlib.sha256(json.dumps({k:v for k,v in case.items() if k not in ('search_id','ks')},sort_keys=True).encode()).hexdigest()
 from .search import results
 run=next((r for r in results(store,project) if r['run']['id']==result['search_id']),None)
 scope=json.loads(run['run']['options']) if run else {}
 scope_hash=hashlib.sha256(json.dumps(scope,sort_keys=True).encode()).hexdigest()
 id=store.execute('INSERT INTO golden_snapshots(project,case_id,created,search_id,case_hash,scope_hash,report) VALUES(?,?,?,?,?,?,?)',(project,case['case_id'],now(),result['search_id'],case_hash,scope_hash,json.dumps(result,ensure_ascii=False))).lastrowid
 return result|{'snapshot_id':id}

def snapshot_history(store,project,limit=20):
 if type(limit) is not int or not 1<=limit<=100:raise ValueError('Limit 1–100')
 snapshot_schema(store)
 rows=store.rows('SELECT * FROM golden_snapshots WHERE project=? ORDER BY id DESC LIMIT ?',(project,limit));out=[]
 for row in rows:
  result=json.loads(row.pop('report'));row['metrics']=result['metrics'];row['pollution']=result['pollution'];out.append(row)
 return out

def compare_snapshots(store,project,first,second):
 snapshot_schema(store)
 rows=store.rows('SELECT * FROM golden_snapshots WHERE project=? AND id IN (?,?)',(project,first,second));by_id={r['id']:r for r in rows}
 if first==second or first not in by_id or second not in by_id:raise ValueError('Wybierz dwa różne pomiary z tego projektu')
 a,b=by_id[first],by_id[second];ar,br=json.loads(a['report']),json.loads(b['report'])
 keys=set(ar['metrics'])&set(br['metrics']);deltas={k:br['metrics'][k]-ar['metrics'][k] for k in sorted(keys) if type(ar['metrics'][k]) in (int,float) and type(br['metrics'][k]) in (int,float)}
 return {'first':first,'second':second,'same_reference_definition':a['case_hash']==b['case_hash'],'same_scan_scope':a['scope_hash']==b['scope_hash'],'same_metric_protocol':ar.get('metric_protocol')==br.get('metric_protocol'),'deltas':deltas,'before':ar['metrics'],'after':br['metrics'],'warning':'Deltas are descriptive. Changed labels, seeds, scope, observations or upstream availability prevent causal accuracy claims.'}
