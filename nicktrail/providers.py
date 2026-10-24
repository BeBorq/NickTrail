"""Provider contract: public APIs, no-key probes and optional search indexes.

Source IDs stay compatible with persisted searches. No provider owns the scheduler.
"""
from dataclasses import dataclass
import importlib,os,re
from .identity import normalize

@dataclass(frozen=True)
class Provider:
    id:str
    handler:str
    scope:str
    context_search:bool=False
    required_env:tuple=()
    exact_lookup:bool=False
    username_pattern:str|None=None
    @property
    def supports_exact(self):return self.scope=='public_api' or self.exact_lookup
    def valid_username(self,value):return self.username_pattern is None or re.fullmatch(self.username_pattern,value) is not None
    def available(self):return all(os.environ.get(k) for k in self.required_env)
    def lookup(self,term,client):
        module,function=self.handler.split(':');handler=getattr(importlib.import_module(module),function)
        result=handler(self.id,term,client) if function in ('_lookup_builtin','lookup_platform') else handler(term,client)
        return validate(result)

REGISTRY={p:Provider(p,'nicktrail.search:_lookup_builtin','public_api',p in ('GitHub','GitLab','Roblox','Bluesky')) for p in ('GitHub','GitLab','Roblox','Bluesky','DEV','Codeberg','Gitea')}
REGISTRY.update({
 'SearXNG':Provider('SearXNG','nicktrail.indexes:searx_lookup','web_index',True,('NICKTRAIL_SEARXNG_URL',)),
 'Mojeek':Provider('Mojeek','nicktrail.indexes:mojeek_lookup','web_index',True,('NICKTRAIL_MOJEEK_KEY',)),
 'GoogleCSE':Provider('GoogleCSE','nicktrail.indexes:google_lookup','web_index',True,('NICKTRAIL_GOOGLE_KEY','NICKTRAIL_GOOGLE_CX')),
 'PythonForum':Provider('PythonForum','nicktrail.forums:python_lookup','public_api'),
 'BlenderForum':Provider('BlenderForum','nicktrail.forums:blender_lookup','public_api'),
 'Free':Provider('Free','nicktrail.freeprofiles:lookup','username_probe'),
 'Web':Provider('Web','nicktrail.websearch:lookup','web_index',True,('NICKTRAIL_BRAVE_KEY',)),
 'Catalog':Provider('Catalog','nicktrail.catalog:lookup','domain_index',True,('NICKTRAIL_BRAVE_KEY',)),
 'Steam':Provider('Steam','nicktrail.search:_lookup_builtin','public_api',False,('NICKTRAIL_STEAM_KEY',)),
 'Mastodon':Provider('Mastodon','nicktrail.search:_lookup_builtin','public_api',False,('NICKTRAIL_MASTODON_TOKEN','NICKTRAIL_MASTODON_INSTANCE')),
 'Twitch':Provider('Twitch','nicktrail.search:_lookup_builtin','public_api',False,('NICKTRAIL_TWITCH_CLIENT_ID','NICKTRAIL_TWITCH_TOKEN')),
 'Xbox':Provider('Xbox','nicktrail.search:_lookup_builtin','public_api',False,('NICKTRAIL_XBOX_KEY',)),
})

def validate(result):
    if not isinstance(result,dict) or result.get('state') not in ('found','not_found','partial','blocked','error','unsupported','unverified'):raise ValueError('Nieprawidłowy stan dostawcy wyszukiwania')
    matches=result.get('matches',[])
    if not isinstance(matches,list) or len(matches)>100:raise ValueError('Nieprawidłowa lista wyników dostawcy')
    for match in matches:
        if not isinstance(match,dict) or not isinstance(match.get('url'),str) or not isinstance(match.get('data',{}),dict) or not isinstance(match.get('evidence',[]),list):raise ValueError('Nieprawidłowy kandydat dostawcy')
        normalize(match['url'])
    return result

def lookup(id,term,client):
    provider=REGISTRY.get(id)
    if provider is None:raise ValueError('Nieznany dostawca wyszukiwania')
    if not provider.available():return {'state':'unsupported','matches':[],'detail':'Dostawca '+id+' wymaga konfiguracji; inne źródła działają niezależnie.'}
    return provider.lookup(term,client)

def describe():
    return [{'id':p.id,'scope':p.scope,'context_search':p.context_search,'available':bool(p.available()),'requires_configuration':bool(p.required_env)} for p in REGISTRY.values()]

# Public forum and community adapters are scheduler peers, not URL templates.
from .forums import HOSTS
from .community import STACK
for id in HOSTS:
    REGISTRY.setdefault(id,Provider(id,'nicktrail.forums:lookup_platform','public_api'))
for id in (*STACK,'Lichess','ChessCom'):
    REGISTRY[id]=Provider(id,'nicktrail.community:lookup_platform','platform_search' if id in STACK else 'public_api',id in STACK)

REGISTRY['Keybase']=Provider('Keybase','nicktrail.identityapis:lookup_platform','platform_search',True,exact_lookup=True,username_pattern=r'[A-Za-z0-9](?:[A-Za-z0-9]|_(?!_)){1,15}')
REGISTRY['HackerNews']=Provider('HackerNews','nicktrail.identityapis:lookup_platform','public_api')

REGISTRY['Extended']=Provider('Extended','nicktrail.extended:lookup','username_probe')
REGISTRY['Sensitive']=Provider('Sensitive','nicktrail.sensitive:lookup','username_probe')
REGISTRY['Archive']=Provider('Archive','nicktrail.archivesearch:lookup','archive_index')

from .native15 import SITES as NATIVE_SITES
for id in NATIVE_SITES:REGISTRY[id]=Provider(id,'nicktrail.native15:lookup_platform','public_api')

from .engineconfig import instances as engine_instances
from .engineconfig import HTML_ENGINES
for id,definition in engine_instances().items():REGISTRY[id]=Provider(id,'nicktrail.engines:lookup_platform','username_probe' if definition['engine'] in HTML_ENGINES else 'public_api',exact_lookup=definition['engine'] in HTML_ENGINES)

from .native17 import SITES as NATIVE17_SITES
for id in NATIVE17_SITES:REGISTRY[id]=Provider(id,'nicktrail.native17:lookup_platform','public_api')
