"""What the last read of a saved profile returned, explained in plain words.

A read status is a hint for the user's own review ("this old account may be
gone"), never identity evidence and never a reason to change ownership labels.
"""
import json
import re
from datetime import datetime, timezone

SCHEMA = '''CREATE TABLE IF NOT EXISTS node_read_status(
  node INTEGER PRIMARY KEY REFERENCES nodes ON DELETE CASCADE,
  state TEXT, detail TEXT, observed TEXT)'''

# kind → panel tone. "missing"/"gone"/"changed" can mean the account no longer exists.
KINDS = {
    'missing': 'Konto może nie istnieć',
    'gone': 'Usunięte lub wyłączone',
    'changed': 'Pod adresem jest inne konto',
    'access': 'Konto może istnieć, odczyt zablokowany',
    'policy': 'Serwis nie pozwala na automatyczny odczyt',
    'temporary': 'Problem chwilowy',
    'unclear': 'Wynik niejednoznaczny',
}
MAY_BE_MISSING = {'missing', 'gone', 'changed'}

HTTP = {
    400: ('Błędne zapytanie', 'unclear', 'Serwis odrzucił adres. Nick może zawierać znaki, których ten serwis nie dopuszcza.'),
    401: ('Wymaga logowania', 'access', 'Profil może istnieć, ale jest prywatny albo widoczny tylko po zalogowaniu. To nie oznacza braku konta.'),
    403: ('Odmowa dostępu', 'access', 'Serwis odmówił automatycznego odczytu, często przez ochronę anty-bot. To nie oznacza braku konta; otwórz adres w przeglądarce.'),
    404: ('Nie znaleziono', 'missing', 'Serwis nie ma strony pod tym adresem. Konto mogło zostać usunięte, zmienić nazwę albo nigdy nie istniało.'),
    405: ('Metoda niedozwolona', 'unclear', 'Serwis nie obsługuje tego sposobu odczytu.'),
    408: ('Przekroczony czas', 'temporary', 'Serwis nie odpowiedział na czas. Spróbuj później.'),
    409: ('Konflikt', 'unclear', 'Serwis zgłosił konflikt stanu. Spróbuj później.'),
    410: ('Usunięte na stałe', 'gone', 'Serwis zgłasza, że strona została trwale usunięta. Zwykle oznacza to usunięte lub zamknięte konto.'),
    429: ('Za dużo zapytań', 'temporary', 'Serwis ogranicza tempo. NickTrail poczeka i spróbuje ponownie; to nic nie mówi o koncie.'),
    451: ('Niedostępne z przyczyn prawnych', 'access', 'Serwis blokuje treść w tym regionie albo z przyczyn prawnych.'),
    202: ('Odpowiedź niekompletna', 'temporary', 'Serwis przyjął zapytanie, ale nie zwrócił jeszcze treści profilu.'),
    204: ('Pusta odpowiedź', 'unclear', 'Serwis odpowiedział bez treści.'),
}

PATTERNS = (
    # Order matters: specific phrases before the generic "HTTP nnn".
    (r'strona błędu w odpowiedzi HTTP 200|soft.?404', 'Soft 404', 'Strona błędu', 'missing', 'Serwis zwrócił stronę „nie znaleziono” z kodem 200. Konto prawdopodobnie nie istnieje pod tym adresem.'),
    (r'PROFILE_NOT_FOUND|nie zwróciło publicznego aktywnego konta', 'API', 'Brak konta w API', 'missing', 'Publiczne API serwisu nie zna tego nicku. Konto mogło zostać usunięte albo zmienić nazwę.'),
    (r'trwał\w* identyfikator', 'ID', 'Inne konto pod adresem', 'changed', 'Pod tym adresem jest teraz konto o innym trwałym ID. Twoje konto mogło zostać usunięte, a nick zajęty przez kogoś innego.'),
    (r'ROBOTS_RESTRICTED|robots', 'robots.txt', 'Odczyt niedozwolony', 'policy', 'Serwis prosi automaty o niepobieranie tej strony. NickTrail to respektuje; sprawdź adres ręcznie.'),
    (r'Wyzwanie dostępu|captcha|challenge', 'CAPTCHA', 'Wyzwanie anty-bot', 'access', 'Serwis pokazał wyzwanie dostępu (np. CAPTCHA). NickTrail go nie omija; sprawdź adres ręcznie.'),
    (r'Limit przekierowań|REDIRECT_POLICY|przekierow', '3xx', 'Przekierowanie', 'unclear', 'Adres przekierowuje gdzie indziej, np. na stronę główną lub logowania. Tak często wygląda usunięte konto, ale nie zawsze.'),
    (r'LOCAL_DOMAIN_BUDGET|limit domeny', 'Limit', 'Limit tej rundy', 'temporary', 'Wyczerpał się limit zapytań tej rundy. Odczyt zostanie wznowiony.'),
    (r'gaierror|Name or service not known|getaddrinfo', 'DNS', 'Domena nie odpowiada', 'gone', 'Domena nie istnieje w DNS albo nie było sieci. Strona lub serwis mogły przestać działać.'),
    (r'Timeout|timed out', 'Timeout', 'Brak odpowiedzi', 'temporary', 'Serwis nie odpowiedział w wyznaczonym czasie. Spróbuj później.'),
    (r'SSL|certificate|CERTIFICATE', 'TLS', 'Błąd bezpiecznego połączenia', 'temporary', 'Nie udało się nawiązać bezpiecznego połączenia (certyfikat lub TLS).'),
    (r'Connection|ConnectionError|reset|refused', 'Sieć', 'Połączenie przerwane', 'temporary', 'Połączenie zostało przerwane lub odrzucone.'),
    (r'HTTP 200 bez jednoznacznych danych', '200', 'Brak danych profilu', 'unclear', 'Strona się otworzyła, ale nie zawiera jednoznacznych danych profilu.'),
)

STATE_FALLBACK = {
    'not_found': ('Nie znaleziono', 'missing', 'Odczyt nie znalazł profilu pod tym adresem. Konto mogło zostać usunięte albo zmienić nazwę.'),
    'blocked': ('Zablokowane', 'access', 'Serwis zablokował automatyczny odczyt. To nie oznacza braku konta.'),
    'error': ('Błąd odczytu', 'temporary', 'Odczyt się nie udał. Spróbuj ponownie później.'),
    'partial': ('Wynik częściowy', 'unclear', 'Odczyt dał niepełne dane.'),
}

PROBLEM_STATES = ('not_found', 'blocked', 'error', 'partial')


def schema(store):
    store.execute(SCHEMA)


def note(store, node, state, detail):
    """Remember the latest read outcome for one profile."""
    store.execute('INSERT OR REPLACE INTO node_read_status VALUES(?,?,?,?)',
                  (node, state, str(detail or '')[:500], datetime.now(timezone.utc).isoformat(timespec='seconds')))


def classify(state, detail):
    detail = str(detail or '')
    for pattern, code, label, kind, meaning in PATTERNS:
        if re.search(pattern, detail, re.I):
            match = re.search(r'HTTP (\d{3})', detail)
            if match and code == '3xx':
                code = match.group(1)
            return _result(code, label, kind, meaning)
    match = re.search(r'HTTP (\d{3})', detail)
    if match:
        status = int(match.group(1))
        if status in HTTP:
            label, kind, meaning = HTTP[status]
        elif 520 <= status <= 530:
            label, kind, meaning = 'Błąd pośrednika', 'temporary', 'Pośrednik serwisu (np. Cloudflare) nie połączył się ze stroną. Problem leży po stronie serwisu.'
        elif status >= 500:
            label, kind, meaning = 'Błąd serwera', 'temporary', 'Serwis miał wewnętrzny błąd. To nic nie mówi o koncie; spróbuj później.'
        elif 300 <= status < 400:
            label, kind, meaning = 'Przekierowanie', 'unclear', 'Adres przekierowuje gdzie indziej. Tak często wygląda usunięte konto, ale nie zawsze.'
        elif 400 <= status < 500:
            label, kind, meaning = 'Błąd zapytania', 'unclear', 'Serwis odrzucił odczyt kodem z grupy 4xx.'
        else:
            label, kind, meaning = 'Nietypowa odpowiedź', 'unclear', 'Serwis odpowiedział nietypowym kodem.'
        return _result(str(status), label, kind, meaning)
    if state in STATE_FALLBACK:
        label, kind, meaning = STATE_FALLBACK[state]
        return _result('', label, kind, meaning)
    return None


def _result(code, label, kind, meaning):
    return {'code': code, 'label': label, 'kind': kind, 'kind_label': KINDS[kind],
            'meaning': meaning, 'may_be_missing': kind in MAY_BE_MISSING}


def report(store, project, nodes):
    """Explain the last read of every saved profile whose current state is a problem."""
    problem = {n['id']: n for n in nodes if n.get('state') in PROBLEM_STATES}
    if not problem:
        return {}
    known = {}
    if store.rows("SELECT name FROM sqlite_master WHERE name='node_read_status'"):
        for row in store.rows('SELECT r.* FROM node_read_status r JOIN nodes n ON n.id=r.node WHERE n.project=?', (project,)):
            known[row['node']] = (row['state'], row['detail'], row['observed'], 'note')
    # Older data: the last scan observation, then the last search task that named the profile.
    for row in store.rows('SELECT o.node,o.state,o.detail,s.started FROM observations o JOIN scans s ON s.id=o.scan WHERE s.project=? ORDER BY o.scan', (project,)):
        if row['node'] in problem and row['node'] not in known:
            known[('obs', row['node'])] = (row['state'], row['detail'], row['started'], 'scan')
    for row in store.rows("SELECT t.state,t.detail,t.nodes,s.started FROM search_tasks t JOIN searches s ON s.id=t.search WHERE s.project=? AND t.nodes!='[]' AND t.state IN ('not_found','blocked','error','partial') ORDER BY t.search", (project,)):
        try:
            ids = json.loads(row['nodes'] or '[]')
        except ValueError:
            continue
        for id in ids:
            if id in problem and id not in known:
                known[('task', id)] = (row['state'], row['detail'], row['started'], 'search')
    out = {}
    for id, node in problem.items():
        last = known.get(id) or known.get(('obs', id)) or known.get(('task', id))
        state, detail, observed, source = last if last else (node['state'], '', '', 'state')
        if state not in PROBLEM_STATES:
            # The newest note is older than the current state; explain the state alone.
            state, detail, observed, source = node['state'], '', '', 'state'
        info = classify(state, detail)
        if info:
            out[str(id)] = info | {'detail': detail, 'observed': observed, 'source': source}
    return out
