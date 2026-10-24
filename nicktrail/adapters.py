import json
import re
import html
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, quote
from .identity import URL, EMAIL, classify, identify, normalize


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts, self.links = [], []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"): self.skip += 1
        if self.skip: return
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"): self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"): self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip: self.parts.append(data)


def capabilities(platform):
    from .providers import REGISTRY
    provider=REGISTRY.get(platform)
    supported = bool(provider and provider.scope in ('public_api','platform_search')) or platform in ('GitHub','Roblox','GitLab','Bluesky','DEV','Strona','HackerOne','Codeberg','Gitea','PythonForum','BlenderForum')
    return {"recognizes": True, "existence": supported, "profile": supported, "posts": False,'requires_configuration':platform in ('Steam','Mastodon','X')}


def extract(text, base, location="bio", context="own", links=()):
    def clean(raw):
        raw=raw.rstrip('.,;`*')
        for opening,closing in (('(',')'),('[',']')):
            while raw.endswith(closing) and raw.count(closing)>raw.count(opening):raw=raw[:-1]
        return raw.rstrip('.,;`*')
    # Parse descriptions containing HTML before extracting text; script bodies never become evidence.
    if re.search(r'<(?:a|p|div|script|br)\b',text,re.I):
        from .publicprofile import ProfileHTML
        page=ProfileHTML();page.feed(text);page.close()
        links=tuple(links)+tuple(page.links)
        text='\n'.join(page.parts)
    text=html.unescape(text)
    bare=re.findall(r'(?<![\w@/:.-])(?:www\.)?(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,24}/[^\s<>"\x27]+',text)
    domain=r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,24}'
    # Root domains need an explicit www prefix or a website label; prose/file names are not links.
    roots=re.findall(r'(?<![\w@/:.-])www\.'+domain+r'(?![\w@/?#:-]|\.[A-Za-z0-9])',text)
    roots+=re.findall(r'(?i)\b(?:website|homepage|portfolio|strona(?:\s+www)?|witryna)\s*[:=]\s*('+domain+r')(?![\w@/?#:-]|\.[A-Za-z0-9])',text)
    bare+=roots
    out = []
    for raw in list(URL.findall(text)) + ['https://'+u for u in bare] + list(links):
        if raw.startswith("mailto:"): continue
        try:
            url = normalize(urljoin(base, clean(raw)))
            if url == normalize(base): continue
            # General websites only expose off-site links or a small about/contact scope.
            if urlsplit(url).hostname == urlsplit(base).hostname and identify(base)["platform"] == "Strona":
                from .personal import relevant
                if not relevant(url,base):continue
            reference=clean(raw) if raw.startswith(('http://','https://')) else url
            out.append({"url": url, "relation": classify(text, reference, context), "snippet": next((s.strip()[:500] for s in text.splitlines() if raw in s), raw[:500]), "location": location})
        except ValueError: continue
    for email in EMAIL.findall(text):
        out.append({"email": email, "relation": "public_contact_occurrence", "snippet": next((s.strip()[:500] for s in text.splitlines() if email in s), email), "location": location})
    from .labelprofiles import extract_labels
    out.extend(extract_labels(text,location,context))
    for match in re.finditer(r'(?im)\bdiscord\s*[:=]\s*([A-Za-z0-9_.]{2,32}(?:#[0-9]{4})?)(?![A-Za-z0-9_.:/])',text):
        out.append({'discord':match.group(1),'relation':'mentions','snippet':match.group(0),'location':location+'.discord'})
    unique={}
    for item in out:
        unique[(item.get('url',item.get('email',item.get('discord'))),item['relation'],item['location'])]=item
    return list(unique.values())[:100]


def public_account_fields(data):
    import re
    out=[]
    for field,prefix in (('github_username','https://github.com/'),('twitter_username','https://x.com/')):
        value=data.get(field)
        if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,39}',value):
            out.append({'url':prefix+value,'relation':'links','location':field,'snippet':field+': '+value})
    return out


def read(node, client):
    from .forums import HOSTS
    from .engineconfig import instances
    if node['platform'] in instances():
        from .engines import read as engine_read
        return engine_read(node,client)
    recorded=json.loads(node.get('data','{}'))
    if recorded.get('public_engine') and recorded.get('id_scope')==urlsplit(node['url']).hostname:
        from .publicengines import lookup as public_engine_lookup,SUPPORTED
        if recorded['public_engine'] in SUPPORTED and isinstance(recorded.get('alias'),str):
            result=public_engine_lookup(recorded['public_engine'],recorded['id_scope'],recorded['alias'].replace(' ','_'),client);matches=result.get('matches',[])
            return {'state':'found','canonical_url':matches[0]['url'],'data':matches[0]['data'],'evidence':matches[0].get('evidence',[])} if matches else {k:v for k,v in result.items() if k!='matches'}
    from .native17 import SITES as NATIVE17_SITES
    if node['platform'] in NATIVE17_SITES:
        from .native17 import read as native_read17
        return native_read17(node,client)
    from .native15 import SITES as NATIVE_SITES
    if node['platform'] in NATIVE_SITES:
        from .native15 import read as native_read
        return native_read(node,client)
    from .community import STACK
    if node['platform'] in ('Keybase','HackerNews') and not json.loads(node.get('data','{}')).get('public_probe'):
        from .identityapis import read as identity_read
        return identity_read(node,client)
    if node['platform'] in STACK or node['platform'] in ('Lichess','ChessCom'):
        from .community import read as community_read
        return community_read(node,client)
    if node['platform'] in HOSTS:
        from .forums import read as forum_read
        return forum_read(node,client)
    previous=json.loads(node.get('data','{}'))
    if previous.get('public_probe'):
        from .freeprofiles import lookup as probe_lookup,TEMPLATES
        service=previous['public_probe'];alias=previous.get('alias')
        if service in TEMPLATES and isinstance(alias,str) and normalize(TEMPLATES[service].format(nick=quote(alias,safe='')))==normalize(node['url']):
            probe=probe_lookup(service+':'+alias,client)
            matches=probe.get('matches',[])
            if probe['state']=='found' and matches:return {'state':'found','data':matches[0]['data'],'evidence':matches[0].get('evidence',[]),'canonical_url':matches[0]['url'],'detail':probe.get('detail','')}
            return {'state':probe['state'],'detail':probe.get('detail','')}

    if node["platform"] in ("Codeberg","Gitea"):
        from .forge import read as forge_read
        return forge_read(node,client)
    p = urlsplit(node["url"])
    platform = node["platform"]
    if platform=='X':
        from .xprofile import read as read_x
        return read_x(node,client)
    if platform in ('Steam','Mastodon') and node['kind']=='profile':
        from .keyed import read_keyed
        return read_keyed(node,client)
    if platform in ('Twitch','Xbox') and node['kind']=='profile':
        from .gaming import read_gaming
        return read_gaming(node,client)
    if platform in ('GitLab','Bluesky','DEV') and node['kind'] == 'profile':
        return read_extra(node, client)
    if node['kind'] in ('profile','page') and platform not in ('GitHub','Roblox'):
        from .publicprofile import read as read_public
        return read_public(node,client)
    if node["kind"] not in ("profile", "page") or platform not in ("GitHub", "Roblox", "Strona"):
        return {"state": "unsupported", "detail": "Rozpoznawanie i ręczna ocena; brak odczytu"}
    if platform == "GitHub" and node["kind"] != "profile":
        return {"state": "unsupported", "detail": "Repozytorium nie jest profilem właściciela"}
    previous=json.loads(node.get('data','{}'))
    github_id=previous.get('stable_id','')
    github_endpoint='https://api.github.com/user/'+str(github_id) if str(github_id).isdigit() else 'https://api.github.com/users/'+p.path.strip('/')
    endpoint = github_endpoint if platform == "GitHub" else "https://users.roblox.com/v1/users/" + p.path.split("/")[2] if platform == "Roblox" else node["url"]
    result = client.get(endpoint)
    if result["state"] != "found": return result
    if platform in ("GitHub", "Roblox"):
        data = json.loads(result["text"])
        if not isinstance(data, dict) or type(data.get('id')) is not int or data['id']<=0: raise ValueError("Nieprawidłowa odpowiedź API")
        fields = ("bio", "blog", "email") if platform == "GitHub" else ("description",)
        evidence = [e for field in fields for e in extract(str(data.get(field) or ""), node["url"], field)]
        evidence += public_account_fields(data)
        if platform == "GitHub" and data.get("blog"):
            blog = data["blog"]
            if "://" not in blog and "." in blog: evidence += extract("https://" + blog, node["url"], "blog")
        canonical=node['url']
        if platform=='GitHub' and isinstance(data.get('login'),str):
            import re
            if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}',data['login']):
                canonical='https://github.com/'+data['login'].lower()
                # One extra API call; GitHub allows 60 unauthenticated calls an hour, so
                # only the user's own accounts spend it (their declared accounts are the
                # best route to forgotten ones).
                if node.get('ownership')=='mine':evidence += github_social_accounts(data['login'],node['url'],client)
        from .accountentities import api_fields
        return {"state": "found", 'canonical_url':canonical,"data": {"avatar_url":data.get('avatar_url'),"stable_id": str(data["id"]), "alias": data.get("login", data.get("name")), "bio":data.get("bio",data.get("description")), "display": data.get("displayName", data.get("name")), "declared_location": data.get("location")}|(api_fields(data) if platform=='GitHub' else {}), "evidence": evidence}
    page = Page()
    page.feed(result["text"])
    text = "\n".join(page.parts)
    return {"state": "found", "data": {"title": text.strip()[:120]}, "evidence": extract(text, result.get("url", node["url"]), "page", links=page.links)}


def github_social_accounts(login,source_url,client):
    """Social accounts the owner added to their own GitHub profile.

    GitHub lists them on a public endpoint; they are the owner's declaration,
    the same strength as the website field.  A failed or empty response never
    breaks the profile read: it only means no extra declared accounts.
    """
    try:
        response=client.get('https://api.github.com/users/'+quote(login,safe='')+'/social_accounts')
    except (OSError,ValueError):
        return []
    if not isinstance(response,dict) or response.get('state')!='found':return []
    try:items=json.loads(response['text'])
    except (ValueError,TypeError,KeyError):return []
    if not isinstance(items,list):return []
    out=[]
    for item in items[:10]:
        if not isinstance(item,dict) or not isinstance(item.get('url'),str):continue
        try:url=identify(item['url'])['url']
        except (ValueError,AttributeError):continue
        if urlsplit(url).scheme not in ('http','https'):continue
        provider=str(item.get('provider') or 'generic')[:40]
        out.append({'url':url,'relation':'links','location':'github.social_accounts',
                    'snippet':'GitHub: konto dodane przez właściciela profilu w sekcji kont społecznościowych ('+provider+')'})
    return out


# Handles under these hosts are provider subdomains, not the account's own domain.
BLUESKY_PROVIDER_SUFFIXES=('bsky.social','bsky.app','bsky.network','blacksky.app','handle.invalid')

def bluesky_domain_handle(handle):
    """A custom Bluesky handle is a domain the account linked bidirectionally.

    The public AppView shows such a handle only after atproto handle
    verification (DNS TXT _atproto or /.well-known/atproto-did); otherwise it
    reports handle.invalid.  NickTrail does not re-check DNS itself.
    """
    if not isinstance(handle,str):return []
    host=handle.strip().lower().rstrip('.')
    if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',host):return []
    if any(host==s or host.endswith('.'+s) for s in BLUESKY_PROVIDER_SUFFIXES):return []
    try:url=normalize('https://'+host)
    except ValueError:return []
    return [{'url':url,'relation':'links','location':'bluesky.domain_handle','snippet':'Bluesky handle: '+host+' (weryfikacja domeny wg AppView; NickTrail nie sprawdza DNS)'}]


def read_extra(node, client):
    platform = node['platform']
    username = urlsplit(node['url']).path.strip('/').split('/')[-1]
    stable=json.loads(node.get('data','{}')).get('stable_id','')
    if platform=='GitLab':endpoint='https://gitlab.com/api/v4/users/'+str(stable) if str(stable).isdigit() else 'https://gitlab.com/api/v4/users?username='+quote(username,safe='')
    elif platform=='Bluesky':endpoint='https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor='+quote(stable or username,safe='')
    else:endpoint='https://dev.to/api/users/'+str(stable) if str(stable).isdigit() else 'https://dev.to/api/users/by_username?url='+quote(username,safe='')
    result = client.get(endpoint)
    if result['state'] != 'found': return result
    data = json.loads(result['text'])
    if platform == 'GitLab' and not str(stable).isdigit():
        if not isinstance(data,list): raise ValueError('Nieprawidłowa lista GitLab')
        data = next((d for d in data if isinstance(d,dict) and str(d.get('username','')).lower()==username.lower()), None)
        if data is None: return {'state':'not_found','detail':'Brak dokładnego nicku w odpowiedzi API'}
    if not isinstance(data,dict):raise ValueError('Nieprawidłowy profil API')
    if platform=='Bluesky':
        if not isinstance(data.get('did'),str) or not data['did'].startswith('did:') or any(c.isspace() for c in data['did']):raise ValueError('Nieprawidłowy DID')
    elif type(data.get('id')) is not int or data['id']<=0:raise ValueError('Nieprawidłowy identyfikator profilu API')
    fields = ('description',) if platform=='Bluesky' else ('bio','website_url','public_email','summary')
    evidence = [e for field in fields for e in extract(str(data.get(field) or ''), node['url'], field)]
    evidence += public_account_fields(data)
    canonical=node['url']
    new_alias=data.get('handle') if platform=='Bluesky' else data.get('username')
    import re
    if isinstance(new_alias,str) and re.fullmatch(r'[A-Za-z0-9_.-]+',new_alias):
        canonical={'GitLab':'https://gitlab.com/','DEV':'https://dev.to/','Bluesky':'https://bsky.app/profile/'}[platform]+new_alias
    if platform=='Bluesky':evidence+=bluesky_domain_handle(new_alias)
    return {'state':'found','canonical_url':canonical,'data':{'stable_id':str(data.get('did',data.get('id'))),
            'avatar_url':data.get('avatar') or data.get('avatar_url') or data.get('profile_image'),'alias':data.get('handle',data.get('username')), 'display':data.get('displayName',data.get('name')),
            'declared_location':data.get('location')}, 'evidence':evidence}
