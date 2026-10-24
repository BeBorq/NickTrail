"""Exact documented public profile APIs; never convert names into ownership."""
import json,re
from urllib.parse import quote,urlencode,urlsplit
from .adapters import extract
SITES={'Codewars':('https://www.codewars.com/users/','https://www.codewars.com/api/v1/users/'),'Modrinth':('https://modrinth.com/user/','https://api.modrinth.com/v2/user/'),'Codeforces':('https://codeforces.com/profile/','https://codeforces.com/api/user.info?handles='),'Launchpad':('https://launchpad.net/~','https://api.launchpad.net/1.0/~')}
def lookup_platform(platform,alias,client):
    from .search import validate_nickname
    alias=validate_nickname(alias);base,api=SITES[platform];url=base+quote(alias,safe='')
    response=client.get(api+quote(alias,safe=''))
    if response['state']!='found':return response|{'matches':[]}
    body=json.loads(response['text']);data={};evidence=[]
    if platform=='Codeforces':
        if not isinstance(body,dict):raise ValueError('Nieprawidłowa odpowiedź Codeforces')
        if body.get('status')!='OK':
            from .apierrors import codeforces_error
            typed=codeforces_error(body,[alias])
            if typed and typed['state']=='blocked' and hasattr(client,'defer_host'):client.defer_host('codeforces.com',60)
            return (typed or {'state':'partial','detail':'Codeforces odrzucił zapytanie; brak potwierdzenia profilu'})|{'matches':[]}
        users=body.get('result');body=users[0] if isinstance(users,list) and len(users)==1 and isinstance(users[0],dict) else {}
        name=body.get('handle');data={'display':' '.join([v for v in (body.get('firstName'),body.get('lastName')) if isinstance(v,str)]),'declared_location':', '.join([v for v in (body.get('city'),body.get('country')) if isinstance(v,str)]),'avatar_url':body.get('titlePhoto'),'organization':body.get('organization')}
    elif platform=='Codewars':
        if not isinstance(body,dict):raise ValueError('Nieprawidłowy profil Codewars')
        name=body.get('username');data={'display':body.get('name'),'bio':body.get('bio'),'organization':body.get('clan')}
    elif platform=='Modrinth':
        if not isinstance(body,dict) or not isinstance(body.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9]{8}',body['id']):return {'state':'partial','matches':[],'detail':'Brak trwałego ID Modrinth'}
        name=body.get('username');data={'stable_id':body['id'],'display':body.get('name'),'bio':body.get('bio'),'avatar_url':body.get('avatar_url')}
    else:
        if not isinstance(body,dict) or not str(body.get('resource_type_link','')).endswith('#person'):return {'state':'partial','matches':[],'detail':'Launchpad nie zwrócił publicznej osoby'}
        name=body.get('name');data={'display':body.get('display_name'),'bio':body.get('description')}
    if not isinstance(name,str) or name.casefold()!=alias.casefold():return {'state':'partial','matches':[],'detail':'Odpowiedź nie dotyczy dokładnego żądanego nicku'}
    url=base+quote(name,safe='')
    for field in ('bio','description','website_link'):
        if isinstance(body.get(field),str):evidence+=extract(body[field],url,field)
    return {'state':'found','matches':[{'url':url,'data':data|{'alias':name,'public_adapter':platform},'evidence':evidence}],'detail':'Dokładny publiczny profil API; własność pozostaje niepotwierdzona.'}
def read(node,client):
    alias=urlsplit(node['url']).path.strip('/').split('/')[-1].removeprefix('~')
    result=lookup_platform(node['platform'],alias,client);matches=result.get('matches',[])
    return {'state':'found','canonical_url':matches[0]['url'],'data':matches[0]['data'],'evidence':matches[0]['evidence']} if matches else {k:v for k,v in result.items() if k!='matches'}
