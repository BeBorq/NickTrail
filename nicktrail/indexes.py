"""Optional permitted web indexes. Snippets are leads, never profile evidence."""
import json,os
from urllib.parse import urlencode,urlsplit
from .identity import normalize
INDEXES=('Web','SearXNG','Mojeek','GoogleCSE')

def leads(items,provider,url_key='url',snippet_key='content'):
    if not isinstance(items,list):raise ValueError('Nieprawidłowa lista wyników indeksu')
    matches=[];seen=set()
    for item in items[:20]:
        if not isinstance(item,dict) or not isinstance(item.get(url_key),str):continue
        try:url=normalize(item[url_key])
        except ValueError:continue
        if url in seen:continue
        seen.add(url)
        matches.append({'url':url,'data':{'indexed_only':True,'discovery_provider':provider,'search_title':str(item.get('title',''))[:300],'search_snippet':str(item.get(snippet_key,''))[:500]},'evidence':[]})
    return {'state':'found' if matches else 'not_found','matches':matches,'detail':provider+': do 20 tropów indeksu; strony nieodczytane, własność niepotwierdzona.'}

def lookup(provider,term,client):
    if not isinstance(term,str) or not term.strip() or len(term)>500:raise ValueError('Nieprawidłowe zapytanie indeksu')
    if provider=='SearXNG':
        base=normalize(os.environ['NICKTRAIL_SEARXNG_URL']);p=urlsplit(base)
        if p.scheme!='https' or p.query or p.fragment:raise ValueError('SearXNG wymaga publicznego HTTPS bez parametrów; prywatne adresy pozostają zablokowane')
        endpoint=base.rstrip('/')+'/search?'+urlencode({'q':term,'format':'json','categories':'general'})
    elif provider=='Mojeek':endpoint='https://www.mojeek.com/search?'+urlencode({'q':term,'api_key':os.environ['NICKTRAIL_MOJEEK_KEY'],'fmt':'json','t':20})
    elif provider=='GoogleCSE':endpoint='https://www.googleapis.com/customsearch/v1?'+urlencode({'q':term,'key':os.environ['NICKTRAIL_GOOGLE_KEY'],'cx':os.environ['NICKTRAIL_GOOGLE_CX'],'num':10})
    else:raise ValueError('Nieznany indeks')
    response=client.get(endpoint)
    if response['state']!='found':return response|{'matches':[]}
    body=json.loads(response['text'])
    if not isinstance(body,dict):raise ValueError('Nieprawidłowy wynik indeksu')
    if provider=='SearXNG':
        result=leads(body.get('results'),provider)
        if body.get('unresponsive_engines'):
            result['state']='partial';result['detail']+=' Niektóre silniki nie odpowiedziały.'
        return result
    if provider=='GoogleCSE':
        if 'error' in body:return {'state':'blocked','matches':[],'detail':'GoogleCSE: błąd uprawnień/limitu API; bez ponawiania inną drogą.'}
        return leads(body.get('items',[]),provider,'link','snippet')
    response=body.get('response')
    if not isinstance(response,dict):raise ValueError('Nieprawidłowa odpowiedź Mojeek')
    if response.get('status') not in (None,'OK',200):return {'state':'blocked','matches':[],'detail':'Mojeek: API odrzuciło żądanie.'}
    return leads(response.get('results',[]),provider,'url','desc')

def searx_lookup(term,client):return lookup('SearXNG',term,client)
def mojeek_lookup(term,client):return lookup('Mojeek',term,client)
def google_lookup(term,client):return lookup('GoogleCSE',term,client)
