"""No-key public username checks. Ambiguous HTML is not proof of a profile."""
import json,re
from html.parser import HTMLParser
from urllib.parse import quote,urlsplit
from .identity import normalize
from .servicecatalog import services,definition
TEMPLATES={s['id']:s['profile_url'] for s in services()}

class Meta(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.values={};self.canonical='';self.title=[];self.in_title=False
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='meta':self.values[a.get('property') or a.get('name') or '']=a.get('content','')
  if tag=='link' and 'canonical' in a.get('rel','').lower().split():self.canonical=a.get('href','')
  if tag=='title':self.in_title=True
 def handle_endtag(self,tag):
  if tag=='title':self.in_title=False
 def handle_data(self,text):
  if self.in_title:self.title.append(text)
def lookup(term,client):
 from .search import validate_nickname
 from .publicprofile import ProfileHTML
 from .adapters import extract
 site,alias=term.split(':',1);alias=validate_nickname(alias)
 if site not in TEMPLATES:raise ValueError('Nieznany darmowy adapter')
 service=definition(site)
 from .providers import REGISTRY
 if site in ('Codewars','Modrinth','Codeforces','Launchpad'):
  try:return REGISTRY[site].lookup(alias,client)
  except (ValueError,KeyError,TypeError):return {'state':'partial','matches':[],'detail':site+': publiczny adapter nie potwierdził schematu profilu'}
 if not re.fullmatch(service['username_pattern'],alias):return {'state':'unsupported','detail':'Nick nie spełnia reguł serwisu','matches':[]}
 return probe(service,alias,client)

def probe(service,alias,client):
 from .publicprofile import ProfileHTML
 from .adapters import extract
 site=service['id']
 url=service['profile_url'].format(nick=quote(alias,safe=''))
 result=getattr(client,'profile_get',client.get)(url)
 if result['state']!='found':return result|{'matches':[]}
 from .publicengines import observed_payload
 negotiated=observed_payload(url,alias,result)
 if negotiated is not None:return negotiated
 if site=='HackerOne' and result['text'].lstrip().startswith('{'):
  from .publicprofile import read
  class Cached:
   def get(self,target):return result
  profile=read({'url':url,'platform':'HackerOne'},Cached())
  return profile|{'matches':[{'url':profile.get('canonical_url',url),'data':profile.get('data',{}),'evidence':profile.get('evidence',[])}] if profile['state']=='found' else []}
 html=result['text'];meta=Meta();meta.feed(html);page=ProfileHTML();page.feed(html);page.close()
 title=' '.join(meta.title).strip();visible=' '.join(page.parts).casefold()
 if any(x in visible for x in ('verify you are human','just a moment...','enable javascript','access denied','captcha')):return {'state':'blocked','detail':site+': blokada lub wymagany JavaScript','matches':[]}
 if any(x in title.casefold() for x in service['detection']['not_found_titles']):return {'state':'not_found','detail':site+': strona błędu w odpowiedzi HTTP 200','matches':[]}
 def same(candidate):
  try:return normalize(candidate)==normalize(url)
  except (ValueError,AttributeError):return False
 if not same(result.get('url',url)):return {'state':'partial','detail':site+': przekierowanie poza żądany profil; brak potwierdzenia','matches':[]}
 person=page.persons(url)
 explicit=(meta.values.get('og:type','').casefold()=='profile' or meta.values.get('profile:username','').casefold()==alias.casefold()) and (same(meta.canonical) or same(meta.values.get('og:url'))) and (meta.values.get('profile:username','').casefold()==alias.casefold() or bool(re.search(r'(?<![\w])'+re.escape(alias)+r'(?![\w])',title,re.I)))
 if not person and not explicit:
  from .publicengines import fallback
  enriched=fallback(url,alias,meta.values.get('generator',''),client)
  if enriched is not None:return enriched
  return {'state':'partial','detail':site+': HTTP 200 bez jednoznacznych danych profilu; nie dodano trafienia','matches':[]}
 data={'alias':alias,'display':person[0].get('name') if person else None,'title':title[:200],'avatar_url':meta.values.get('og:image'),'public_probe':site}
 evidence=[]
 for description in page.meta:evidence.extend(extract(description,url,'profile_description'))
 evidence.extend(page.person_evidence(url));evidence.extend(page.identity_evidence(url))
 evidence.extend(extract("",url,"profile.outbound",links=page.links))
 return {'state':'found','detail':site+': jawne metadane profilu; właściciel niepotwierdzony','matches':[{'url':url,'data':data,'evidence':evidence}]}
