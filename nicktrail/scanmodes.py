"""Shared bounded discovery mode policies; scope is never an AI decision."""
from .providers import REGISTRY
from .engineconfig import instances
NAMES=('QUICK','STANDARD','DEEP','HISTORICAL','CUSTOM','EXACT_ONLY','EXTENDED')

def presets():
 standard=[id for id,p in REGISTRY.items() if not p.required_env and id not in instances() and id not in ('Extended','Catalog','Web','Sensitive','Archive')]
 quick=[id for id in ('GitHub','Roblox','Bluesky','GitLab','DEV','Codeberg','Gitea','HackerNews','HuggingFace','CratesIO','RubyGems') if id in REGISTRY and REGISTRY[id].available()]
 exact=[id for id in standard if id not in __import__('nicktrail.community',fromlist=['STACK']).STACK]
 indexes=[id for id,p in REGISTRY.items() if p.scope in ('web_index','domain_index') and p.available()]
 configured=[id for id in instances() if REGISTRY[id].available()]
 def plan(platforms,related,branches,variants,queries,seconds,rounds,description):
  return {'platforms':platforms,'related':related,'branches':branches,'variants':variants,'options':{'queries':queries,'seconds':seconds,'per_domain':15,'candidates':50},'branch_options':{'queries':80 if branches else 0,'seconds':120,'per_domain':15},'continuations':rounds,'auto_resume':rounds>0,'discovery_request_upper_bound':queries*(rounds+1)*(2 if branches else 1),'branch_request_upper_bound_per_batch':80*(rounds+1) if branches else 0,'description':description,'ai':'manual_only'}
 result={
 'QUICK':plan(quick,False,False,False,40,60,0,'Tanie dokładne API, bez szerokiego katalogu, drzewa i automatycznego wznawiania.'),
 'STANDARD':plan(standard,True,True,False,100,150,2,'Dokładne API i 100 ścisłych szablonów, potem linki i podobne nazwy. Wznawia się sama, dopóki kolejka maleje.'),
 'DEEP':plan(list(dict.fromkeys(standard+['Extended','Archive']+indexes+configured)),True,True,True,250,300,5,'Duży katalog, skonfigurowane indeksy/instancje, warianty i linki. Wznawia się sama, dopóki kolejka maleje; serwisy, które stale odmawiają, są pomijane do sprawdzenia ręcznego.'),
 'EXACT_ONLY':plan(exact,False,False,False,100,150,2,'Dokładne aliasy i wzbogacanie; bez wyszukiwania podobnych nazw.'),
 'HISTORICAL':plan([],False,False,False,4,35,0,'Osobny panel: jeden zapisany adres i data, podgląd oraz jawna zgoda na publiczne archiwum.'),
 'CUSTOM':plan([],False,False,False,40,120,50,'Własne źródła, limity i wznawianie.')}
 result['EXTENDED']=dict(result['DEEP'])|{'description':'Alias zgodności dla trybu DEEP.'}
 return result

def policy(name):
 if name not in NAMES:raise ValueError('Nieznany tryb skanowania')
 return presets()[name]

def apply(payload):
 """Named modes enforce their scope; custom retains explicit caller settings."""
 if not isinstance(payload,dict):raise ValueError('Invalid discovery request')
 name=payload.get('scan_mode','CUSTOM');p=policy(name)
 if name=='HISTORICAL':raise ValueError('Tryb historyczny wymaga wybrania źródła i daty w panelu archiwum')
 if name=='CUSTOM':return dict(payload)
 return payload|{'platforms':p['platforms'],'related':p['related'],'variants':p['variants'],'auto_branches':p['branches'],'verify_top':0,'auto_resume':p['auto_resume'],'options':p['options'],'branch_options':p['branch_options']}
