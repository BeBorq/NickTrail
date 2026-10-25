"""Local, per-database reading settings (robots.txt handling and speed).

None of these options bypasses CAPTCHAs, logins, access control or anti-bot
challenges.  They only change how NickTrail interprets robots.txt (within or
beside RFC 9309), how long a refusal is remembered, and how many *different*
services are read at the same time.  Each single service is still read one
request at a time with at least the configured pause.
"""

import json

from .storage import SCHEMA_LOCK

DEFAULTS = {
    # RFC 9309 2.3.1.2: follow robots.txt redirects, also to another host.
    'robots_follow_redirects': True,
    # RFC 9309 2.3.1.3: a 4xx robots.txt (e.g. 401/403) means "unavailable", crawling MAY proceed.
    'robots_4xx_allow': False,
    # Crawl-delay / Request-rate is not part of RFC 9309.  When honoured, the full declared
    # pause is always kept; it is never shortened.  Up to the threshold NickTrail waits
    # during the round; above it the policy decides: skip the source or keep the full pause.
    'crawl_delay_wait': False,
    'crawl_delay_max': 10,
    'crawl_delay_long': 'skip',
    # Remember definitive robots.txt refusals per host so later searches skip them.
    'robots_memory': True,
    'robots_memory_hours': 24,
    # Different services read at the same time (1 = strictly sequential, as before 0.20).
    'parallel_hosts': 3,
}
LIMITS = {'crawl_delay_max': (1, 30), 'robots_memory_hours': (1, 168), 'parallel_hosts': (1, 6)}
CHOICES = {'crawl_delay_long': ('skip', 'wait')}
CHOICE_LABELS = {'skip': 'pomiń źródło', 'wait': 'respektuj pełną przerwę (wolniej)'}
LABELS = {
    'robots_follow_redirects': 'Idź za przekierowaniem robots.txt (także na inną domenę, RFC 9309)',
    'robots_4xx_allow': 'robots.txt z kodem 4xx (np. 401/403) traktuj jak brak reguł (RFC 9309 dopuszcza)',
    'crawl_delay_wait': 'Respektuj Crawl-delay zamiast pomijać serwis (zawsze pełna zadeklarowana przerwa, nigdy skrócona)',
    'crawl_delay_max': 'Próg krótkiej przerwy [s]: do tej wartości czekaj w trakcie wyszukiwania',
    'crawl_delay_long': 'Przerwa dłuższa niż próg',
    'robots_memory': 'Pamiętaj odmowy robots.txt i nie pytaj ponownie',
    'robots_memory_hours': 'Jak długo pamiętać odmowę [h]',
    'parallel_hosts': 'Ile różnych serwisów sprawdzać naraz (każdy nadal po jednym zapytaniu)',
}


def schema(store):
    with SCHEMA_LOCK:
        store.db.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)')
        store.db.commit()


def validate(changes):
    if not isinstance(changes, dict) or set(changes) - set(DEFAULTS):
        raise ValueError('Nieznane ustawienie')
    out = {}
    for key, value in changes.items():
        if isinstance(DEFAULTS[key], bool):
            if type(value) is not bool:
                raise ValueError('Ustawienie ' + key + ' musi być tak/nie')
        elif key in CHOICES:
            if value not in CHOICES[key]:
                raise ValueError('Ustawienie ' + key + ': ' + ' albo '.join(CHOICES[key]))
        else:
            low, high = LIMITS[key]
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'Ustawienie {key}: liczba od {low} do {high}')
        out[key] = value
    return out


def load(store):
    if not store.rows("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"):
        return dict(DEFAULTS)
    saved = {}
    for row in store.rows('SELECT key,value FROM settings'):
        if row['key'] in DEFAULTS:
            try:
                saved.update(validate({row['key']: json.loads(row['value'])}))
            except (ValueError, TypeError):
                continue
    return DEFAULTS | saved


def apply(store):
    """Load this database's settings into the process-wide network settings."""
    from . import network

    values = load(store)
    network.SETTINGS.clear()
    network.SETTINGS.update(values)
    return values


def save(store, changes):
    changes = validate(changes)
    schema(store)
    for key, value in changes.items():
        store.execute(
            'INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            (key, json.dumps(value)),
        )
    return apply(store)


def describe(store):
    values = load(store)
    return {
        'values': values,
        'defaults': DEFAULTS,
        'labels': LABELS,
        'limits': LIMITS,
        'choices': {k: [[v, CHOICE_LABELS[v]] for v in options] for k, options in CHOICES.items()},
        'note': 'Żadna opcja nie omija CAPTCHA, logowania ani blokad anty-bot. Każdy serwis jest odpytywany po jednym zapytaniu naraz.',
    }
