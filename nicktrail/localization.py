"""Local presentation catalogs: source records and evidence are never translated."""
import html,json,re
from functools import lru_cache
from pathlib import Path
LANGUAGES=('en','pl')
LOCALES={'en':'en-GB','pl':'pl-PL'}
@lru_cache(maxsize=1)
def catalog():return json.loads(Path(__file__).with_name('translations.json').read_text(encoding='utf-8'))
def render_panel(source,language='en'):
 language=language if language in LANGUAGES else 'en'
 data=catalog();translations=data['languages'].get(language,{})
 def text(value):
  stripped=value.strip()
  if not stripped:return value
  translated=translations.get(stripped,stripped)
  return value[:len(value)-len(value.lstrip())]+translated+value[len(value.rstrip()):]
 literals={raw:json.dumps(text(value),ensure_ascii=True).replace('<',r'\u003c') for raw,value in data['literals'].items() if value.strip() in translations}
 literals["'pl-PL'"]=json.dumps(LOCALES[language]);literals['"pl-PL"']=json.dumps(LOCALES[language])
 pattern=re.compile('|'.join(re.escape(raw) for raw in sorted(literals,key=len,reverse=True)))
 parts=re.split(r'(<script\b[^>]*>[\s\S]*?</script>|<style\b[^>]*>[\s\S]*?</style>|<[^>]+>)',source,flags=re.I)
 protected=0;out=[]
 for part in parts:
  if part.lower().startswith('<script'):
   opening,body=part.split('>',1);body,closing=body.rsplit('</',1)
   out.append(opening+'>'+pattern.sub(lambda m:literals[m.group()],body)+'</'+closing);continue
  if part.lower().startswith('<style'):out.append(part);continue
  if part.startswith('<'):
   if re.match(r'<(?:code|pre)\b',part,re.I):protected+=1
   elif re.match(r'</(?:code|pre)\b',part,re.I):protected=max(0,protected-1)
   part=re.sub(r'(\b(?:placeholder|title|aria-label)\s*=\s*)(["\'])(.*?)\2',lambda m:m[1]+m[2]+html.escape(text(html.unescape(m[3])),quote=True)+m[2],part,flags=re.S)
   out.append(part);continue
  out.append(part if protected else html.escape(text(html.unescape(part)),quote=False))
 result=''.join(out)
 return re.sub(r'(<html\b[^>]*\blang=)["\'][^"\']*["\']',lambda m:m[1]+'"'+language+'"',result,count=1,flags=re.I)

# Only UI-owned response paths are localized. Profile records, source content,
# evidence, identifiers, settings values and exports are deliberately excluded.
DISPLAY_PATHS={
 '/api/state': (
  'read_status.*.label','read_status.*.kind_label','read_status.*.meaning','read_status.*.detail',
  'pools.*.reason','labels.*.text','ranking.nodes.*.reasons','ranking.nodes.*.conflicts','ranking.nodes.*.sort_reason',
  'identity_clusters.note','identity_clusters.clusters.*.bridges.*.facts.*.why',
  'identity_clusters.review_pairs.*.facts.*.why',
  'dead_ends.note','dead_ends.dead_ends.*.detail','dead_ends.dead_ends.*.suggestion',
  'discovery_coverage.*.limitations','manual_queue.*.reason','manual_queue.*.meaning',
  'manual_queue.*.suggestion','review_plan.note','review_plan.actions.*.reason',
  'review_plan.actions.*.why','review_plan.actions.*.explanation',
  'aliasSuggestions.*.reason','suggestions.*.reason','job.error'),
 '/api/keys':('services.*.used_for','services.*.cost','services.*.steps',
  'services.*.fields.*.label','services.*.links.*.label','note'),
 '/api/settings':('labels.*','choices.*.*.1','note'),
 '/api/capabilities':('rows.*.limitations','note'),
 '/api/health-report':('note','rows.*.repair_diagnosis.summary'),
}
# Whole sub-trees of UI-owned text: progress details, notes, diagnostics, job results.
# Records the user's data lives in (snapshot nodes/evidence, search terms, imported
# hints) are deliberately not listed, and KEEP protects identifiers inside the trees.
DEEP_PATHS={
 '/api/state':('job.**','scan_coverage.**','dead_ends.**','review_plan.**','pools.**','labels.**','read_status.**',
  'identity_clusters.**','discovery_coverage.**','local_ai.**','eta.**','throttling.**','manual_queue.**',
  'suggestions.**','aliasSuggestions.**','discovery_leads.**','historical.**','exposure.**','focusResults.**',
  'searches.*.sources.*.detail','searches.*.tasks.*.detail','snapshot.scans.*.notes','branches.*.nodes.*.detail',
  'ranking.**','progress.**'),
 '/api/profile-history':('**',),'/api/health-report':('**',),'/api/capabilities':('**',),
}
KEEP={'url','urls','platform','kind','ownership','state','status','alias','display','term','nickname','source_url',
      'value','id','node','root','source','target','url_hint','domain','email','search_term','evidence','fingerprint',
      'source_platform','source_key','mode','basis','code','capability_state','search','platforms','provider','service'}
@lru_cache(maxsize=1)
def system_catalog():
 return json.loads(Path(__file__).with_name('system_translations.json').read_text(encoding='utf-8'))
@lru_cache(maxsize=65536)
def translate_message(value,language='en'):
 if language=='pl' or not value:return value
 language=language if language in LANGUAGES else 'en'
 core=catalog()['languages'];messages=system_catalog()
 for table in (core.get(language,{}),messages.get(language,{}),messages.get('en',{})):
  if value in table:return table[value]
 for row,pattern,order in _templates():
  match=pattern.fullmatch(value)
  if match:
   values={index:captured for index,captured in zip(order,match.groups())}
   translated=row.get(language,row['en'])
   return re.sub(r'\{([0-9]+)\}',lambda m:values[int(m[1])],translated)
 # Messages built from several pieces ("Serwis odmówił " + n + " razy…"): translate each
 # known piece.  Pieces are whole phrases from the code, matched on word boundaries.
 pattern,table=_fragments()
 return pattern.sub(lambda m:table[m.group(0)],value) if pattern else value

@lru_cache(maxsize=1)
def _templates():
 out=[]
 for row in system_catalog().get('templates',[]):
  parts=re.split(r'(\{[0-9]+\})',row['source']);pattern='';order=[]
  for part in parts:
   if re.fullmatch(r'\{[0-9]+\}',part):
    order.append(int(part[1:-1]));pattern+='(.*?)'
   else:pattern+=re.escape(part)
  out.append((row,re.compile(pattern,re.S),order))
 return out

@lru_cache(maxsize=1)
def _fragments():
 messages=system_catalog()
 table={k:v for k,v in messages.get('en',{}).items() if len(k.strip())>=6 and k.strip()==k}
 table.update(messages.get('fragments',{}))
 # Values that are identifiers in the data (platform names) must never be rewritten.
 table={k:v for k,v in table.items() if k and k!=v and k not in ('Strona','Deklaracja','Moje konta','Discord')}
 if not table:return None,{}
 def bounded(text):
  return (r'(?<!\w)' if text[0].isalnum() else '')+re.escape(text)+(r'(?!\w)' if text[-1].isalnum() else '')
 return re.compile('|'.join(bounded(k) for k in sorted(table,key=len,reverse=True))),table

def localize_response(path,data,language):
 """Copy on write: localization never changes the worker's source objects."""
 if language not in LANGUAGES or language=='pl' or path.startswith('/api/export'):return data
 def leaf(value):
  if isinstance(value,str):return translate_message(value,language)
  if isinstance(value,list):return [leaf(v) if isinstance(v,str) else v for v in value]
  return value
 def deep(value):
  # Every string below this point is UI text (or an identifier no phrase matches).
  if isinstance(value,str):return translate_message(value,language)
  if isinstance(value,list):return [deep(v) for v in value]
  if isinstance(value,dict):return {k:(v if k in KEEP else deep(v)) for k,v in value.items()}
  return value
 def apply(value,parts):
  if not parts:return leaf(value)
  token,*rest=parts
  if token=='**':return deep(value)
  if isinstance(value,dict):
   keys=list(value) if token=='*' else [token] if token in value else []
   if not keys:return value
   result=dict(value)
   for key in keys:result[key]=apply(value[key],rest)
   return result
  if isinstance(value,list):
   indices=range(len(value)) if token=='*' else [int(token)] if token.isdigit() and int(token)<len(value) else []
   result=list(value)
   for index in indices:result[index]=apply(value[index],rest)
   return result
  return value
 paths=('error','result.**')+DISPLAY_PATHS.get(path,())+DEEP_PATHS.get(path,())
 for pointer in paths:data=apply(data,pointer.split('.'))
 return data
