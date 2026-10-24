"""Public instance definitions. Network safety remains in Client, never in imported data."""
import json,re,os
from pathlib import Path
from functools import lru_cache
HTML_ENGINES={'xenforo','phpbb','vbulletin','invision','mybb','vanilla','pixelfed','mbin','misskey','ghost'}

def alias_for_url(definition,url):
    from .identity import normalize
    from urllib.parse import unquote
    template=normalize(definition['profile_url'].format(nick='nicktrailplaceholder'))
    match=re.fullmatch(re.escape(template).replace('nicktrailplaceholder',r'([^/?#&]+)'),normalize(url))
    alias=unquote(match[1]) if match else ''
    return alias if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}',alias) else None
@lru_cache(maxsize=1)
def instances():
    rows=json.loads(Path(__file__).with_name('engine_instances.json').read_text(encoding='utf-8'));out={}
    extra=os.environ.get('NICKTRAIL_ENGINE_INSTANCES')
    if extra:
        path=Path(extra)
        if path.stat().st_size>100000:raise ValueError('Instance configuration too large')
        custom=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(custom,list) or len(custom)>100 or any(not isinstance(row,dict) for row in custom):raise ValueError('At most 100 explicit instances')
        rows+= [row|{'live_status':'UNTESTED'} for row in custom]
    for row in rows:
        if not isinstance(row,dict) or any(not isinstance(row.get(key),str) for key in ('id','host','engine','live_status','limitations')):raise ValueError('Nieprawidłowe pola instancji')
        if set(row)-{'id','host','engine','live_status','limitations','profile_url'} or not {'id','host','engine','live_status','limitations'}<=set(row) or row['engine'] not in {'gitea','forgejo','gitlab','discourse','wordpress','lemmy','mastodon','peertube','mediawiki','nodebb','flarum'}|HTML_ENGINES:raise ValueError('Nieznany silnik instancji')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]{1,50}',row['id']) or not re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}',row['host']) or row['id'] in out:raise ValueError('Nieprawidłowa instancja')
        if row['engine'] in HTML_ENGINES:
            from urllib.parse import urlsplit,parse_qs
            template=row.get('profile_url')
            if not isinstance(template,str) or len(template)>500 or template.count('{nick}')!=1 or '{' in template.replace('{nick}','') or '}' in template.replace('{nick}',''):raise ValueError('Ten silnik wymaga jawnego publicznego profile_url z {nick}; brak zgadywania API lub numerów użytkowników')
            p=urlsplit(template.format(nick='nicktrailfixture'))
            if p.scheme!='https' or p.hostname!=row['host'] or p.username or p.password or p.port not in (None,443) or p.fragment or any(k.casefold() in ('key','sid','session','session_id','auth','secret') or re.search(r'(?i)(password|passwd|token|cookie|api.?key|authorization)',k) for k in parse_qs(p.query)):raise ValueError('Niebezpieczna publiczna trasa profilu')
        elif 'profile_url' in row:raise ValueError('Natywny silnik API nie używa podmienianego szablonu')
        out[row['id']]=row
    return out
