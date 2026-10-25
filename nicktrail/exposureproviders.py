"""Metadata-only exposure providers. No raw records, passwords or identity edges."""

import hashlib, json, os, re, time
from urllib.parse import quote
from .storage import SCHEMA_LOCK

BASE = 'https://haveibeenpwned.com/api/v3/'
ATTRIBUTION = 'Have I Been Pwned — CC BY 4.0 — https://haveibeenpwned.com/'


def schema(store):
    with SCHEMA_LOCK:
        store.execute(
            'CREATE TABLE IF NOT EXISTS exposure_provider_cache(provider TEXT,scope TEXT,query_hash TEXT,checked REAL,expires REAL,result TEXT,PRIMARY KEY(provider,scope,query_hash))'
        )
        store.execute(
            'CREATE TABLE IF NOT EXISTS exposure_consents(id INTEGER PRIMARY KEY,project INTEGER REFERENCES projects ON DELETE CASCADE,provider TEXT,query_hash TEXT,checked REAL,purpose TEXT)'
        )
        store.execute(
            'CREATE TABLE IF NOT EXISTS exposure_cache_projects(project INTEGER REFERENCES projects ON DELETE CASCADE,provider TEXT,scope TEXT,query_hash TEXT,PRIMARY KEY(project,provider,scope,query_hash))'
        )
        store.execute('''CREATE TRIGGER IF NOT EXISTS exposure_project_delete BEFORE DELETE ON projects BEGIN
   DELETE FROM exposure_provider_cache WHERE scope='account' AND EXISTS(SELECT 1 FROM exposure_cache_projects r WHERE r.project=OLD.id AND r.provider=exposure_provider_cache.provider AND r.scope=exposure_provider_cache.scope AND r.query_hash=exposure_provider_cache.query_hash) AND NOT EXISTS(SELECT 1 FROM exposure_cache_projects r WHERE r.project!=OLD.id AND r.provider=exposure_provider_cache.provider AND r.scope=exposure_provider_cache.scope AND r.query_hash=exposure_provider_cache.query_hash);
   DELETE FROM exposure_cache_projects WHERE project=OLD.id;
   DELETE FROM exposure_consents WHERE project=OLD.id;
  END''')


def metadata(item):
    if (
        not isinstance(item, dict)
        or not isinstance(item.get('Name'), str)
        or not 1 <= len(item['Name']) <= 200
    ):
        raise ValueError('Nieprawidłowy incydent HIBP')
    classes = item.get('DataClasses', [])
    if (
        not isinstance(classes, list)
        or len(classes) > 100
        or any(not isinstance(v, str) or len(v) > 200 for v in classes)
    ):
        raise ValueError('Nieprawidłowe kategorie danych HIBP')
    result = {'Name': item['Name'], 'DataClasses': classes}
    for key in ('Title', 'Domain', 'BreachDate', 'AddedDate', 'ModifiedDate'):
        value = item.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > 500):
            raise ValueError('Nieprawidłowe metadane HIBP')
        result[key] = value
    for key in ('IsVerified', 'IsFabricated', 'IsSpamList', 'IsRetired'):
        if key in item and type(item[key]) is not bool:
            raise ValueError('Nieprawidłowa flaga HIBP')
        result[key] = item.get(key)
    if 'PwnCount' in item:
        if type(item['PwnCount']) is not int or item['PwnCount'] < 0:
            raise ValueError('Nieprawidłowy licznik HIBP')
        result['PwnCount'] = item['PwnCount']
    if 'Description' in item:
        value = item['Description']
        if not isinstance(value, str) or len(value) > 20000:
            raise ValueError('Nieprawidłowy opis incydentu HIBP')
        from .adapters import Page

        page = Page()
        page.feed(value)
        page.close()
        result['Description'] = ' '.join(' '.join(page.parts).split())[:6000]
    # Description is plain text. Unknown fields/raw records remain outside the contract.
    return result


class ExposureProvider:
    def capabilities(self):
        raise NotImplementedError

    def check_identifier(self, identifier):
        raise NotImplementedError

    def list_incidents(self):
        raise NotImplementedError

    def incident_metadata(self, name):
        raise NotImplementedError

    def health(self):
        raise NotImplementedError

    def rate_limit_state(self):
        raise NotImplementedError


class HIBP(ExposureProvider):
    id = 'HIBP'
    root_source = 'HIBP'

    def __init__(self, store, client=None):
        from .network import Client
        from .cooldowns import bind

        self.validation_kind = 'fixture' if client is not None else 'live'
        self.store = store
        schema(store)
        self.client = client or Client(queries=3, seconds=30, per_domain=3, exposure_catalog=True)
        bind(self.client, store)

    def capabilities(self):
        key = bool(os.environ.get('NICKTRAIL_HIBP_KEY'))
        old_fingerprint = hashlib.sha256(
            ('\0' + hashlib.sha256(os.environ.get('NICKTRAIL_HIBP_KEY', '').encode()).hexdigest()).encode()
        ).hexdigest()
        fingerprint = hashlib.sha256((old_fingerprint + '\0live').encode()).hexdigest()
        cached = (
            self.store.rows(
                "SELECT result FROM exposure_provider_cache WHERE provider='HIBP' AND scope='subscription' AND query_hash=? AND expires>?",
                (fingerprint, time.time()),
            )
            if key
            else []
        )
        status = json.loads(cached[0]['result']) if cached else {}
        return {
            'provider': self.id,
            'root_source': self.root_source,
            'state': status.get('state', 'CONFIGURED' if key else 'UNCONFIGURED'),
            'PUBLIC_BREACH_CATALOG': 'AVAILABLE',
            'EXPOSURE_DATA_CLASSES': 'AVAILABLE',
            'EMAIL_BREACH_LOOKUP': ('CONFIGURED_NOT_VERIFIED' if key else 'API_KEY_REQUIRED'),
            'DOMAIN_LOOKUP': 'DOMAIN_VERIFICATION_REQUIRED',
            'PASTE_METADATA': 'DOCUMENTED_NOT_IMPLEMENTED',
            'USERNAME_METADATA': 'NOT_PROVIDED',
            'subscription': status.get('subscription'),
            'attribution': ATTRIBUTION,
            'network_calls': 0,
        }

    def rate_limit_state(self):
        from .cooldowns import active

        return [r for r in active(self.store) if r['host'] == 'haveibeenpwned.com']

    def request(self, scope, query, path, authenticated=False, ttl=86400):
        key = os.environ.get('NICKTRAIL_HIBP_KEY', '')
        if authenticated and not key:
            raise ValueError('Brak NICKTRAIL_HIBP_KEY. Żaden identyfikator nie został wysłany.')
        # Include a key fingerprint to prevent subscription results leaking between configurations.
        base_digest = hashlib.sha256(
            (query + '\0' + (hashlib.sha256(key.encode()).hexdigest() if authenticated else '')).encode()
        ).hexdigest()
        digest = hashlib.sha256((base_digest + '\0' + self.validation_kind).encode()).hexdigest()
        cached = self.store.rows(
            'SELECT result,checked,expires FROM exposure_provider_cache WHERE provider=? AND scope=? AND query_hash=?',
            (self.id, scope, digest),
        )
        if cached and cached[0]['expires'] > time.time():
            return json.loads(cached[0]['result']) | {
                'cached': True,
                'checked': cached[0]['checked'],
                'expires': cached[0]['expires'],
                'cache_ref': digest,
            }
        from .network import Limit
        import http.client

        try:
            response = self.client.get(
                BASE + path, **({'headers': {'hibp-api-key': key}} if authenticated else {})
            )
        except (OSError, http.client.HTTPException):
            response = {'state': 'error', 'detail': 'NETWORK_ERROR'}
        except Limit:
            response = {'state': 'error', 'detail': 'LOCAL_BUDGET_EXHAUSTED'}
        detail = response.get('detail', '')
        status_match = re.search(r'HTTP\s+(\d{3})', detail)
        code = int(status_match[1]) if status_match else None
        state = response['state']
        if state == 'found':
            try:
                body = json.loads(response['text'])
                if scope == 'subscription':
                    if not isinstance(body, dict):
                        raise ValueError('Nieprawidłowy status subskrypcji HIBP')
                    body = {
                        k: v
                        for k, v in body.items()
                        if k
                        in (
                            'SubscriptionName',
                            'SubscribedUntil',
                            'Rpm',
                            'DomainSearchMaxBreachedAccounts',
                            'MaxBreachedDomains',
                            'IncludesKAnon',
                            'IncludesStealerLogs',
                            'IncludesBulkDomainAdd',
                            'IncludesCustomerDomains',
                            'IncludesAutoSubdomainVerification',
                        )
                        and type(v) in (str, int, bool, type(None))
                    }
                    result = {'state': 'HEALTHY', 'subscription': body}
                else:
                    items = body if isinstance(body, list) else [body] if scope == 'incident' else None
                    if items is None or len(items) > 3000:
                        raise ValueError('Nieprawidłowa lista HIBP')
                    result = {
                        'state': (
                            'exposed'
                            if scope == 'account' and items
                            else 'no_known_exposure' if scope == 'account' else 'HEALTHY'
                        ),
                        'incidents': [metadata(v) for v in items],
                    }
            except (ValueError, TypeError, KeyError):
                result = {
                    'state': 'PARTIAL',
                    'incidents': [],
                    'reason': 'INVALID_PROVIDER_SCHEMA',
                    'detail': 'Dostawca zwrócił niezgodne metadane. Nie ustalono ekspozycji; odpowiedź nie została zinterpretowana jako brak incydentów.',
                }
        elif state == 'not_found' and scope == 'account':
            result = {'state': 'no_known_exposure', 'incidents': []}
        else:
            result = {
                'state': (
                    'RATE_LIMITED'
                    if code == 429
                    or 'RATE_LIMITED' in detail
                    or 'przerwa zalecona' in detail.casefold()
                    or self.rate_limit_state()
                    else (
                        'AUTH_FAILED'
                        if code == 401
                        else (
                            'SUBSCRIPTION_REQUIRED'
                            if code == 402
                            else 'ACCESS_DENIED' if code == 403 else 'PARTIAL'
                        )
                    )
                ),
                'incidents': [],
                'reason': (
                    'RESPONSE_TOO_LARGE'
                    if 'za duża' in detail
                    else 'HTTP_' + str(code) if code else 'UPSTREAM_UNAVAILABLE'
                ),
                'detail': 'Odczyt metadanych nie powiódł się; brak wyniku nie oznacza braku ekspozycji.',
            }
        checked = time.time()
        expires = checked + (
            ttl
            if result['state'] in ('HEALTHY', 'CONTROL_RESPONSE_TESTED', 'exposed', 'no_known_exposure')
            else 60
        )
        if self.validation_kind == 'fixture' and result['state'] == 'HEALTHY':
            result['state'] = 'CONTROL_RESPONSE_TESTED'
        result.update(
            provider=self.id,
            root_source=self.root_source,
            kind='EXPOSURE_METADATA',
            validation_kind=self.validation_kind,
            identity_evidence=False,
            attribution=ATTRIBUTION,
        )
        self.store.execute(
            'INSERT OR REPLACE INTO exposure_provider_cache VALUES(?,?,?,?,?,?)',
            (self.id, scope, digest, checked, expires, json.dumps(result, ensure_ascii=False)),
        )
        return result | {'cached': False, 'checked': checked, 'expires': expires, 'cache_ref': digest}

    def check_identifier(self, identifier, consent=False):
        from .identity import EMAIL, email_key

        if consent is not True:
            raise ValueError('Wymagana jawna zgoda na przekazanie identyfikatora do HIBP')
        if not isinstance(identifier, str) or len(identifier) > 254 or not EMAIL.fullmatch(identifier):
            raise ValueError('Nieprawidłowy adres e-mail')
        identifier = email_key(identifier)
        return self.request(
            'account',
            identifier,
            'breachedaccount/' + quote(identifier, safe='') + '?truncateResponse=false',
            True,
        )

    def list_incidents(self):
        return self.request('catalog', '', 'breaches')

    def incident_metadata(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}', name):
            raise ValueError('Nieprawidłowy identyfikator incydentu')
        return self.request('incident', name, 'breach/' + quote(name, safe=''))

    def health(self):
        return self.request('subscription', '', 'subscription/status', True, 3600)
