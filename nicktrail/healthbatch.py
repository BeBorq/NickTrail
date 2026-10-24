"""Explicit control-pair maintenance, sequential and bounded; never enumerate users."""
import time
from .serviceaudit import report
from .health import validate

def run(store,controls,filters=None,maximum=5,pause=None):
 if type(maximum) is not int or not 1<=maximum<=25:raise ValueError('Partia wymaga limitu 1–25')
 if not isinstance(controls,list) or len(controls)>2000:raise ValueError('Nieprawidłowy plik kontroli')
 pairs={}
 for row in controls:
  if not isinstance(row,dict) or set(row)!={'service','positive','negative'} or any(not isinstance(v,str) or len(v)>200 for v in row.values()):raise ValueError('Każda kontrola wymaga service, positive, negative')
  if row['service'] in pairs:raise ValueError('Powtórzony serwis kontroli')
  pairs[row['service']]=row
 before=report(store,filters,2000);chosen=[];skipped=[]
 known={r['health_key'] for r in report(store,limit=2000)['rows']}
 for service in pairs:
  if service not in known:skipped.append({'service':service,'reason':'CONTROL_SERVICE_NOT_IN_CATALOG; no request sent'})
 for row in before['rows']:
  if row['health_key'] not in pairs:continue
  if row['validation_action']!='paired_public_controls':skipped.append({'service':row['health_key'],'reason':row['validation_action']});continue
  chosen.append(pairs[row['health_key']])
  if len(chosen)>=maximum:break
 outcomes=[];started=time.monotonic()
 for row in chosen:
  if outcomes:(pause or time.sleep)(2)
  try:
   r=validate(store,row['service'],row['positive'],row['negative'])
   outcomes.append({k:r.get(k) for k in ('service','status','positive_state','negative_state','requests','cached','reason')})
  except ValueError:
   outcomes.append({'service':row['service'],'status':'UNKNOWN','reason':'CONTROL_CONFIGURATION_INVALID; no detector-health inference'})
 return {'before':before['health_counts'],'after':report(store,limit=1)['health_counts'],'selected':len(chosen),'maximum':maximum,'outcomes':outcomes,'skipped':skipped,'elapsed_seconds':round(time.monotonic()-started,3),'concurrency':1,'repair_backlog':report(store,filters,25),'private_controls_not_exported':True}
