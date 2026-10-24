"""Optional licensed definition catalog. HTTP 200 without profile proof stays quarantined."""
import json,os,re
from pathlib import Path
from functools import lru_cache
from urllib.robotparser import RobotFileParser
from urllib.parse import urlsplit,quote
from .identity import normalize
@lru_cache(maxsize=1)
def services():
    from .definition_import import PATTERN
    paths=[Path(__file__).with_name(name) for name in ('imported_catalog.json','maigret_catalog.json')]
    paths.extend(Path(value) for value in os.environ.get('NICKTRAIL_DEFINITION_PACKS','').split(os.pathsep) if value)
    if len(paths)>6:raise ValueError('At most four optional definition packs')
    result=[];seen=set();ids=set()
    for path in paths:
        if path.stat().st_size>12000000:raise ValueError('Definition pack too large')
        pack=json.loads(path.read_text(encoding='utf-8'))
        if pack.get('schema_version')!=1 or pack.get('license') not in ('MIT','CC-BY-SA-4.0') or not isinstance(pack.get('license_text'),str) or not isinstance(pack.get('services'),list) or len(pack['services'])>1500:raise ValueError('Invalid licensed definition pack')
        for original in pack['services']:
            row=dict(original);template=row.get('profile_url','');id=row.get('id','')
            if not isinstance(id,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',id) or id in ids or row.get('username_pattern')!=PATTERN or not isinstance(template,str) or template.count('{nick}')!=1 or '{' in template.replace('{nick}','') or '}' in template.replace('{nick}',''):raise ValueError('Invalid definition route')
            url=normalize(template.format(nick='nicktrailfixture'));p=urlsplit(url)
            if p.scheme!='https' or p.query or p.fragment or row.get('provenance',{}).get('license')!=pack['license'] or not re.fullmatch('[a-f0-9]{40}',row.get('provenance',{}).get('revision','')):raise ValueError('Unsafe definition provenance')
            ids.add(id)
            if url in seen:continue
            seen.add(url)
            # A pack cannot replace NickTrail policy or inject detector regex/request behavior.
            row['detection']={'strategy':'explicit_profile_metadata','redirect_policy':'same_normalized_url','not_found_titles':['404 not found','page not found','user not found']}
            row['validation']={'live_status':'UNTESTED','coverage_claim':'definition_only_not_verified'}
            result.append(row)
    return tuple(result)
def lookup(term,client):
    from .search import validate_nickname
    from .freeprofiles import probe
    site,alias=term.split(':',1);alias=validate_nickname(alias)
    service=next((s for s in services() if s['id']==site),None)
    if not service:raise ValueError('Nieznana definicja importowana')
    url=normalize(service['profile_url'].format(nick=quote(alias,safe='')));p=urlsplit(url);base=p.scheme+'://'+p.netloc
    # One shared robots.txt decision (settings, memory, RFC 9309) for every reader.
    if callable(getattr(client,'profile_policy',None)):denied=client.profile_policy(url)
    else:
        from .network import robots_decision
        denied=robots_decision(client.get,url,1)[0]
    if denied:return {'state':'blocked','matches':[],'detail':denied}
    result=probe(service,alias,client)
    if result['state']=='partial':
        result['state']='unverified';result['matches']=[{'url':url,'data':{'alias':alias,'definition_only':True,'definition_id':site,'definition_revision':service['provenance']['revision']},'evidence':[]}]
        result['detail']+=' Definicja importowana; brak dowodu istnienia profilu.'
    return result
