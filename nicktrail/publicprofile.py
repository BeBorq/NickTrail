"""Public profile content only: no arbitrary script strings or navigation links."""
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit
from .identity import normalize,EMAIL

class ProfileHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack=[];self.parts=[];self.links=[];self.meta=[];self.structured=[];self.script=None;self.identity_links=[];self.contact_links=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='script':self.script=[] if attrs.get('type','').lower()=='application/ld+json' else None
        if tag not in ('meta','link','img','input','br','hr','source','area','base','embed','wbr'):self.stack.append(tag)
        # Explicit identity semantics can live in a header/footer, unlike ordinary navigation.
        if tag in ('a','link') and attrs.get('href') and not any(t in self.stack for t in ('script','style','noscript')):
            rel=set(attrs.get('rel','').lower().split());classes=set(attrs.get('class','').split())
            if 'me' in rel:self.identity_links.append((attrs['href'],'html.rel-me'))
            elif 'author' in rel:self.identity_links.append((attrs['href'],'html.rel-author'))
            elif 'u-url' in classes:self.identity_links.append((attrs['href'],'microformat.u-url'))
            if attrs['href'].lower().startswith('mailto:'):self.contact_links.append(attrs['href'])
        if self.blocked():return
        if tag=='a' and attrs.get('href'):self.links.append(attrs['href'])
        if tag=='meta' and (attrs.get('name')=='description' or attrs.get('property')=='og:description'):self.meta.append(attrs.get('content',''))
    def handle_endtag(self,tag):
        if tag=='script' and self.script is not None:
            try:self.structured.append(json.loads(''.join(self.script)))
            except (ValueError,RecursionError):pass
            self.script=None
        if tag in self.stack:self.stack=self.stack[:len(self.stack)-1-self.stack[::-1].index(tag)]
    def blocked(self):return any(t in self.stack for t in ('script','style','noscript','nav','footer','header'))
    def handle_data(self,data):
        if self.stack and self.stack[-1]=='script' and self.script is not None:self.script.append(data)
        if not self.blocked():self.parts.append(data)
    def persons(self,base):
        found=[];remaining=1000
        def matches(value):
            if isinstance(value,list):return any(matches(v) for v in value[:20])
            if isinstance(value,dict):value=value.get('@id')
            if not isinstance(value,str):return False
            from urllib.parse import urljoin
            try:return normalize(urljoin(base,value))==normalize(base)
            except ValueError:return False
        def visit(item,depth=0,associated=False):
            nonlocal remaining
            remaining-=1
            if depth>6 or remaining<0:return
            if isinstance(item,list):
                for child in item[:100]:visit(child,depth+1,associated)
            elif isinstance(item,dict):
                kind=item.get('@type',[]);kinds=[kind] if isinstance(kind,str) else kind if isinstance(kind,list) else []
                if 'Person' in kinds and (matches(item.get('url')) or associated):found.append(item)
                if '@graph' in item:visit(item['@graph'],depth+1)
                own_page='ProfilePage' in kinds and (matches(item.get('url')) or matches(item.get('@id')))
                if own_page and 'mainEntity' in item:visit(item['mainEntity'],depth+1,True)
        for data in self.structured:visit(data)
        return found[:100]

    def same_as(self,base):
        found=[]
        for person in self.persons(base):
            values=person.get('sameAs',[]);values=[values] if isinstance(values,(str,dict)) else values if isinstance(values,list) else []
            for value in values[:100]:
                if isinstance(value,dict):value=value.get('@id')
                if isinstance(value,str):found.append(value)
        return list(dict.fromkeys(found))[:100]

    def identity_evidence(self,base):
        from .adapters import extract
        from urllib.parse import unquote,urlsplit
        evidence=[]
        for href,location in self.identity_links[:50]:
            evidence+=extract('',base,location,links=[href])
        for href in self.contact_links[:30]:
            address=unquote(urlsplit(href).path)
            # Mail subject/body are not contact evidence; ignore multiple recipients.
            if EMAIL.fullmatch(address):
                evidence+=extract(address,base,'html.mailto')
        return evidence[:100]

    def person_evidence(self,base):
        from .adapters import extract
        evidence=[]
        for url in self.same_as(base):evidence+=extract(url,base,'jsonld.sameAs')
        for person in self.persons(base):
            # A description belonging to the matched Person is profile text, not script/navigation.
            if isinstance(person.get('description'),str):
                evidence+=extract(person['description'][:10000],base,'jsonld.person.description')
            for field in ('url','email'):
                values=person.get(field,[]);values=[values] if isinstance(values,(str,dict)) else values if isinstance(values,list) else []
                for value in values[:20]:
                    if isinstance(value,dict):value=value.get('@id')
                    if isinstance(value,str):evidence+=extract(value,base,'jsonld.person.'+field)
        return evidence[:100]


def hub_content(page,visible,base):
    from urllib.parse import urljoin
    p=urlsplit(base);host=(p.hostname or '').casefold()
    segments=[s for s in p.path.split('/') if s]
    handle=(segments[-1] if segments else host.split('.')[0]).lstrip('@')
    if len(handle)<3 or not re.search(r'(?<![\w-])@?'+re.escape(handle)+r'(?![\w-])',visible,re.I):return False
    hosts=set()
    for href in page.links:
        try:target=urlsplit(normalize(urljoin(base,href)))
        except ValueError:continue
        if target.hostname and target.hostname.casefold()!=host:hosts.add(target.hostname.casefold())
    return bool(hosts)

def read(node,client):
    from .adapters import extract,public_account_fields
    result=(getattr(client,'profile_get',None) or client.get)(node['url'])
    if result['state']!='found':return result
    text=result['text'];base=node['url']
    from .publicengines import observed_payload
    alias=urlsplit(base).path.rstrip('/').split('/')[-1]
    negotiated=observed_payload(base,alias,result)
    if negotiated is not None:
        matches=negotiated.get('matches',[])
        return {'state':'found','canonical_url':matches[0]['url'],'data':matches[0]['data'],'evidence':matches[0].get('evidence',[])} if matches else {k:v for k,v in negotiated.items() if k!='matches'}
    if node['platform']=='HackerOne' and text.lstrip().startswith('{'):
        data=json.loads(text)
        if not isinstance(data,dict) or type(data.get('id')) is not int or data['id']<=0 or not isinstance(data.get('username'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,63}',data['username']):raise ValueError('Nieprawidłowy profil HackerOne')
        canonical='https://hackerone.com/'+data['username']
        if normalize(base)!=normalize(canonical):raise ValueError('HackerOne zwrócił inny profil niż żądany; wymagana ocena adresu')
        evidence=extract(str(data.get('bio') or ''),base,'bio')+extract(str(data.get('website') or ''),base,'website')+public_account_fields(data)
        return {'state':'found','canonical_url':canonical,'data':{'avatar_url':(data.get('profile_picture_urls') or {}).get('small'),'stable_id':str(data['id']),'alias':data['username'],'display':data.get('name'),'declared_location':data.get('location')},'evidence':evidence}
    if text.lstrip().startswith(('{','[')):
        return {'state':'unsupported','detail':'Nierozpoznany schemat JSON profilu. Adresy techniczne nie są importowane jako odnośniki konta.'}
    page=ProfileHTML();page.feed(text);page.close()
    visible='\n'.join(p.strip() for p in page.parts if p.strip())
    shell=visible.casefold()
    persons=page.persons(base)
    challenge=any(w in shell for w in ('just a moment...','verify you are human'))
    shell_only=len(visible)<60 or ('javascript' in shell and any(w in shell for w in ('enable javascript','javascript is disabled','requires javascript')))
    # Link-in-bio pages are short by design.  They are content, not an empty
    # shell, when the page itself names the requested handle and links off-site.
    if shell_only and hub_content(page,visible,base):shell_only=False
    if challenge or (shell_only and not persons):
        return {'state':'blocked','detail':'Strona nie udostępniła treści profilu: JavaScript, logowanie lub strona ochronna. Nie oznacza braku odnośników.'}
    evidence=extract(visible,base,'page',links=page.links)
    for description in page.meta:evidence+=extract(description,base,'meta.description')
    evidence+=page.person_evidence(base)+page.identity_evidence(base)
    fields={'title':visible[:180]}
    if persons:
        person=persons[0]
        if isinstance(person.get('name'),str):fields['display']=person['name'][:300]
        if isinstance(person.get('description'),str):fields['bio']=person['description'][:10000]
        image=person.get('image')
        if isinstance(image,dict):image=image.get('contentUrl') or image.get('url')
        if isinstance(image,str) and urlsplit(image).scheme in ('http','https') and urlsplit(image).hostname:fields['avatar_url']=image[:2000]
        birth=person.get('birthDate')
        if isinstance(birth,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',birth):
            import datetime
            try:
                if datetime.date.fromisoformat(birth)<=datetime.date.today():fields['declared_birth_date']=birth
            except ValueError:pass
    return {'state':'found','data_complete':False,'data':fields,'evidence':evidence,'detail':'Publiczny HTML; odnośniki są poszlakami, bez potwierdzenia właściciela.'}


