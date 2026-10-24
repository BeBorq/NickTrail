"""Validated structured service definitions. A template is not validated live support."""
import json,re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

@lru_cache(maxsize=1)
def services():
    payload=json.loads(Path(__file__).with_name('platform_catalog.json').read_text(encoding='utf-8'))
    if payload.get('schema_version')!=1 or not isinstance(payload.get('services'),list):raise ValueError('Nieprawidłowy katalog serwisów')
    ids=set();records=[]
    for entry in payload['services']:
        required={'id','name','domain','profile_url','username_pattern','category','detection','public_metadata','public_api','rate_limits','validation'}
        if not isinstance(entry,dict) or set(entry)!=required:raise ValueError('Nieprawidłowy rekord katalogu')
        if not isinstance(entry['id'],str) or not entry['id'] or ':' in entry['id'] or entry['id'] in ids:raise ValueError('Powtórzony lub nieprawidłowy identyfikator serwisu')
        ids.add(entry['id'])
        if entry['profile_url'].count('{nick}')!=1 or '{' in entry['profile_url'].replace('{nick}',''):raise ValueError('Nieprawidłowy szablon profilu')
        url=urlsplit(entry['profile_url'].format(nick='nicktrail'))
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.port not in (None,443):raise ValueError('Niebezpieczny szablon profilu')
        if not (url.hostname==entry['domain'] or url.hostname.endswith('.'+entry['domain'])):raise ValueError('Niezgodna domena katalogu')
        re.compile(entry['username_pattern'])
        if entry['detection'].get('strategy') not in ('hackerone_json_or_profile_metadata','explicit_profile_metadata'):raise ValueError('Nieobsługiwana strategia wykrywania')
        if entry['detection'].get('redirect_policy')!='same_normalized_url':raise ValueError('Nieobsługiwana polityka przekierowań')
        records.append(entry)
    return tuple(records)

def definition(id):
    return next((s for s in services() if s['id']==id),None)

def summary():
    return [{'id':s['id'],'name':s['name'],'domain':s['domain'],'category':s['category'],'strategy':s['detection']['strategy'],'validation':s['validation'],'discovery':'username_template','verification':'explicit_metadata_only','enrichment':s['public_metadata'],'outbound_links':'public HTML / sameAs / rel=me when verified','limitations':'JavaScript/blocks/ambiguous HTML remain partial or blocked; not a guarantee of support'} for s in services()]
