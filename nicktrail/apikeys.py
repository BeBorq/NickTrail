"""API keys typed into the panel.

Keys live in a small file in the user's own config folder, never in the project
database (databases get copied, exported and attached), never in exports, and
never come back to the browser: the panel only learns whether a key is set and
its last four characters.  Environment variables set outside NickTrail win.
"""

import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit

# Each entry: env name, field label, kind, and the service it belongs to.
SERVICES = [
    {
        'id': 'brave',
        'name': 'Brave Search API',
        'used_for': 'Indeks WWW i katalog 180 domen: automatyczne wyszukiwanie profili przez wyszukiwarkę.',
        'cost': 'Płatne za użycie; co miesiąc $5 darmowego kredytu (ok. 1000 zapytań). Wymaga karty; ustaw limit w panelu Brave.',
        'steps': 'Zaloguj się, wybierz plan Search, potem „API Keys” → „Add API key”.',
        'links': [
            ('Panel Brave Search API', 'https://api-dashboard.search.brave.com/'),
            ('Cennik', 'https://api-dashboard.search.brave.com/documentation/pricing'),
        ],
        'fields': [('NICKTRAIL_BRAVE_KEY', 'Klucz API (X-Subscription-Token)', 'secret')],
    },
    {
        'id': 'hibp',
        'name': 'Have I Been Pwned',
        'used_for': 'Sprawdzenie, w jakich znanych wyciekach wystąpił Twój adres e-mail (tylko nazwy incydentów, bez haseł).',
        'cost': 'Płatna subskrypcja.',
        'steps': 'Kup subskrypcję i skopiuj klucz ze strony klucza API.',
        'links': [('Klucz API HIBP', 'https://haveibeenpwned.com/API/Key')],
        'fields': [('NICKTRAIL_HIBP_KEY', 'Klucz API (hibp-api-key)', 'secret')],
    },
    {
        'id': 'steam',
        'name': 'Steam Web API',
        'used_for': 'Odczyt publicznych profili Steam po nicku (vanity URL).',
        'cost': 'Bezpłatnie; konto Steam musi mieć wydane co najmniej $5.',
        'steps': 'Zaloguj się do Steam, wpisz dowolną domenę (np. localhost) i zaakceptuj warunki.',
        'links': [('Rejestracja klucza Steam', 'https://steamcommunity.com/dev/apikey')],
        'fields': [('NICKTRAIL_STEAM_KEY', 'Klucz Steam Web API', 'secret')],
    },
    {
        'id': 'twitch',
        'name': 'Twitch',
        'used_for': 'Sprawdzenie publicznego profilu kanału Twitch po loginie (bio, nazwa, zdjęcie).',
        'cost': 'Bezpłatnie.',
        'steps': 'W konsoli deweloperskiej zarejestruj aplikację (Client ID). Token aplikacji uzyskaj metodą client credentials z Client ID i Client Secret.',
        'links': [
            ('Konsola aplikacji Twitch', 'https://dev.twitch.tv/console/apps'),
            (
                'Jak uzyskać token aplikacji',
                'https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/',
            ),
        ],
        'fields': [
            ('NICKTRAIL_TWITCH_CLIENT_ID', 'Client ID', 'text'),
            ('NICKTRAIL_TWITCH_TOKEN', 'Token aplikacji (App Access Token)', 'secret'),
        ],
    },
    {
        'id': 'xbox',
        'name': 'Xbox (OpenXBL)',
        'used_for': 'Sprawdzenie publicznego profilu Xbox po gamertagu przez OpenXBL.',
        'cost': 'Bezpłatny plan OpenXBL; wymaga konta Microsoft.',
        'steps': 'Zaloguj się do OpenXBL kontem Microsoft i wygeneruj klucz API (X-Authorization).',
        'links': [('Panel OpenXBL', 'https://xbl.io/')],
        'fields': [('NICKTRAIL_XBOX_KEY', 'Klucz OpenXBL (X-Authorization)', 'secret')],
    },
    {
        'id': 'mastodon',
        'name': 'Mastodon',
        'used_for': 'Wyszukiwanie kont w sieci Mastodon (fediwersum) przez Twoją instancję.',
        'cost': 'Bezpłatnie.',
        'steps': 'Na swojej instancji: Preferencje → Development → Nowa aplikacja, zakres tylko „read”. Skopiuj „Your access token”.',
        'links': [
            ('Aplikacje na mastodon.social', 'https://mastodon.social/settings/applications'),
            ('Inna instancja: https://TWOJA-INSTANCJA/settings/applications', ''),
        ],
        'fields': [
            ('NICKTRAIL_MASTODON_INSTANCE', 'Adres instancji (np. https://mastodon.social)', 'url'),
            ('NICKTRAIL_MASTODON_TOKEN', 'Token dostępu', 'secret'),
        ],
    },
    {
        'id': 'x',
        'name': 'X (Twitter) API',
        'used_for': 'Odczyt bio i pola „strona” wybranego profilu X.',
        'cost': 'Wyłącznie płatne za użycie (kredyty kupowane z góry); brak darmowego planu.',
        'steps': 'W konsoli deweloperskiej utwórz aplikację, w „Keys and tokens” wygeneruj Bearer Token.',
        'links': [
            ('Konsola deweloperska X', 'https://console.x.com/'),
            ('Cennik X API', 'https://docs.x.com/x-api/getting-started/pricing'),
        ],
        'fields': [('NICKTRAIL_X_BEARER_TOKEN', 'Bearer Token', 'secret')],
    },
    {
        'id': 'mojeek',
        'name': 'Mojeek Search API',
        'used_for': 'Niezależny indeks wyszukiwarki jako dodatkowe źródło kandydatów.',
        'cost': 'Płatne; dostęp na wniosek.',
        'steps': 'Złóż wniosek o dostęp na stronie API i skopiuj otrzymany klucz.',
        'links': [('Mojeek Web Search API', 'https://www.mojeek.com/services/search/web-search-api/')],
        'fields': [('NICKTRAIL_MOJEEK_KEY', 'Klucz API', 'secret')],
    },
    {
        'id': 'google',
        'name': 'Google Programmable Search',
        'used_for': 'Wyszukiwanie w Google przez własną wyszukiwarkę (CSE).',
        'cost': 'Zamknięte dla nowych klientów; usługa kończy działanie 1 stycznia 2027. Działa tylko z istniejącym kluczem.',
        'steps': 'Klucz: Google Cloud → APIs & Services → Credentials. Identyfikator wyszukiwarki (cx): panel Programmable Search.',
        'links': [
            ('Klucze Google Cloud', 'https://console.cloud.google.com/apis/credentials'),
            (
                'Panel Programmable Search (cx)',
                'https://programmablesearchengine.google.com/controlpanel/all',
            ),
        ],
        'fields': [
            ('NICKTRAIL_GOOGLE_KEY', 'Klucz API', 'secret'),
            ('NICKTRAIL_GOOGLE_CX', 'Identyfikator wyszukiwarki (cx)', 'text'),
        ],
    },
    {
        'id': 'searxng',
        'name': 'SearXNG',
        'used_for': 'Własna lub dozwolona instancja meta-wyszukiwarki z włączonym formatem JSON.',
        'cost': 'Bezpłatnie (własny serwer).',
        'steps': 'Uruchom własną instancję dostępną pod publicznym adresem https:// i włącz format json w settings.yml. Adres lokalny (127.0.0.1) nie zadziała: NickTrail ze względów bezpieczeństwa łączy się tylko z publicznymi adresami.',
        'links': [('Instalacja SearXNG', 'https://docs.searxng.org/admin/installation.html')],
        'fields': [('NICKTRAIL_SEARXNG_URL', 'Publiczny adres instancji (https://…)', 'url')],
    },
]
FIELDS = {env: (label, kind) for s in SERVICES for env, label, kind in s['fields']}
_loaded = set()  # env names this module put into os.environ


def path():
    base = (
        os.environ.get('APPDATA')
        if os.name == 'nt'
        else os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    )
    return Path(base or os.path.expanduser('~')) / 'NickTrail' / 'api-keys.json'


def _read():
    try:
        data = json.loads(path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return (
        {k: v for k, v in data.items() if k in FIELDS and isinstance(v, str)}
        if isinstance(data, dict)
        else {}
    )


def _write(data):
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=1), encoding='utf-8')
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    os.replace(tmp, target)


def load():
    """Put saved keys into the environment, without overriding variables set outside NickTrail."""
    for env, value in _read().items():
        if not os.environ.get(env) or env in _loaded:
            os.environ[env] = value
            _loaded.add(env)


def validate(env, value):
    if env not in FIELDS:
        raise ValueError('Nieznany klucz')
    value = value.strip()
    if not value:
        return ''
    if len(value) > 512 or re.search(r'[\s\x00-\x1f\x7f]', value):
        raise ValueError(FIELDS[env][0] + ': niedozwolone znaki lub zbyt długa wartość')
    if FIELDS[env][1] == 'url':
        p = urlsplit(value)
        # The network client only connects to public HTTPS addresses, so a local or
        # plain-http address would be saved but could never work.
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ValueError(FIELDS[env][0] + ': wymagany publiczny adres https:// bez parametrów')
        import ipaddress

        try:
            local = not ipaddress.ip_address(p.hostname).is_global
        except ValueError:  # a host name, not an IP literal
            local = p.hostname == 'localhost' or p.hostname.endswith('.localhost')
        if local:
            raise ValueError(FIELDS[env][0] + ': adres lokalny lub prywatny nie jest obsługiwany')
        value = value.rstrip('/')
    return value


def save(changes):
    """Set or clear keys. Empty value clears a key saved in the panel."""
    if not isinstance(changes, dict) or not changes:
        raise ValueError('Brak zmian')
    clean = {env: validate(env, value if isinstance(value, str) else '') for env, value in changes.items()}
    data = _read()
    for env, value in clean.items():
        if value:
            data[env] = value
            os.environ[env] = value
            _loaded.add(env)
        else:
            data.pop(env, None)
            if env in _loaded:
                os.environ.pop(env, None)
                _loaded.discard(env)
    _write(data)
    return describe()


def _mask(value, kind):
    if kind in ('url', 'text'):
        return value if kind == 'url' else value[:4] + '…' if len(value) > 8 else '••••'
    return '••••' + value[-4:] if len(value) > 8 else '••••'


def describe():
    saved = _read()
    out = []
    for s in SERVICES:
        fields = []
        for env, label, kind in s['fields']:
            value = os.environ.get(env, '')
            source = 'panel' if env in saved and env in _loaded else 'environment' if value else None
            fields.append(
                {
                    'env': env,
                    'label': label,
                    'kind': kind,
                    'set': bool(value),
                    'source': source,
                    'preview': _mask(value, kind) if value else '',
                }
            )
        out.append(
            {k: s[k] for k in ('id', 'name', 'used_for', 'cost', 'steps')}
            | {
                'links': [{'label': a, 'url': b} for a, b in s['links']],
                'fields': fields,
                'ready': all(f['set'] for f in fields),
            }
        )
    return {
        'services': out,
        'file': str(path()),
        'note': 'Klucze są zapisane w pliku użytkownika poza bazą projektu i nie trafiają do eksportów.',
    }
