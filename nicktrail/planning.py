"""Reviewable queries derived only from confirmed self-audit sources."""
import json
from urllib.parse import urlsplit
from .context import criteria
from .search import validate_nickname

def suggestions(store,project):
    snapshot=store.snapshot(project)
    sources=[n for n in snapshot['nodes'] if n['ownership']=='mine' and n['kind'] in ('profile','page')]
    plan=[];seen=set()
    for source in sources:
        data=json.loads(source['data'])
        alias=data.get('alias')
        if isinstance(alias,str):
            try:alias=validate_nickname(alias)
            except ValueError:alias=None
            if alias and ('alias',alias.casefold()) not in seen:
                plan.append({'kind':'alias','value':alias,'source':source['id'],'reason':'Nick odczytany z konta oznaczonego przez Ciebie jako moje'});seen.add(('alias',alias.casefold()))
        display=data.get('display')
        if isinstance(display,str) and display.strip() and len(display)<=160 and ('words',display.casefold()) not in seen:
            plan.append({'kind':'words','value':display,'source':source['id'],'reason':'Nazwa wyświetlana konta oznaczonego jako moje'});seen.add(('words',display.casefold()))
        for edge in snapshot['evidence']:
            if edge['source']!=source['id'] or not edge.get('current',1) or edge['decision']=='rejected' or edge['relation'] not in ('links','claims_ownership'):continue
            target=next((n for n in snapshot['nodes'] if n['id']==edge['target']),None)
            if not target or target['kind'] not in ('profile','page') or target['ownership']=='not_mine':continue
            if ('url',target['url']) in seen:continue
            plan.append({'kind':'url','value':target['url'],'source':source['id'],'reason':'Jawny odnośnik; konto docelowe nadal wymaga weryfikacji'});seen.add(('url',target['url']))
    return plan[:30]

def words_queries(value):
    c=criteria(value);name=' '.join(filter(None,(c['first_name'],c['last_name'])))
    # Separate independent keywords; never turn a comma-separated list into one rigid phrase.
    words=[w.strip() for w in c['keywords'].split(',') if w.strip()][:4]
    out=[name,*words]
    if name and c['location']:out.append(name+' '+c['location'])
    if c['last_name'] and c['location']:out.append(c['last_name']+' '+c['location'])
    return list(dict.fromkeys(v for v in out if v))[:8]
