"""Reusable public exact-user engines; no credentials, directory crawling or remote resolution."""
import json
from urllib.parse import quote,urlsplit
from .engineconfig import instances

def lookup_platform(platform,alias,client,instance=None):
    from .search import validate_nickname
    from .adapters import extract
    from .identity import normalize
    alias=validate_nickname(alias);conf=instance or instances()[platform];base='https://'+conf['host'];kind=conf['engine'];q=quote(alias,safe='')
    from .engineconfig import HTML_ENGINES
    if kind in HTML_ENGINES:
        from .freeprofiles import probe
        result=probe({'id':platform or kind,'name':kind,'profile_url':conf['profile_url'],'detection':{'not_found_titles':['404 not found','page not found','user not found']}},alias,client)
        for match in result.get('matches',[]):match['data'].update(public_engine=kind,id_scope=conf['host'],engine_verification='explicit_public_profile_metadata_not_native_api')
        return result
    if kind in ('mastodon','peertube','mediawiki','nodebb','forgejo','flarum'):
        from .publicengines import lookup
        return lookup(kind,conf['host'],alias,client)
    endpoint={'gitea':'/api/v1/users/'+q,'gitlab':'/api/v4/users?username='+q,'discourse':'/u/'+q+'.json','wordpress':'/wp-json/wp/v2/users?slug='+q,'lemmy':'/api/v3/user?username='+q}[kind]
    response=client.get(base+endpoint)
    if response['state']!='found':return response|{'matches':[]}
    final=urlsplit(response.get('url') or base)
    if final.hostname!=conf['host'] or final.scheme!='https':return {'state':'partial','matches':[],'detail':'REDIRECT_POLICY_BLOCKED: API left selected HTTPS instance'}
    body=json.loads(response['text']);data={};fields=()
    if kind in ('gitlab','wordpress'):
        if not isinstance(body,list):raise ValueError('Nieprawidłowa lista publicznych profili')
        key='username' if kind=='gitlab' else 'slug';body=next((b for b in body if isinstance(b,dict) and str(b.get(key,'')).casefold()==alias.casefold()),None)
        if body is None:return {'state':'not_found','matches':[],'detail':'Brak dokładnego publicznego profilu'}
    elif kind=='discourse':body=body.get('user') if isinstance(body,dict) else None
    elif kind=='lemmy':
        view=body.get('person_view') if isinstance(body,dict) else None
        body=view.get('person') if isinstance(view,dict) else None
    if not isinstance(body,dict):return {'state':'partial','matches':[],'detail':'Brak rozpoznanych publicznych danych instancji'}
    key={'gitea':'login','gitlab':'username','discourse':'username','wordpress':'slug','lemmy':'name'}[kind];name=body.get(key)
    if type(body.get('id')) is not int or body['id']<=0 or not isinstance(name,str) or name.casefold()!=alias.casefold():return {'state':'partial','matches':[],'detail':'Nie potwierdzono żądanego konta w publicznym API'}
    url=base+{'gitea':'/','gitlab':'/','discourse':'/u/','wordpress':'/author/','lemmy':'/u/'}[kind]+quote(name,safe='')
    if kind=='lemmy' and (body.get('local') is not True or body.get('deleted') is True or urlsplit(str(body.get('actor_id',''))).hostname!=conf['host']):return {'state':'partial','matches':[],'detail':'Brak jednoznacznego lokalnego konta Lemmy'}
    if kind=='wordpress':
        candidate=normalize(str(body.get('link') or url))
        if urlsplit(candidate).hostname!=conf['host']:return {'state':'partial','matches':[],'detail':'Link autora poza instancją'}
        url=candidate
    fields={'gitea':('description','website'),'gitlab':('bio','website_url'),'discourse':('bio_raw','bio_cooked','website'),'wordpress':('description','url'),'lemmy':('bio',)}[kind]
    evidence=[]
    for field in fields:
        text=body.get(field)
        if isinstance(text,str):evidence+=extract(text,url,field)
    data={'stable_id':str(body['id']),'alias':name,'display':body.get('full_name') or body.get('display_name') or body.get('name'),'bio':next((body.get(k) for k in ('bio','description','bio_raw') if isinstance(body.get(k),str)),None),'declared_location':body.get('location'),'avatar_url':body.get('avatar_url') or body.get('avatar'),'public_engine':kind,'id_scope':conf['host']}
    return {'state':'found','matches':[{'url':url,'data':data,'evidence':evidence}],'detail':'Publiczny profil instancji '+kind+'; ID jest lokalne dla tej instancji.'}
def read(node,client):
    alias=urlsplit(node['url']).path.strip('/').split('/')[-1]
    from urllib.parse import unquote
    alias=unquote(alias).removeprefix('@').removeprefix('User:').replace(' ','_')
    old=json.loads(node.get('data') or '{}')
    from .engineconfig import HTML_ENGINES
    definition=instances()[node['platform']]
    if definition['engine'] in HTML_ENGINES:
        from .engineconfig import alias_for_url
        alias=alias_for_url(definition,node['url'])
        if not alias:return {'state':'unsupported','detail':'MANUAL_ONLY: URL nie odpowiada jawnej publicznej trasie profilu instancji'}
    elif definition['engine']=='flarum' and isinstance(old.get('alias'),str):alias=old['alias']
    r=lookup_platform(node['platform'],alias,client);matches=r.get('matches',[])
    if matches and old.get('stable_id') and str(old['stable_id'])!=str(matches[0]['data'].get('stable_id')):return {'state':'partial','detail':'PERSISTENT_ID_CONFLICT: public handle now resolves to a different account; previous identity retained'}
    return {'state':'found','canonical_url':matches[0]['url'],'data':matches[0]['data'],'evidence':matches[0]['evidence']} if matches else {k:v for k,v in r.items() if k!='matches'}
