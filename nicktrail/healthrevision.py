"""Conservative detector revision stamps. Never waive health cache/cooldowns."""
import hashlib,json
from pathlib import Path
from functools import lru_cache

@lru_cache(maxsize=256)
def _digest_files(stamps):
 h=hashlib.sha256()
 for name,_,_ in stamps:h.update(Path(name).read_bytes())
 return h.hexdigest()

def fingerprint(service):
 family,id=service.split(':',1)
 if family in ('Free','Extended'):
  from .servicecatalog import services
  from .extended import services as imported
  row=next((r for r in (services() if family=='Free' else imported()) if r['id']==id),{})
  contract={k:v for k,v in row.items() if k not in ('validation','controls')}
  modules=('freeprofiles','publicengines','adapters','publicprofile','network','apierrors','labelprofiles')
 else:
  from .providers import REGISTRY
  provider=REGISTRY[id];contract={'id':id,'handler':provider.handler,'scope':provider.scope,'exact':provider.supports_exact,'username_pattern':provider.username_pattern}
  from .engineconfig import instances
  if id in instances():contract['instance']=instances()[id]
  modules=tuple(dict.fromkeys((provider.handler.split(':')[0].split('.')[-1],'adapters','identity','network','apierrors','labelprofiles','native15','native17','identityapis','engines','publicengines')))
  # Built-in dispatch delegates to these modules; their code is part of the
  # observed detector even though it is not named in Provider.handler.
  if id in ('Codeberg','Gitea'):modules+=('forge',)
  if id in ('Steam','Mastodon'):modules+=('keyed',)
  if provider.handler.startswith('nicktrail.engines:'):modules+=('freeprofiles','publicprofile','engineconfig')
 root=Path(__file__).parent
 stamps=tuple((str(p),p.stat().st_mtime_ns,p.stat().st_size) for module in modules if (p:=root/(module+'.py')).is_file())
 return hashlib.sha256((json.dumps(contract,sort_keys=True,ensure_ascii=False)+_digest_files(stamps)).encode()).hexdigest()
