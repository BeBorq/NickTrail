"""Evidence labels are independent from HTTP success or ranking percentages."""
import json
from .context import compare

def labels(snapshot,criteria=None,pending=(),derived=None):
    out={};pending=set(pending)
    if derived is None:
        from .graphsignals import analyze
        paths=analyze(snapshot)
    else:paths={int(id):r.get('graph_paths',[]) for id,r in derived.items()}
    for node in snapshot['nodes']:
        incoming=[e for e in snapshot['evidence'] if e['target']==node['id'] and e.get('current',1) and e['decision']!='rejected' and e['relation'] in ('links','claims_ownership')]
        automatic=[e for e in incoming if e.get('method')!='manual_observation']
        found={n['id'] for n in snapshot['nodes'] if n['state']=='found' and n['ownership']!='not_mine'}
        if node['ownership']=='not_mine':color='red';text='Odrzucone przez Ciebie'
        elif node['id'] in pending:color='gray';text='Oczekuje na odczyt'
        elif node['ownership']=='mine':color='green';text='Własność potwierdzona przez Ciebie'
        elif node['id'] in found and any(e['assessment']=='reciprocal' and e['source'] in found for e in automatic):color='green';text='Odczytane wzajemne odnośniki — własność niepotwierdzona'
        elif automatic:color='orange';text='Jawny jednostronny odnośnik — powiązanie wymaga oceny'
        elif incoming:color='orange';text='Ręczna obserwacja powiązania'
        elif node['state'] in ('unverified','partial','blocked','unsupported','error'):color='gray';text='Brak pełnego odczytu — nie można ocenić powiązania'
        else:color='red';text='Nie znaleziono odnośnika łączącego konta; to nie dowód innego właściciela'
        if color=='red' and node['ownership']!='not_mine' and any(e['source']==node['id'] and e.get('current',1) and e['decision']!='rejected' and e['relation'] in ('links','claims_ownership') and e.get('method')!='manual_observation' for e in snapshot['evidence']):color='orange';text='Profil zawiera jawne odnośniki — właściciel niepotwierdzony'
        if color=='red' and paths.get(node['id']):color='orange';text='Powiązanie przez publiczny graf dowodów — własność niepotwierdzona'
        matches=compare(json.loads(node['data']),criteria or {})
        out[str(node['id'])]={'color':color,'text':text,'matched_fields':matches}
    return out
