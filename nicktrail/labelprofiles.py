"""Conservative bio field declarations, not free-text username guessing."""
import re
from .identity import identify

def extract_labels(text,location,context='own'):
 out=[]
 # A label must occupy its entire clause. Prose, quotations and a third-party
 # prefix therefore cannot silently become the profile author's declaration.
 for clause in re.split(r'[\n;|]',text[:100000])[:200]:
  m=re.fullmatch(r'\s*(?:[-*•]\s+)?(?:(?:my|mój)\s+)?(github|twitter|twitter/x|x|steam)\s*[:=]\s*(@?[A-Za-z0-9_.-]{1,64})\s*',clause,re.I)
  if not m:continue
  label,alias=m.groups();label=label.lower();alias=alias.removeprefix('@')
  if label=='github':
   if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?',alias) or '--' in alias:continue
   url='https://github.com/'+alias;method='github'
  elif label=='steam':
   if not re.fullmatch(r'[A-Za-z0-9_-]{2,32}',alias):continue
   url='https://steamcommunity.com/'+('profiles/' if re.fullmatch(r'[0-9]{17}',alias) else 'id/')+alias;method='steam'
  else:
   if not re.fullmatch(r'[A-Za-z0-9_]{1,15}',alias):continue
   url='https://x.com/'+alias;method='x'
  node=identify(url)
  if node['kind']!='profile':continue
  out.append({'url':node['url'],'relation':'links' if context=='own' else 'mentions','snippet':clause.strip()[:500],'location':location+'.label.'+method})
 return out[:50]
