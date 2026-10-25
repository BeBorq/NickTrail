"""Domain-scoped index discovery; never guesses profile existence from HTTP 200."""

import os
from urllib.parse import urlsplit
from .context import SITES


def queries(terms, context):
    from .planning import words_queries

    values = list(dict.fromkeys([*terms, *words_queries(context)]))[:8]
    return [
        (site, 'site:' + site + ' ' + ' '.join('"' + v.replace('"', ' ') + '"' for v in [term]))
        for term in values
        for site in SITES
    ]


def lookup(term, client):
    from .websearch import lookup as index_lookup

    if not os.environ.get('NICKTRAIL_BRAVE_KEY'):
        return {
            'state': 'unsupported',
            'detail': 'Katalog 180 domen: automatyczny indeks wymaga NICKTRAIL_BRAVE_KEY; plan ręczny działa bez klucza.',
            'matches': [],
        }
    domain = term.split(' ', 1)[0].removeprefix('site:')
    if domain not in SITES:
        raise ValueError('Nieznana domena katalogu')
    result = index_lookup(term, client)
    result['matches'] = [
        m
        for m in result.get('matches', [])
        if (urlsplit(m['url']).hostname or '').removeprefix('www.') == domain
        or (urlsplit(m['url']).hostname or '').endswith('.' + domain)
    ]
    if result.get('state') == 'found' and not result['matches']:
        result['state'] = 'not_found'
    result['detail'] = domain + ' — ' + result.get('detail', '')
    return result
