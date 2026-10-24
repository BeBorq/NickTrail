"""Deterministic overview of how candidate accounts connect to a reference account."""


def cluster_overview(packet):
    """Deterministic evidence baseline; semantic similarity is not an identity label."""
    edges={e['id']:e for e in packet['evidence']};rows=[]
    for profile in packet['profiles']:
        if profile['id']==packet['reference']:continue
        claims=[e for e in edges.values() if e['relation']=='claims_ownership' and e['current'] and e['decision']!='rejected' and e.get('method') in ('parser','rendered_public_page') and e.get('context','own')=='own' and {e['source'],e['target']}=={packet['reference'],profile['id']}]
        directions={(e['source'],e['target']) for e in claims}
        reciprocal=(packet['reference'],profile['id']) in directions and (profile['id'],packet['reference']) in directions and profile.get('read_state')=='found'
        support=sorted({id for path in profile.get('identity_paths',[]) for id in path['evidence'] if id in edges}|({e['id'] for e in claims} if reciprocal else set()))
        relevant=[e for e in edges.values() if profile['id'] in (e['source'],e['target'])]
        rejected=[e['id'] for e in relevant if e['decision']=='rejected']
        historical=[e['id'] for e in relevant if not e['current']]
        groups=sorted({edges[id].get('independence_group','unknown') for id in support})
        missing=[]
        if not support:missing.append('No current supported path to the selected cluster')
        if len(groups)<2:missing.append('Fewer than two independent source groups')
        if profile['user_label']=='unknown':missing.append('No explicit user ownership label')
        explicit=[edges[id] for id in support if edges[id]['relation']=='claims_ownership' and edges[id]['current'] and edges[id]['decision']!='rejected']
        classification='LIKELY_SAME' if reciprocal and len({e.get('independence_group') for e in explicit}-{None,'unknown'})>=2 else 'AMBIGUOUS' if support else 'INSUFFICIENT_EVIDENCE'
        if profile['user_label']!='unknown':classification='INSUFFICIENT_EVIDENCE'
        from .accountentities import non_person_type
        reference=next(p for p in packet['profiles'] if p['id']==packet['reference'])
        if non_person_type(profile.get('entity_type')) or non_person_type(reference.get('entity_type')):classification='INSUFFICIENT_EVIDENCE'
        rows.append({'candidate':profile['id'],'classification':classification,'supporting':support,'conflicting':rejected,'historical_or_uncertain':historical,'independence_groups':groups,'missing_evidence':missing,'effective_user_label':profile['user_label'],'basis':'deterministic normalized evidence; not an LLM conclusion','identity_confirmed':False,'advisory_only':True})
    return rows
