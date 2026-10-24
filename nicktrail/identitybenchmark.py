"""Explicit-reference deterministic identity evaluation, separate from retrieval ranking."""
import json
from .identity import reference_matches
from .graphsignals import analyze
from .clusteroverview import cluster_overview

def evaluate(snapshot,reference,true,false,resolved):
 if not reference:return {'available':False,'reason':'NO_EXPLICIT_IDENTITY_REFERENCE','false_positive_rate':None,'classifications':[]}
 roots=[n for n in snapshot['nodes'] if reference_matches(n,reference) and n['state']=='found' and not any(json.loads(n['data']).get(k) for k in ('indexed_only','definition_only'))]
 if len(roots)!=1:return {'available':False,'reason':'REFERENCE_NOT_UNIQUELY_VALIDATED','false_positive_rate':None,'classifications':[]}
 neutral=dict(snapshot,focus=[{'node':roots[0]['id']}]);paths=analyze(neutral);edges=[];profiles=[]
 independent={e['id']:e.get('independence_group','unknown') for items in paths.values() for path in items for e in path['edges']}
 for e in snapshot['evidence']:
  edges.append({**e,'id':'E'+str(e['id']),'source':'P'+str(e['source']),'target':'P'+str(e['target']),'independence_group':independent.get(e['id'],'unknown')})
 provided={e['id'] for e in edges}
 for n in snapshot['nodes']:
  if n['kind'] not in ('profile','page'):continue
  current=n['state']=='found' and not any(json.loads(n['data']).get(k) for k in ('indexed_only','definition_only'))
  profiles.append({'id':'P'+str(n['id']),'read_state':n['state'],'entity_type':json.loads(n['data']).get('entity_type'),'user_label':'unknown','identity_paths':[{'kind':p['kind'],'evidence':['E'+str(e['id']) for e in p['edges']]} for p in paths.get(n['id'],[]) if current and p['strength']>=12 and all('E'+str(e['id']) in provided for e in p['edges'])]})
 packet={'profiles':profiles,'evidence':edges,'reference':'P'+str(roots[0]['id'])};rows=cluster_overview(packet);by_id={n['id']:n for n in snapshot['nodes']};out=[]
 for row in rows:
  node=by_id[int(row['candidate'][1:])];url=resolved.get(node['url'],node['url'])
  out.append({'url':url,'classification':row['classification'],'supporting':row['supporting'],'known_label':'negative' if url in false else 'positive' if url in true else 'unjudged'})
 negatives=[r for r in out if r['known_label']=='negative'];positive_states={'SAME_PERSON_STRONG','LIKELY_SAME'}
 return {'available':True,'basis':'deterministic cluster analysis, explicit reference; not a trained identity accuracy','false_positive_rate':sum(r['classification'] in positive_states for r in negatives)/len(negatives) if negatives else None,'evaluated_known_negatives':len(negatives),'negative_abstention_rate':sum(r['classification'] in ('INSUFFICIENT_EVIDENCE','AMBIGUOUS') for r in negatives)/len(negatives) if negatives else None,'classifications':out,'network_calls':0,'user_labels_used_as_features':False,'reference_is_explicit_input':True}
