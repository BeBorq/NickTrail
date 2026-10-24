"""Discovery relevance is not identity evidence or the user label."""
import json
from collections import defaultdict
from .stages import exact_match
from .context import compare
from .accountentities import non_person

def classify(snapshot,ranking,terms=(),criteria=None,per_source_visible=3):
    result={};weak_counts=defaultdict(int);nodes={n['id']:n for n in snapshot['nodes']}
    for id in ranking.get('order',[]):
        n=nodes[id];data=json.loads(n['data']);r=ranking['nodes'].get(str(id),{})
        paths=r.get('graph_paths',[]);exact=exact_match(data,terms,n.get('platform',''))
        strong=not non_person(n) and any(p['kind'] not in ('incoming_link','shared_website') for p in paths)
        matched=compare(data,criteria or {});full={'first_name','last_name'}<=set(matched)
        if n['ownership']=='not_mine':pool='QUARANTINED_DISCOVERY_POOL';reason='Odrzucone przez Ciebie'
        elif n['ownership']=='mine' or strong:pool='STRONG_RESULTS';reason='Twoja deklaracja lub aktualne publiczne powiązanie'
        elif non_person(n) and exact:pool='POSSIBLE_LEADS';reason='Dokładna nazwa konta organizacji/bota; to nie jest dowód tożsamości osoby'
        elif exact and n['state']=='found' and not data.get('indexed_only'):pool='STRONG_RESULTS';reason='Dokładny podany nick, profil odczytany — własność nadal niepotwierdzona'
        elif exact or full:pool='POSSIBLE_LEADS';reason='Dokładny trop nazwy/adresu, wymaga dalszych dowodów'
        else:pool='QUARANTINED_DISCOVERY_POOL';reason='Słabe dopasowanie lub wynik indeksu bez odczytu'
        identity='STRONG' if strong else 'INSUFFICIENT'
        if n['ownership']=='not_mine':identity='CONFLICTING'
        relevance='HIGH' if pool=='STRONG_RESULTS' else 'MODERATE' if pool=='POSSIBLE_LEADS' else 'LOW'
        visible=pool!='QUARANTINED_DISCOVERY_POOL'
        if pool=='POSSIBLE_LEADS' and not exact and not strong:
            weak_counts[n.get('platform','Strona')]+=1;visible=weak_counts[n.get('platform','Strona')]<=per_source_visible
        result[str(id)]={'pool':pool,'discovery_relevance':relevance,'identity_evidence':identity,'user_label':n['ownership'],'exact_supplied_alias':exact,'primary_visible':visible,'reason':reason,'saturation_hidden':pool=='POSSIBLE_LEADS' and not visible}
    return result
