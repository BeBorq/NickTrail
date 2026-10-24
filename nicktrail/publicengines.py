"""Fixed public APIs for explicitly chosen or positively fingerprinted instances."""
import json,re
from urllib.parse import urlsplit,quote,urlencode
from .identity import normalize
SUPPORTED={'gitea','forgejo','gitlab','discourse','wordpress','lemmy','mastodon','peertube','mediawiki','nodebb','flarum'}

def lookup(engine,host,alias,client):
 from .search import validate_nickname
 from .adapters import extract
 alias=validate_nickname(alias)
 base=normalize('https://'+host);parsed=urlsplit(base)
 from .engineconfig import HTML_ENGINES,instances
 if parsed.netloc!=host or parsed.path or parsed.query or parsed.fragment or not re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}',host) or engine not in SUPPORTED|HTML_ENGINES:raise ValueError('Explicit public HTTPS instance required')
 if engine in HTML_ENGINES:
  configured=[r for r in instances().values() if r['engine']==engine and r['host']==host and r.get('profile_url')]
  if len(configured)!=1:return {'state':'unsupported','matches':[],'detail':'MANUAL_ONLY: configure one explicit public profile_url with {nick}; no guessed API or numeric account ID'}
  from .engines import lookup_platform
  return lookup_platform(configured[0]['id'],alias,client,instance=configured[0])
 if engine in {'gitea','forgejo','gitlab','discourse','wordpress','lemmy'}:
  from .engines import lookup_platform
  return lookup_platform('',alias,client,instance={'engine':'gitea' if engine=='forgejo' else engine,'host':host})
 if engine=='flarum':
  response=client.get(base+'/api/users?'+urlencode({'filter[q]':alias,'page[limit]':20}))
  if response['state']!='found':return response|{'matches':[]}
  if urlsplit(response.get('url') or base).hostname!=host or urlsplit(response.get('url') or base).scheme!='https':return {'state':'partial','matches':[],'detail':'REDIRECT_POLICY_BLOCKED'}
  body=json.loads(response['text']);rows=body.get('data') if isinstance(body,dict) else None
  if not isinstance(rows,list) or len(rows)>20:return {'state':'partial','matches':[],'detail':'PROFILE_SCHEMA_MISMATCH: Flarum'}
  matches=[r for r in rows if isinstance(r,dict) and r.get('type')=='users' and isinstance(r.get('attributes'),dict) and isinstance(r['attributes'].get('username'),str) and r['attributes']['username'].casefold()==alias.casefold()]
  if len(matches)!=1:return {'state':'partial','matches':[],'detail':'No unique exact public Flarum result; directory search is not proof of absence'}
  user=matches[0];attrs=user['attributes'];stable=str(user.get('id',''));slug=attrs.get('slug')
  if not re.fullmatch('[0-9]{1,20}',stable) or int(stable)<1 or not isinstance(slug,str) or not re.fullmatch(r'[A-Za-z0-9_.~-]{1,150}',slug):return {'state':'partial','matches':[],'detail':'PROFILE_SCHEMA_MISMATCH: Flarum ID/slug'}
  url=base+'/u/'+quote(slug,safe='');data={'alias':attrs['username'],'stable_id':stable,'id_scope':host,'public_engine':'flarum'}
  for key,field in (('display','displayName'),('avatar_url','avatarUrl'),('bio','bio')):
   if isinstance(attrs.get(field),str):data[key]=attrs[field][:3000]
  return {'state':'found','matches':[{'url':url,'data':data,'evidence':extract(data.get('bio',''),url,'public_engine_profile')}],'detail':'Exact public Flarum result; existence only, ownership unconfirmed'}
 q=quote(alias,safe='')
 endpoint={'mastodon':'/api/v1/accounts/lookup?acct='+q,'peertube':'/api/v1/accounts/'+q,'mediawiki':'/w/api.php?'+urlencode({'action':'query','list':'users','ususers':alias.replace('_',' '),'usprop':'editcount|registration','format':'json','formatversion':2}),'nodebb':'/api/user/'+q}[engine]
 response=client.get(base+endpoint)
 if response['state']!='found':return response|{'matches':[]}
 if urlsplit(response.get('url') or base).hostname!=host:return {'state':'partial','matches':[],'detail':'REDIRECT_POLICY_BLOCKED: API left chosen instance'}
 body=json.loads(response['text'])
 if not isinstance(body,dict):return {'state':'partial','matches':[],'detail':'PROFILE_SCHEMA_MISMATCH'}
 fields=[];data={}
 if engine=='mastodon':
  name=body.get('username');stable=body.get('id');url=body.get('url');bio=body.get('note');data={'display':body.get('display_name'),'bio':bio,'avatar_url':body.get('avatar')}
  if not isinstance(body.get('acct'),str) or body['acct'].casefold()!=alias.casefold() or '@' in body['acct'] or body.get('suspended') is True:return {'state':'partial','matches':[],'detail':'Only local nonsuspended public accounts are supported'}
  fields=[bio]+[f.get('value') for f in body.get('fields',[]) if isinstance(f,dict)]
 elif engine=='peertube':
  name=body.get('name');stable=body.get('id');url=body.get('url');data={'display':body.get('displayName'),'bio':body.get('description')};fields=[body.get('description')]
 elif engine=='nodebb':
  name=body.get('userslug');stable=body.get('uid');url=base+'/user/'+quote(str(name),safe='');data={'display':body.get('username'),'bio':body.get('signature'),'declared_location':body.get('location'),'avatar_url':body.get('picture')};fields=[body.get('signature'),body.get('website')]
 else:
  query=body.get('query',{});users=query.get('users') if isinstance(query,dict) else None
  if not isinstance(users,list) or len(users)!=1 or not isinstance(users[0],dict):return {'state':'partial','matches':[],'detail':'PROFILE_SCHEMA_MISMATCH: wiki users'}
  body=users[0]
  if body.get('missing') is True or body.get('invalid') is True:return {'state':'not_found','matches':[],'detail':'Wiki reports missing public user'}
  name=body.get('name');stable=body.get('userid');url=base+'/wiki/User:'+quote(str(name),safe='');data={'display':name,'public_registration':body.get('registration')}
 expected=alias.replace('_',' ') if engine=='mediawiki' else alias
 name_matches=isinstance(name,str) and ((name[:1].upper()+name[1:])==(expected[:1].upper()+expected[1:]) if engine=='mediawiki' else name.casefold()==expected.casefold())
 if not name_matches or not (type(stable) is int and stable>0 or isinstance(stable,str) and bool(re.fullmatch('[0-9]{1,30}',stable)) and int(stable)>0):return {'state':'partial','matches':[],'detail':'PROFILE_ALIAS_MISMATCH or missing instance ID'}
 try:url=normalize(url)
 except (ValueError,TypeError,AttributeError):return {'state':'partial','matches':[],'detail':'PROFILE_SCHEMA_MISMATCH: profile URL'}
 p=urlsplit(url)
 if p.hostname!=host or p.scheme!='https':return {'state':'partial','matches':[],'detail':'Remote-account URL refused'}
 if engine=='mastodon' and p.path.casefold()!='/@'+alias.casefold():return {'state':'partial','matches':[],'detail':'Local account URL mismatch'}
 evidence=[]
 for field in fields:
  if isinstance(field,str):evidence+=extract(field,url,'public_engine_profile')
 return {'state':'found','matches':[{'url':url,'data':{k:v for k,v in data.items() if isinstance(v,str)}|{'alias':name,'stable_id':str(stable),'public_engine':engine,'id_scope':host},'evidence':evidence}],'detail':'Exact local public engine profile; ownership unconfirmed.'}

def fallback(url,alias,generator,client):
 """No speculative endpoint probing: require generator AND a matching profile route."""
 p=urlsplit(url);path=p.path.rstrip('/');text=str(generator).casefold();engine=None
 if 'discourse' in text and path.casefold() in ('/u/'+alias.casefold(),'/users/'+alias.casefold()):engine='discourse'
 elif ('gitea' in text or 'forgejo' in text) and path.casefold()=='/'+alias.casefold():engine='gitea'
 elif 'gitlab' in text and path.casefold()=='/'+alias.casefold():engine='gitlab'
 elif 'wordpress' in text and path.casefold()=='/author/'+alias.casefold():engine='wordpress'
 elif 'nodebb' in text and path.casefold()=='/user/'+alias.casefold():engine='nodebb'
 if not engine:return None
 return lookup(engine,p.hostname,alias,client)


def observed_payload(url,alias,response):
 """Discourse may negotiate JSON even for /u/name; reuse the permitted observation."""
 path=urlsplit(url).path.rstrip('/')
 if path.casefold() not in ('/u/'+alias.casefold(),'/users/'+alias.casefold()) or not response.get('text','').lstrip().startswith('{'):return None
 try:body=json.loads(response['text'])
 except ValueError:return None
 if not isinstance(body,dict) or not isinstance(body.get('user'),dict):return None
 class CachedObservation:
  def get(self,endpoint):return response
 return lookup('discourse',urlsplit(url).hostname,alias,CachedObservation())
