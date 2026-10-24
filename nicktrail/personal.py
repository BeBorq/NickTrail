"""Small robots-aware identity-page crawl; never a general domain crawler."""
import json,re,http.client
from urllib.parse import urlsplit,urljoin
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree as ET
from .identity import normalize
from .engine import scan
IDENTITY_PATHS={'about','about-me','aboutme','contact','contact-me','links','social','socials','bio','me','o-mnie','kontakt','author','profile'}

def origin(url):
    p=urlsplit(normalize(url));return p.scheme+'://'+p.netloc

def relevant(url,base):
    try:
        p=urlsplit(normalize(url));parts=p.path.strip('/').lower().split('/')
        return origin(url)==origin(base) and not p.query and len(parts)<=2 and any(s.removesuffix('.html') in IDENTITY_PATHS for s in parts)
    except ValueError:return False

def paths(text,base):
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():return []
    try:root=ET.fromstring(text)
    except ET.ParseError:return []
    # Sitemap indexes are deliberately not recursively expanded.
    if root.tag.split('}')[-1]!='urlset':return []
    return list(dict.fromkeys(e.text for e in list(root.iter())[:1000] if e.tag.split('}')[-1]=='loc' and e.text and relevant(e.text,base)))[:10]

def crawl(store,project,sites,client,stopped=lambda:False):
    from .network import Limit
    from .engine import record
    from .publicprofile import read
    report=[];origins=set()
    def fetch(url):
        try:return client.get(url)
        except (OSError,ValueError,http.client.HTTPException) as error:return {'state':'error','detail':type(error).__name__}
    for id in sites[:2]:
        node=store.node(id);base=node['url']
        if node['project']!=project or node['platform']!='Strona' or node['state']!='found' or node['ownership']=='not_mine':continue
        host=origin(base)
        if host in origins or stopped():continue
        origins.add(host)
        robots=fetch(host+'/robots.txt');policy=RobotFileParser();policy.set_url(host+'/robots.txt')
        if robots['state']=='found':policy.parse(robots['text'].splitlines())
        elif robots['state']=='not_found':policy.parse([])
        else:report.append({'site':id,'state':'blocked','detail':'Nie odczytano robots.txt; podstrony odłożone'});continue
        def allowed(url):return relevant(url,base) and policy.can_fetch('NickTrail',url)
        candidates=[]
        for edge in store.rows("SELECT target FROM evidence WHERE source=? AND current=1 AND decision!='rejected' AND relation IN ('links','claims_ownership') AND context='own' AND method IN ('parser','rendered_public_page')",(id,)):
            target=store.node(edge['target'])
            if target['ownership']!='not_mine' and allowed(target['url']):candidates.append(target['url'])
        if len(candidates)<3 and policy.can_fetch('NickTrail',host+'/sitemap.xml'):
            sitemap=fetch(host+'/sitemap.xml')
            if sitemap['state']=='found':candidates+=paths(sitemap['text'],base)
        for url in list(dict.fromkeys(candidates))[:3]:
            if stopped():break
            if not allowed(url):continue
            target=store.add(project,url,seed=False,depth=node['depth']+1)
            if store.node(target)['ownership']=='not_mine':continue
            # The sitemap is navigation evidence, never an identity assertion.
            existing=store.rows("SELECT 1 FROM evidence WHERE source=? AND target=? AND current=1",(id,target))
            if not existing:record(store,node,[{'url':url,'relation':'links','location':'personal.identity-page','snippet':'Publiczna podstrona o osobie/kontakcie: '+url,'source_url':host+'/sitemap.xml'}])
            offset=client.count
            class SameOrigin:
                @property
                def count(self):return client.count-offset
                def get(self,address,**kwargs):
                    result=client.get(address,**kwargs)
                    if result.get('url') and origin(result['url'])!=host:return {'state':'blocked','detail':'Podstrona przeniosła się poza dozwoloną witrynę'}
                    return result
                def profile_get(self,address):
                    # Keeps the client's robots.txt check (incl. Crawl-delay) for the subpage itself.
                    result=getattr(client,'profile_get',client.get)(address)
                    if result.get('url') and origin(result['url'])!=host:return {'state':'blocked','detail':'Podstrona przeniosła się poza dozwoloną witrynę'}
                    return result
            scan_id=scan(store,project,{'profiles':1,'pages':1},targets=[target],client=SameOrigin(),stopped=stopped)
            observed=store.rows('SELECT state,detail FROM observations WHERE scan=? AND node=?',(scan_id,target))
            report.append({'site':id,'node':target,'scan':scan_id,'state':observed[0]['state'] if observed else 'pending','url':url})
    return report
