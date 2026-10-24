"""Documented X user lookup; profile links use expanded_url, never display_url."""
import json
import os
import re
from urllib.parse import urlsplit,quote
from .identity import normalize
from .adapters import extract

def parse(data,source):
    if not isinstance(data,dict) or not str(data.get('id','')).isdigit() or int(data['id'])<=0 or not isinstance(data.get('username'),str) or not re.fullmatch(r'[A-Za-z0-9_]{1,15}',data['username']):
        raise ValueError('Nieprawidłowy profil X')
    evidence=extract(str(data.get('description') or ''),source,'description')
    entities=data.get('entities') or {}
    if not isinstance(entities,dict):raise ValueError('Nieprawidłowe entities X')
    for field in ('url','description'):
        part=entities.get(field) or {}
        if not isinstance(part,dict) or not isinstance(part.get('urls',[]),list):raise ValueError('Nieprawidłowe URL X')
        for item in part.get('urls',[])[:30]:
            if not isinstance(item,dict):continue
            raw=item.get('expanded_url') or item.get('url')
            if not isinstance(raw,str):continue
            try:url=normalize(raw)
            except ValueError:continue
            if urlsplit(url).hostname=='t.co':continue
            evidence.append({'url':url,'relation':'links','location':'entities.'+field+'.urls','snippet':url,'method':'x_api'})
    raw=data.get('url')
    if isinstance(raw,str):
        try:
            url=normalize(raw)
            if urlsplit(url).hostname!='t.co':evidence.append({'url':url,'relation':'links','location':'url','snippet':url,'method':'x_api'})
        except ValueError:pass
    unique={}
    for e in evidence:unique[(e.get('url',e.get('email')),e['location'])]=e
    return {'state':'found','canonical_url':'https://x.com/'+data['username'],'data':{'avatar_url':data.get('profile_image_url'),'stable_id':str(data['id']),'alias':data['username'],'display':data.get('name'),'declared_location':data.get('location')},'evidence':list(unique.values())}

def read(node,client):
    token=os.environ.get('NICKTRAIL_X_BEARER_TOKEN','')
    if not token:return {'state':'unsupported','detail':'Nie odczytano profilu X: wymagany NICKTRAIL_X_BEARER_TOKEN i dostęp do API X. Możesz dodać link widoczny w przeglądarce jako ręczną obserwację.'}
    handle=urlsplit(node['url']).path.strip('/')
    if not re.fullmatch(r'[A-Za-z0-9_]{1,15}',handle):return {'state':'unsupported','detail':'Wymagany adres profilu X, nie wpisu lub strony serwisu'}
    stable=json.loads(node.get('data','{}')).get('stable_id')
    path='/2/users/'+str(stable) if str(stable or '').isdigit() else '/2/users/by/username/'+quote(handle,safe='')
    response=client.get('https://api.x.com'+path+'?user.fields=description,url,entities,location,name,username,profile_image_url',headers={'Authorization':'Bearer '+token})
    if response['state']!='found':return response
    body=json.loads(response['text'])
    if not isinstance(body,dict) or 'data' not in body:return {'state':'error','detail':'API X nie zwróciło danych profilu'}
    return parse(body['data'],node['url'])

def manual_link(store,source,url,note):
    node=store.node(source)
    if node['kind'] not in ('profile','page'):raise ValueError('Wybierz profil lub stronę źródłową')
    url=normalize(url)
    if not isinstance(note,str) or not note.strip() or len(note)>500:raise ValueError('Podaj opis ręcznej obserwacji (do 500 znaków)')
    if normalize(node['url'])==url:raise ValueError('Odnośnik prowadzi do tego samego źródła')
    target=store.add(node['project'],url,seed=False,depth=node['depth']+1)
    store.evidence(node['project'],source,target,'links',node['url'],'imported_profile',note,'manual_observation',context='user_supplied')
    return target
