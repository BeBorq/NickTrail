import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, unquote,parse_qs,urlencode

SERVICES = json.loads(Path(__file__).with_name("services.json").read_text())
from .engineconfig import instances as engine_instances
SERVICES.update({r['host']:r['id'] for r in engine_instances().values()})
EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL = re.compile(r"https?://[^\s<>\"']+")
TEAM = {"support", "info", "contact", "hello", "admin", "office", "team", "sales", "noreply", "no-reply", "notifications", "webmaster", "privacy", "security", "abuse", "press", "jobs", "careers", "billing", "newsletter", "marketing"}


def normalize(value):
    p = urlsplit(value.strip())
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError("Wymagany publiczny adres HTTP(S), bez danych logowania")
    if p.port not in (None, 80, 443):
        raise ValueError("Niedozwolony port")
    host = p.hostname.encode("idna").decode().lower().rstrip(".")
    if any(ord(c) < 33 for c in value) or "\\" in value:
        raise ValueError("Nieprawidłowy adres")
    path = p.path.rstrip("/") or ""
    if host in ("github.com", "www.github.com"):
        host, path = "github.com", path.lower()
    return urlunsplit((p.scheme.lower(), host, path, p.query, ""))


def identify(value):
    url = normalize(value)
    p = urlsplit(url)
    parts = [unquote(x) for x in p.path.split("/") if x]
    platform = SERVICES.get(p.hostname, "Strona")
    kind = "profile"
    if platform in engine_instances():
        family=engine_instances()[platform]['engine']
        from .engineconfig import HTML_ENGINES
        if family in HTML_ENGINES:
            from .engineconfig import alias_for_url
            kind='profile' if alias_for_url(engine_instances()[platform],url) else 'page'
        else:
            prefix={'gitea':None,'gitlab':None,'discourse':'u','wordpress':'author','lemmy':'u','forgejo':None,'mastodon':None,'peertube':'accounts','mediawiki':'wiki','nodebb':'user','flarum':'u'}[family]
            kind='profile' if (len(parts)==1 and not prefix and parts[0] not in ('explore','api','login','about')) or (len(parts)==2 and prefix and parts[0]==prefix) else 'page'
            if family=='mastodon':kind='profile' if len(parts)==1 and re.fullmatch(r'@[A-Za-z0-9_]{1,63}',parts[0]) else 'page'
            if family=='mediawiki':kind='profile' if len(parts)==2 and parts[0]=='wiki' and parts[1].startswith('User:') else 'page'
    elif platform in ('PythonForum','BlenderForum','RustForum','MozillaForum','GNOMEForum','KDEForum','JuliaForum','GodotForum','ObsidianForum','HuggingFaceForum','ProcessingForum','DiscourseMeta'):
        kind='profile' if len(parts)==2 and parts[0] in ('u','users') and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}',parts[1]) else 'page'
        if kind=='profile':url='https://'+p.hostname+'/u/'+parts[1]
    elif platform in ('StackOverflow','SecuritySE','SuperUser','AskUbuntu','GameDevSE','MathSE'):
        kind='profile' if len(parts)>=2 and parts[0]=='users' and parts[1].isdigit() else 'page'
        if kind=='profile':url='https://'+p.hostname+'/users/'+str(int(parts[1]))
    elif platform in ('Lichess','ChessCom'):
        kind='profile' if len(parts)==2 and parts[0]==('@' if platform=='Lichess' else 'member') and re.fullmatch(r'[A-Za-z0-9_-]{1,63}',parts[1]) else 'page'
        if kind=='profile':url=('https://lichess.org/@/' if platform=='Lichess' else 'https://www.chess.com/member/')+parts[1].lower()
    elif platform=='HackerNews':
        values=parse_qs(p.query);alias=values.get('id',[''])[0]
        kind='profile' if p.path=='/user' and set(values)=={'id'} and len(values['id'])==1 and re.fullmatch(r'[A-Za-z0-9_-]{1,63}',alias) else 'page'
        if kind=='profile':url='https://news.ycombinator.com/user?'+urlencode({'id':alias})
    elif platform=='Keybase':
        kind='profile' if len(parts)==1 and re.fullmatch(r'[A-Za-z0-9_]{1,63}',parts[0]) and parts[0] not in ('docs','login','signup','download') else 'page'
    elif platform in ('Codewars','Modrinth','Codeforces'):
        prefix={'Codewars':'users','Modrinth':'user','Codeforces':'profile'}[platform]
        kind='profile' if len(parts)==2 and parts[0]==prefix else 'page'
    elif platform in ('RubyGems','CratesIO','Speedrun'):
        prefix={'RubyGems':'profiles','CratesIO':'users','Speedrun':'users'}[platform]
        kind='profile' if len(parts)==2 and parts[0] in ((prefix,'user') if platform=='Speedrun' else (prefix,)) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}',parts[1]) else 'page'
        if kind=='profile':url={'RubyGems':'https://rubygems.org/profiles/','CratesIO':'https://crates.io/users/','Speedrun':'https://www.speedrun.com/users/'}[platform]+parts[1]
    elif platform=='HuggingFace':
        kind='profile' if len(parts)==1 and parts[0] not in ('models','datasets','spaces','docs','login','join','settings','organizations') and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}',parts[0]) else 'page'
    elif platform=='Launchpad':
        kind='profile' if len(parts)==1 and parts[0].startswith('~') else 'page'
    elif p.hostname in ('discord.gg','discord.com','www.discord.com'):
        platform='Discord';kind='community' if p.hostname=='discord.gg' or parts and parts[0]=='invite' else 'discord'
    elif platform == "GitHub":
        if len(parts) != 1 or parts[0] in {"about", "login", "settings", "explore", "topics", "orgs", "search"}:
            kind = "project" if len(parts) >= 2 else "page"
        elif not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?',parts[0]) or '--' in parts[0]:kind='page'
        if kind=='profile':url=urlunsplit(('https','github.com',p.path.lower(),'',''))
    elif platform=='X':
        reserved={'home','explore','settings','notifications','messages','search','compose','intent','i','logout','login','share','hashtag','account','download','privacy','tos','analytics','bookmarks','communities','jobs'}
        kind='profile' if len(parts)==1 and parts[0].casefold() not in reserved and re.fullmatch(r'[A-Za-z0-9_]{1,15}',parts[0]) else 'page'
        if kind=='profile':url='https://x.com/'+parts[0].lower()
        elif len(parts)==3 and parts[:2]==['i','user'] and parts[2].isdigit():kind='profile';url='https://x.com/i/user/'+parts[2]
    elif platform=='Facebook':
        values=parse_qs(p.query);numeric=values.get('id',[])
        if p.path=='/profile.php' and len(numeric)==1 and numeric[0].isdigit():kind='profile';url='https://www.facebook.com/profile.php?id='+numeric[0]
        elif len(parts)==3 and parts[0]=='people' and parts[2].isdigit():kind='profile';url='https://www.facebook.com/profile.php?id='+parts[2]
        elif len(parts)==1 and parts[0].casefold() not in {'home','profile.php','login','logout','groups','pages','marketplace','help','settings','watch','reel','reels','share','stories','friends','gaming','events','notifications','messages','search','privacy','policies','recover','checkpoint'} and re.fullmatch(r'[A-Za-z0-9.]{3,80}',parts[0]):kind='profile';url='https://www.facebook.com/'+parts[0]
        else:kind='page'
    elif platform == "Roblox":
        kind = "profile" if len(parts) >= 2 and parts[0] == "users" and parts[1].isdigit() else "page"
        if kind == "profile": url = f"https://www.roblox.com/users/{parts[1]}/profile"
    elif platform == "Steam":
        kind = "profile" if len(parts) == 2 and parts[0] in ("id", "profiles") else "page"
    elif platform == "Bluesky":
        kind = "profile" if len(parts) == 2 and parts[0] == "profile" else "page"
    elif platform in ("Codeberg","Gitea"):
        kind="profile" if len(parts)==1 and parts[0].lower() not in {"explore","user","org","api","issues","pulls","notifications","admin","assets"} else "page"
    elif platform == "GitLab":
        kind = "profile" if len(parts) == 1 else "project" if len(parts) >= 2 else "page"
    elif p.hostname.endswith(".itch.io"):
        platform = "itch.io"
        kind = "profile" if not parts else "project"
    elif re.fullmatch(r"/@[^/]+", p.path):
        platform = "Mastodon"
    elif platform == "Twitch":
        reserved={'directory','downloads','store','p','settings','login','signup','videos','subscriptions','friends','search','about','jobs','turbo','prime','products'}
        kind='profile' if len(parts)==1 and parts[0].casefold() not in reserved and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_]{2,24}',parts[0]) else 'page'
        if kind=='profile':url='https://www.twitch.tv/'+parts[0].lower()
    elif platform == "Xbox":
        gt=parse_qs(p.query).get('gamertag',[''])
        kind='profile' if p.path.rstrip('/').endswith('/profile') and len(gt)==1 and gt[0] and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ]{0,14}',gt[0]) else 'page'
        if kind=='profile':url='https://account.xbox.com/en-us/profile?'+urlencode({'gamertag':gt[0]})
    elif platform == "Strona":
        kind = "page"
    return {"url": url, "platform": platform, "kind": kind}


def email_key(value):
    local, domain = value.rsplit("@", 1)
    return local + "@" + domain.lower()


def team_email(value):
    return value.split("@", 1)[0].lower().split("+", 1)[0] in TEAM


def classify(text, url, context="own"):
    if context != "own": return "mentions"
    # Bind a claim to the immediately preceding clause, not every URL in the bio.
    sentence = next((s for s in re.split(r'(?<=[.!?])\s+|[\n;]', text) if url in s), '')
    if not sentence:return 'links'
    prefix=sentence[:sentence.index(url)]
    prefix=re.split(r',|\b(?:and|oraz|ale|but)\b|(?=\b(?:dzięki|thanks|polecam|recommend)\b)',prefix,flags=re.I)[-1].strip().rstrip(' `*')
    if re.search(r'\b(?:cytat|quote|napisał|said|dzięki|thanks)\b',prefix,re.I):return 'mentions'
    if re.search(r"\b(?:polecam|recommend)\b", prefix, re.I): return "recommends"
    if identify(url)["kind"] == "project":
        return "claims_authorship" if re.search(r"(?:mój projekt|my project)\s*(?:to|is|:)?\s*$", prefix, re.I) else "links"
    if re.search(r"\b(?:mój|my)\s+(?:(?:nowy|new)\s+)?(?:github|profil|konto|profile|account)\s*(?:to|jest|is|:)?\s*$", prefix, re.I):
        return "claims_ownership"
    return "links"


def reference_matches(node,reference_url):
    """Compare a reference only using known platform rules or a validated API observation."""
    reference=identify(reference_url)['url']
    if node.get('kind') not in ('profile','page'):return False
    try:canonical=identify(node['url'])['url']
    except ValueError:return False
    if canonical==reference:return True
    data=json.loads(node.get('data','{}')) if isinstance(node.get('data','{}'),str) else node['data']
    # Discourse usernames are case-insensitive; generic personal-site paths are not.
    a=urlsplit(node['url']);b=urlsplit(reference)
    if data.get('public_engine')=='discourse' and data.get('id_scope')==a.hostname==b.hostname and data.get('stable_id') and not a.query and not b.query:
        expected='/u/'+str(data.get('alias',''))
        return a.path.casefold()==expected.casefold() and b.path.casefold()==expected.casefold()
    return False
