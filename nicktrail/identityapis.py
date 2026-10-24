"""Public identity bridges: Keybase lookup/proof directory and official HN API."""
import json,re
from urllib.parse import urlencode,urlsplit,parse_qs,quote
from .identity import normalize
from .adapters import extract
PREFIXES={'github','twitter','reddit','hackernews','domain'}

def lookup_platform(platform,term,client):
    if platform=='HackerNews':
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,63}',term):return {'state':'unsupported','matches':[],'detail':'HN wymaga dokładnego nicku z zachowaniem wielkości liter.'}
        result=client.get('https://hacker-news.firebaseio.com/v0/user/'+quote(term,safe='')+'.json')
        if result['state']!='found':return result
        body=json.loads(result['text'])
        if body is None:return {'state':'not_found','matches':[],'detail':'API HN nie zwróciło publicznego aktywnego konta; nie dowodzi to braku konta.'}
        if not isinstance(body,dict) or body.get('id')!=term:return {'state':'partial','matches':[],'detail':'Nieprawidłowe konto HN w odpowiedzi'}
        url='https://news.ycombinator.com/user?'+urlencode({'id':term})
        return {'state':'found','matches':[{'url':url,'data':{'alias':term,'bio':body.get('about'),'public_adapter':'HackerNews'},'evidence':extract(str(body.get('about') or ''),url,'about')}],'detail':'Publiczne aktywne konto HN; nick jest rozróżniany wielkością liter.'}
    if ':' in term:
        key,value=term.split(':',1)
        if key not in PREFIXES or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,252}',value):return {'state':'unsupported','matches':[],'detail':'Keybase: obsługiwane github:/twitter:/reddit:/hackernews:/domain:'}
    else:
        key='usernames';value=term
        from .providers import REGISTRY
        if not REGISTRY['Keybase'].valid_username(value):return {'state':'unsupported','matches':[],'detail':'USERNAME_RULE_REJECTED: Keybase wymaga 2–16 znaków, bez początkowego lub podwójnego podkreślenia'}
    result=client.get('https://keybase.io/_/api/1.0/user/lookup.json?'+urlencode({key:value,'fields':'basics,profile,proofs_summary,pictures'}))
    if result['state']!='found':return result
    body=json.loads(result['text'])
    if not isinstance(body,dict) or not isinstance(body.get('status'),dict):return {'state':'partial','matches':[],'detail':'PROFILE_SCHEMA_MISMATCH: Keybase status envelope'}
    if body['status'].get('code')!=0:
        code=body['status'].get('code');kind='UPSTREAM_INPUT_ERROR' if code==100 else 'UPSTREAM_API_ERROR'
        return {'state':'partial','matches':[],'detail':kind+': Keybase status '+str(code)[:12]+'; brak potwierdzonego wyniku, nie oznacza braku konta'}
    users=body.get('them')
    if not isinstance(users,list):raise ValueError('Nieprawidłowa lista Keybase')
    matches=[]
    for user in users[:10]:
        if not isinstance(user,dict):continue
        basics=user.get('basics',{});profile=user.get('profile') or {};summary=user.get('proofs_summary') or {};proofs=summary.get('all',[]) if isinstance(summary,dict) else []
        if not isinstance(basics,dict) or not isinstance(profile,dict) or not isinstance(proofs,list):continue
        alias=basics.get('username');uid=user.get('id')
        if not isinstance(alias,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,63}',alias) or not isinstance(uid,str) or not re.fullmatch('[a-f0-9]{16,64}',uid) or basics.get('status',0)!=0:continue
        if key=='usernames' and alias.casefold()!=value.casefold():continue
        # Reverse lookup must be backed by a matching current directory entry, not just API text.
        valid=[p for p in proofs if isinstance(p,dict) and type(p.get('state')) is int and p['state']==1 and isinstance(p.get('service_url'),str)]
        if key!='usernames' and not any(str(p.get('nametag','')).casefold()==value.casefold() and (p.get('proof_type')==key or key=='domain' and p.get('proof_type') in ('dns','generic_web_site')) for p in valid):continue
        url='https://keybase.io/'+alias;evidence=extract(str(profile.get('bio') or ''),url,'bio')
        for proof in valid[:50]:evidence+=extract('',url,'keybase.proof.'+str(proof.get('proof_type','unknown')),links=[proof['service_url']])
        pictures=user.get('pictures') or {};pictures=pictures if isinstance(pictures,dict) else {};primary=pictures.get('primary') or {};primary=primary if isinstance(primary,dict) else {}
        matches.append({'url':url,'data':{'stable_id':uid,'alias':alias,'display':profile.get('full_name'),'bio':profile.get('bio'),'declared_location':profile.get('location'),'avatar_url':primary.get('url'),'public_adapter':'Keybase'},'evidence':evidence})
    return {'state':'found' if matches else 'not_found','matches':matches,'detail':'Publiczny katalog Keybase i jego deklaracje powiązań; NickTrail nie weryfikuje podpisów kryptograficznych ani własności.'}

def read(node,client):
    alias=parse_qs(urlsplit(node['url']).query).get('id',[''])[0] if node['platform']=='HackerNews' else urlsplit(node['url']).path.strip('/')
    result=lookup_platform(node['platform'],alias,client);matches=result.get('matches',[])
    if not matches:return {k:v for k,v in result.items() if k!='matches'}
    m=matches[0];return {'state':'found','canonical_url':m['url'],'data':m['data'],'evidence':m['evidence'],'detail':result['detail']}
