"""Optional documented Brave API. Indexed results remain unverified leads."""

import json
import os
from urllib.parse import quote
from .identity import normalize


def lookup(term, client):
    key = os.environ.get('NICKTRAIL_BRAVE_KEY', '')
    if not key:
        return {
            'state': 'unsupported',
            'detail': 'Ustaw NICKTRAIL_BRAVE_KEY i uruchom ponownie serwer.',
            'matches': [],
        }
    response = client.get(
        'https://api.search.brave.com/res/v1/web/search?q=' + quote(term, safe='') + '&count=20',
        headers={'X-Subscription-Token': key},
    )
    if response['state'] != 'found':
        return response
    body = json.loads(response['text'])
    if not isinstance(body, dict) or not isinstance(body.get('web', {}), dict):
        raise ValueError('Nieprawidłowy wynik wyszukiwarki')
    items = body.get('web', {}).get('results', [])
    if not isinstance(items, list):
        raise ValueError('Nieprawidłowa lista wyników')
    matches = []
    for item in items[:20]:
        if not isinstance(item, dict) or not isinstance(item.get('url'), str):
            continue
        try:
            url = normalize(item['url'])
        except ValueError:
            continue
        matches.append(
            {
                'url': url,
                'data': {
                    'indexed_only': True,
                    'search_title': str(item.get('title', ''))[:300],
                    'search_snippet': str(item.get('description', ''))[:500],
                },
                'evidence': [],
            }
        )
    return {
        'state': 'found' if matches else 'not_found',
        'matches': matches,
        'detail': 'Do 20 wyników indeksu Brave. Strony nie zostały odczytane; wynik nie potwierdza istnienia konta ani właściciela.',
    }
