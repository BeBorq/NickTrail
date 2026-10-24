"""Honest capabilities, including known blind spots and dated smoke results."""
import json
from pathlib import Path
from .providers import REGISTRY
from .forums import HOSTS
from .community import STACK
from .indexes import INDEXES

def describe():
    observed={v['id']:v for v in json.loads(Path(__file__).with_name('discovery_validation.json').read_text(encoding='utf-8'))['adapters']}
    rows=[]
    for id,p in REGISTRY.items():
        api=p.scope in ('public_api','platform_search')
        from .engineconfig import instances,HTML_ENGINES
        api=api or instances().get(id,{}).get('engine') in HTML_ENGINES
        rows.append({'id':id,'discovery':'name_search' if p.context_search else 'username_check','verification':api,'enrichment':api,'outbound_links':api and id not in ('ChessCom','RubyGems'),'available':p.available(),'live_test':observed.get(id,{'state':'not_tested_this_run'}),'limitations':('Keybase: publiczny katalog deklaracji, brak weryfikacji podpisu.' if id=='Keybase' else 'Indeks: nieodczytane tropy, limit 10–20, konfiguracja dostawcy.' if id in INDEXES else 'Dostęp anonimowy zależy od forum; dokładny nick, brak pełnego wyszukiwania.' if id in HOSTS else 'inname do 10 wyników; wspólna kwota i backoff API.' if id in STACK else 'Dokładny nick, brak linków w odpowiedzi API.' if id=='ChessCom' else 'Szablony nie są gwarancją odczytu; patrz katalog.' if id=='Free' else 'Ograniczenia adaptera i dostępu publicznego; brak gwarancji pełnych wyników.')})
    return rows
