"""Opt-in APIs. Secrets come only from environment and never enter stored results."""
import json
import os
from urllib.parse import quote, urlsplit
from .identity import normalize
from .adapters import Page,extract


def configured(platform):
    return bool(os.environ.get('NICKTRAIL_STEAM_KEY')) if platform=='Steam' else bool(os.environ.get('NICKTRAIL_MASTODON_TOKEN') and os.environ.get('NICKTRAIL_MASTODON_INSTANCE'))


def mastodon_base():
    base=normalize(os.environ.get('NICKTRAIL_MASTODON_INSTANCE',''))
    p=urlsplit(base)
    if p.scheme!='https' or p.path or p.query: raise ValueError('Instancja Mastodon: https://domena bez ścieżki')
    return base


def steam_profile(steamid,client):
    if not str(steamid).isdigit(): raise ValueError('Nieprawidłowy SteamID')
    response=client.get('https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key='+quote(os.environ['NICKTRAIL_STEAM_KEY'],safe='')+'&steamids='+str(steamid))
    if response['state']!='found': return response
    body=json.loads(response['text'])
    players=body.get('response',{}).get('players')
    if not isinstance(players,list): raise ValueError('Nieprawidłowa odpowiedź Steam')
    player=next((d for d in players if isinstance(d,dict) and str(d.get('steamid'))==str(steamid)),None)
    if not player:return {'state':'not_found','detail':'Brak profilu w odpowiedzi API Steam'}
    return {'state':'found','data':{'avatar_url':player.get('avatarmedium') or player.get('avatar'),'stable_id':str(steamid),'display':player.get('personaname')},'evidence':[], 'url':'https://steamcommunity.com/profiles/'+str(steamid)}


def steam_lookup(nickname,client):
    response=client.get('https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/?key='+quote(os.environ['NICKTRAIL_STEAM_KEY'],safe='')+'&vanityurl='+quote(nickname,safe=''))
    if response['state']!='found': return response
    body=json.loads(response['text']).get('response',{})
    if body.get('success')!=1:return {'state':'not_found','detail':'Brak dokładnego vanity URL; to nie jest wyszukiwanie po nazwie wyświetlanej Steam'}
    return steam_profile(body['steamid'],client)


def mastodon_lookup(nickname,client):
    base=mastodon_base()
    response=client.get(base+'/api/v1/accounts/lookup?acct='+quote(nickname,safe=''),headers={'Authorization':'Bearer '+os.environ['NICKTRAIL_MASTODON_TOKEN']})
    if response['state']!='found':return response
    d=json.loads(response['text'])
    if not isinstance(d,dict) or 'id' not in d or str(d.get('username','')).lower()!=nickname.lower():raise ValueError('Nieprawidłowe konto Mastodon')
    url=base+'/@'+nickname
    page=Page();page.feed(d.get('note') or '')
    evidence=extract('\n'.join(page.parts),url,'bio',links=page.links)
    for field in d.get('fields',[])[:20]:
        page=Page();page.feed(str(field.get('value') or ''))
        evidence+=extract('\n'.join(page.parts),url,'profile_field',links=page.links)
    return {'state':'found','url':url,'data':{'avatar_url':d.get('avatar_static') or d.get('avatar'),'stable_id':base+':'+str(d['id']),'alias':d.get('acct'),'display':d.get('display_name'),'instance':base},'evidence':evidence}


def read_keyed(node,client):
    if not configured(node['platform']):return {'state':'unsupported','detail':'Brak wymaganej konfiguracji API'}
    p=urlsplit(node['url'])
    if node['platform']=='Mastodon':
        if p.scheme+'://'+p.hostname != mastodon_base():return {'state':'unsupported','detail':'Token skonfigurowany dla innej instancji'}
        return mastodon_lookup(p.path.strip('/@'),client)
    parts=p.path.strip('/').split('/')
    return steam_profile(parts[1],client) if parts[0]=='profiles' else steam_lookup(parts[1],client)
