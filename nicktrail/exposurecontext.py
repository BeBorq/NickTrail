"""Exposure may prioritize a public check; it never supplies an identity path."""
import json
from .exposure import service_hints

def context(store,project):
 if not store.rows("SELECT name FROM sqlite_master WHERE name='exposure_checks'"):return []
 rows=[];seen=set()
 for check in store.rows("SELECT id,checked,incidents FROM exposure_checks WHERE project=? AND state='exposed' ORDER BY id DESC LIMIT 20",(project,)):
  for hint in service_hints(json.loads(check['incidents'])):
   key=('HIBP',hint['domain'])
   if key in seen:continue
   seen.add(key)
   rows.append({'id':'X'+str(check['id'])+':'+str(len(rows)+1),'kind':'EXPOSURE_METADATA','root_source':'HIBP','relation':'EXPOSURE_SUGGESTS_PLATFORM','domain':hint['domain'],'services':hint['services'],'checked':check['checked'],'identity_evidence':False,'historical_aliases':[]})
 return rows[:20]
