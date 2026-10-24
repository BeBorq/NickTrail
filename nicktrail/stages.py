"""Deterministic request stages; username recall comes before weak discovery."""
from .indexes import INDEXES
from .community import STACK
WEAK_SEARCH=set(INDEXES)|set(STACK)|{'Catalog'}
def phase(platform,mode):
    mode=mode.split('|')[0]
    if mode=='enrich':return 'B_ENRICH'
    if mode=='probe' or mode=='exact' and platform not in WEAK_SEARCH:return 'A_EXACT'
    if mode=='variant':return 'D_VARIANTS'
    return 'E_WEAK'
def exact_match(data,terms,platform=''):
    alias=str(data.get('alias') or '')
    values={str(t).casefold() for t in terms}
    if platform=='Bluesky' and alias.casefold().endswith('.bsky.social'):return alias.casefold() in values or alias[:-12].casefold() in values
    if platform=='HackerNews':return alias in terms
    return bool(alias and alias.casefold() in values)
def task_order(t):
    return ({'A_EXACT':0,'B_ENRICH':1,'D_VARIANTS':3,'E_WEAK':4}[phase(t['platform'],t['mode'])],2 if t['platform']=='Extended' else 1 if t['platform']=='Free' else 0,t.get('ordinal',0))
def next_task(tasks):
    return min(tasks,key=task_order) if tasks else None
