"""Self-audit breach metadata. Never a source of identities or credentials."""

from .storage import SCHEMA_LOCK
import json
import os
from urllib.parse import quote
from .identity import EMAIL, email_key
from .storage import now


def schema(store):
    with SCHEMA_LOCK:
        initialized = getattr(store, '_initialized_schemas', set())
        if 'exposure' in initialized:
            return
        store._initialized_schemas = initialized | {'exposure'}
        store.execute('''CREATE TABLE IF NOT EXISTS exposure_checks(
          id INTEGER PRIMARY KEY,project INTEGER REFERENCES projects ON DELETE CASCADE,
          account TEXT,checked TEXT,state TEXT,detail TEXT,incidents TEXT)''')
        columns = {r[1] for r in store.db.execute('PRAGMA table_info(exposure_checks)')}
        for name, kind in (('provider_checked', 'REAL'), ('expires', 'REAL'), ('cached', 'INTEGER')):
            if name not in columns:
                store.execute('ALTER TABLE exposure_checks ADD COLUMN ' + name + ' ' + kind)


def check(store, project, account, consent, client=None):
    schema(store)
    if not store.rows('SELECT id FROM projects WHERE id=?', (project,)):
        raise ValueError('Nieznany projekt')
    if consent is not True:
        raise ValueError('Potwierdź własny adres / upoważnienie i przekazanie tego adresu do HIBP')
    if not isinstance(account, str) or len(account) > 254 or not EMAIL.fullmatch(account):
        raise ValueError('Podaj poprawny adres e-mail')
    account = email_key(account)
    from .exposureproviders import HIBP
    import hashlib, time

    provider = HIBP(store, client)
    if not os.environ.get('NICKTRAIL_HIBP_KEY'):
        raise ValueError('Brak NICKTRAIL_HIBP_KEY. Żaden identyfikator nie został wysłany.')
    provider.store.execute(
        'INSERT INTO exposure_consents(project,provider,query_hash,checked,purpose) VALUES(?,?,?,?,?)',
        (
            project,
            'HIBP',
            hashlib.sha256(account.encode()).hexdigest(),
            time.time(),
            'Explicit own/authorized email metadata lookup',
        ),
    )
    result = provider.check_identifier(account, consent=True)
    store.execute(
        'INSERT OR IGNORE INTO exposure_cache_projects VALUES(?,?,?,?)',
        (project, 'HIBP', 'account', result['cache_ref']),
    )
    state = result['state']
    incidents = result.get('incidents', [])
    detail = (
        'HIBP nie zwróciło znanych incydentów. To nie dowodzi braku wycieku.'
        if state == 'no_known_exposure'
        else (
            'Informacja o ekspozycji adresu, nie dowód własności kont społecznościowych.'
            if state == 'exposed'
            else result.get('detail', 'Sprawdzenie niedostępne')
        )
    )
    row = {
        'account': account,
        'checked': now(),
        'state': state,
        'detail': detail,
        'incidents': incidents,
        'provider': 'HIBP',
        'root_source': 'HIBP',
        'kind': 'EXPOSURE_METADATA',
        'identity_evidence': False,
        'cached': result['cached'],
        'expires': result['expires'],
        'attribution': result['attribution'],
    }
    store.execute(
        'INSERT INTO exposure_checks(project,account,checked,state,detail,incidents,provider_checked,expires,cached) VALUES(?,?,?,?,?,?,?,?,?)',
        (
            project,
            account,
            row['checked'],
            state,
            detail,
            json.dumps(incidents, ensure_ascii=False),
            result['checked'],
            result['expires'],
            int(result['cached']),
        ),
    )
    return row


def history(store, project):
    schema(store)
    rows = []
    for r in store.rows(
        'SELECT * FROM exposure_checks WHERE project=? ORDER BY id DESC LIMIT 20', (project,)
    ):
        incidents = json.loads(r['incidents'])
        rows.append(
            {
                **r,
                'provider': 'HIBP',
                'root_source': 'HIBP',
                'kind': 'EXPOSURE_METADATA',
                'identity_evidence': False,
                'incidents': incidents,
                'service_hints': service_hints(incidents),
            }
        )
    return rows


def service_hints(incidents, definitions=None):
    """Local review priorities from consented metadata, never account/identity evidence."""
    import re, ipaddress
    from urllib.parse import urlsplit

    if definitions is None:
        from .servicecatalog import services
        from .extended import services as extended_services

        definitions = [*services(), *extended_services()]
    hints = []
    seen = set()
    for incident in incidents:
        if (
            not isinstance(incident, dict)
            or incident.get('IsVerified') is not True
            or incident.get('IsFabricated')
            or incident.get('IsSpamList')
        ):
            continue
        domain = incident.get('Domain')
        if not isinstance(domain, str):
            continue
        domain = domain.strip().casefold().removeprefix('www.')
        if (
            len(domain) > 253
            or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', domain)
            or '.' not in domain
            or any(
                not label or len(label) > 63 or label.startswith('-') or label.endswith('-')
                for label in domain.split('.')
            )
        ):
            continue
        try:
            ipaddress.ip_address(domain)
            continue
        except ValueError:
            pass
        if domain in seen:
            continue
        matches = []
        for definition in definitions:
            template = definition.get('profile_url') or definition.get('url') or ''
            host = (
                (urlsplit(template).hostname or definition.get('domain') or '')
                .casefold()
                .removeprefix('www.')
            )
            if host == domain or host.endswith('.' + domain):
                name = definition.get('name') or definition.get('id')
                if name and name not in matches:
                    matches.append(name)
        seen.add(domain)
        hints.append(
            {
                'domain': domain,
                'services': matches[:10],
                'kind': 'service_review_priority',
                'identity_evidence': False,
                'network_calls': 0,
                'reason': 'Metadane incydentu sugerują ręczne sprawdzenie tego serwisu i ustawień prywatności. Nie potwierdzają istnienia ani własności profilu.',
            }
        )
        if len(hints) >= 20:
            break
    return hints
