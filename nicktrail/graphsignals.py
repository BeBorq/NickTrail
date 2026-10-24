"""Derived public-evidence paths, recomputed from the current snapshot.

No new ownership decisions or entity merges. Provenance points to original edges.
"""
from collections import defaultdict, deque
from urllib.parse import urlsplit
from .identity import SERVICES, team_email
from .context import SITES
from .independence import group as source_group
from .accountentities import non_person

PUBLIC_METHODS={'parser','rendered_public_page'}

def analyze(snapshot, max_depth=3):
    nodes={n['id']:n for n in snapshot['nodes']}
    anchors={n['id'] for n in nodes.values() if n.get('ownership')=='mine' and n['kind'] in ('profile','page')}
    anchors.update(f['node'] for f in snapshot.get('focus',[]) if f['node'] in nodes and nodes[f['node']].get('ownership')!='not_mine')
    if not anchors:return {}
    adjacency=defaultdict(list)
    seen_edges=set()
    known_domains=set(SITES)|set(SERVICES)
    def identifier(n):
        if non_person(n):return False
        if n.get('ownership')=='not_mine':return False
        if n['kind']=='email':return not team_email(n['url'])
        if n['kind'] not in ('profile','page'):return False
        p=urlsplit(n['url']);host=(p.hostname or '').removeprefix('www.')
        if p.query or p.path.strip('/').lower() in ('login','signin','signup','privacy','terms','help','support','search','explore'):return False
        if n['kind']=='profile' and p.path.strip('/'):return True
        # Shared provider homepages are not personal websites.
        return bool(host and host not in known_domains and n.get('platform')=='Strona')
    for index,e in enumerate(snapshot['evidence']):
        source=nodes.get(e['source']);target=nodes.get(e['target'])
        if not source or not target or non_person(source) or source['kind'] not in ('profile','page') or source.get('state')!='found' or source.get('ownership')=='not_mine':continue
        if not e.get('current',1) or e.get('decision')=='rejected' or e.get('context','own')!='own' or e.get('method','parser') not in PUBLIC_METHODS:continue
        if e['relation'] not in ('links','claims_ownership','public_contact_occurrence'):continue
        if not identifier(target) or source['id']==target['id']:continue
        # Contact edges must actually refer to an email node; no mixed relation tricks.
        if (e['relation']=='public_contact_occurrence')!=(target['kind']=='email'):continue
        key=(e['source'],e['target'],e['relation'])
        if key in seen_edges:continue
        seen_edges.add(key)
        proof={'id':e.get('id'), 'source':e['source'],'target':e['target'],'source_url':e.get('source_url',source['url']),
               'location':e.get('location',''),'method':e.get('method','parser'),'snippet':e.get('snippet','')[:500],
               'fetched':e.get('last_seen') or e.get('fetched',''),'relation':e['relation'],'independence_group':source_group(source)}
        adjacency[source['id']].append((target['id'],proof))
        adjacency[target['id']].append((source['id'],proof))
    results=defaultdict(list)
    for anchor in sorted(anchors):
        if nodes[anchor].get('ownership')=='not_mine':continue
        queue=deque([(anchor,[anchor],[])])
        while queue:
            at,path,proofs=queue.popleft()
            if len(proofs)>=max_depth:continue
            # Bound propagation through popular identifiers, without erasing direct links.
            if at!=anchor and len({v for v,_ in adjacency[at]})>8:continue
            for target,proof in sorted(adjacency[at],key=lambda pair:pair[0]):
                if target in path:continue
                new_path=path+[target];new_proofs=proofs+[proof]
                n=nodes[target]
                if n['kind'] in ('profile','page') and target not in anchors:
                    shared=len(new_proofs)==2 and all(p['target']==path[-1] for p in new_proofs)
                    kind=('shared_public_email' if nodes[path[-1]]['kind']=='email' else 'shared_profile' if nodes[path[-1]]['kind']=='profile' else 'shared_website') if shared else ('direct_link' if proof['source']==anchor else 'incoming_link') if len(new_proofs)==1 else 'public_path'
                    strength={'shared_public_email':36,'shared_profile':26,'shared_website':18,'direct_link':28,'incoming_link':8,'public_path':20}[kind]
                    if len(new_proofs)==3:strength=12
                    results[target].append({'kind':kind,'anchor':anchor,'path':new_path,'edges':new_proofs,'strength':strength,
                                            'independent_sources':len({p['independence_group'] for p in new_proofs}), 'identity_confirmed':False})
                if len(new_proofs)==1 and proof['source']!=anchor:continue
                queue.append((target,new_path,new_proofs))
    return {id:sorted(signals,key=lambda s:(-s['strength'],len(s['edges']),s['anchor']))[:3] for id,signals in results.items()}
