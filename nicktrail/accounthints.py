"""Find forgotten accounts in the user's own mailbox export and password-manager export.

Almost every sign-up leaves an e-mail ("Welcome", "Confirm your account",
"Password reset") and a saved login.  Both are the user's own data, read only
from files the user points to on their own computer:

  * mailbox: Google Takeout / Thunderbird `.mbox`, a folder of `.eml` files, or a
    `.zip` with either.  Only message headers are read (From, Subject, Date);
    bodies are skipped while streaming.  Stored per sender domain: counts, dates,
    signal kinds (welcome/verify/reset/login/deletion) and sender names.  Subjects
    are used for classification and then discarded.
  * password export (CSV from Chrome, Edge, Firefox, Bitwarden, 1Password,
    KeePass, LastPass, Proton Pass, Dashlane...): each row is parsed locally and
    only the website and username cells are kept.  The password column is never
    copied into the result, never stored and never shown.

Nothing is sent anywhere.  A domain is a hint that an account may exist; the
user decides ("I have an account here", "deleted", "not an account").
"""
import csv
import io
import json
import os
import re
import unicodedata
import zipfile
from email.header import decode_header, make_header
from email.parser import BytesHeaderParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

from .storage import SCHEMA_LOCK

MAX_HEADER = 65536
# mbox separator: "From <sender> <date with a year>"; an unescaped body line rarely matches.
SEPARATOR = re.compile(rb'^From \S+ +.*\b\d{4}\b')
MAX_EML_FILES = 200000
MAX_CSV_BYTES = 50_000_000
STATUSES = ('new', 'mine', 'closed', 'ignored')

# Mailbox providers: mail from these domains is from people, not from a service.
PERSONAL = {
    'gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com', 'live.com', 'msn.com', 'yahoo.com', 'ymail.com',
    'icloud.com', 'me.com', 'mac.com', 'aol.com', 'proton.me', 'protonmail.com', 'pm.me', 'zoho.com', 'gmx.com',
    'gmx.net', 'gmx.de', 'web.de', 'mail.com', 'yandex.ru', 'yandex.com', 'mail.ru', 'wp.pl', 'o2.pl', 'onet.pl',
    'op.pl', 'onet.eu', 'interia.pl', 'interia.eu', 'poczta.fm', 'gazeta.pl', 'tlen.pl', 'vp.pl', 'autograf.pl',
    'buziaczek.pl', 'tutanota.com', 'tuta.io', 'fastmail.com', 'hey.com', 'seznam.cz', 'ukr.net', 'i.ua', 'meta.ua',
}
# Second-level suffixes, so "mail.example.co.uk" groups as "example.co.uk".
TWO_LEVEL = {
    'co.uk', 'org.uk', 'ac.uk', 'gov.uk', 'com.pl', 'net.pl', 'org.pl', 'edu.pl', 'gov.pl', 'info.pl', 'biz.pl',
    'waw.pl', 'krakow.pl', 'com.au', 'net.au', 'org.au', 'co.nz', 'co.jp', 'ne.jp', 'or.jp', 'com.br', 'com.mx',
    'com.ar', 'com.tr', 'co.za', 'com.ua', 'in.ua', 'kiev.ua', 'com.cn', 'com.hk', 'com.sg', 'co.in', 'co.kr',
    'com.tw', 'co.il', 'com.ru', 'msk.ru', 'spb.ru', 'co.at', 'or.at', 'gv.at',
}
SIGNALS = (
    ('deletion', ('usuniecie konta', 'konto zostalo usuniete', 'account deletion', 'account has been deleted',
                  'account deleted', 'delete your account', 'konto usuniete', 'kontoloschung')),
    ('welcome', ('witaj', 'witamy', 'welcome', 'willkommen', 'dziekujemy za rejestracje', 'thanks for signing up',
                 'thank you for registering', 'thanks for joining', 'rejestracj', 'registration', 'sign up', 'signup',
                 'account created', 'konto zostalo utworzone', 'your new account', 'nowe konto', 'zalozyles konto',
                 'zalozenie konta', 'get started')),
    ('verify', ('potwierdz', 'confirm', 'verify', 'verification', 'weryfik', 'aktywuj', 'aktywacja', 'activate',
                'activation', 'bestatig')),
    ('reset', ('reset', 'nowe haslo', 'zmiana hasla', 'zmien haslo', 'password', 'haslo', 'passwort')),
    ('login', ('logowanie', 'zalogowano', 'sign-in', 'sign in', 'signed in', 'new login', 'new device',
               'nowe urzadzenie', 'security alert', 'alert bezpieczenstwa', 'kod weryfikacyjny', 'verification code',
               'login code', 'kod logowania', 'one-time', 'two-factor', '2fa', 'anmeldung')),
)
ACCOUNT_SIGNALS = {'welcome', 'verify', 'reset', 'login', 'deletion'}

URL_COLUMNS = ('url', 'login_uri', 'website', 'web site', 'uri', 'origin', 'login url', 'origin_url', 'site', 'hostname', 'urls')
USER_COLUMNS = ('username', 'login_username', 'login name', 'login', 'user name', 'user', 'email', 'e-mail', 'username1', 'login_name')


def schema(store):
    with SCHEMA_LOCK:
        store.db.execute('''CREATE TABLE IF NOT EXISTS account_hints(project INTEGER REFERENCES projects ON DELETE CASCADE,
            source TEXT,domain TEXT,first_seen TEXT,last_seen TEXT,messages INTEGER DEFAULT 0,signals TEXT DEFAULT '{}',
            senders TEXT DEFAULT '[]',usernames TEXT DEFAULT '[]',status TEXT DEFAULT 'new',PRIMARY KEY(project,source,domain))''')
        store.db.commit()


def registrable(host):
    host = (host or '').strip().lower().rstrip('.')
    if not host or not re.fullmatch(r'[a-z0-9.-]+', host) or '.' not in host:
        return None
    parts = [p for p in host.split('.') if p]
    if len(parts) < 2:
        return None
    if '.'.join(parts[-2:]) in TWO_LEVEL and len(parts) >= 3:
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:])


def _plain(text):
    text = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'\s+', ' ', text)


def classify(subject):
    plain = _plain(subject)
    for kind, words in SIGNALS:
        if any(w in plain for w in words):
            return kind
    return 'contact'


def _decoded(value):
    try:
        return str(make_header(decode_header(value or '')))
    except Exception:
        return str(value or '')


def _date(value):
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except Exception:
        return ''


class Collector:
    def __init__(self, own_addresses=()):
        self.own = {a.lower() for a in own_addresses}
        self.domains = {}
        self.messages = 0
        self.skipped_personal = 0

    def add_headers(self, raw):
        self.messages += 1
        try:
            headers = BytesHeaderParser().parsebytes(raw[:MAX_HEADER])
        except Exception:
            return
        senders = getaddresses([_decoded(headers.get('From', ''))])
        if not senders:
            return
        name, address = senders[0]
        address = address.lower().strip()
        if '@' not in address or address in self.own:
            return
        domain = registrable(address.rsplit('@', 1)[1])
        if not domain:
            return
        if domain in PERSONAL:
            self.skipped_personal += 1
            return
        kind = classify(_decoded(headers.get('Subject', '')))
        day = _date(headers.get('Date', ''))
        entry = self.domains.setdefault(domain, {'messages': 0, 'signals': {}, 'first': '', 'last': '', 'senders': {}})
        entry['messages'] += 1
        entry['signals'][kind] = entry['signals'].get(kind, 0) + 1
        if day:
            entry['first'] = min(entry['first'] or day, day)
            entry['last'] = max(entry['last'], day)
        label = (name or address.split('@', 1)[0]).strip()[:60]
        if label and (label in entry['senders'] or len(entry['senders']) < 3):
            entry['senders'][label] = entry['senders'].get(label, 0) + 1


def _mbox_headers(stream, collector):
    """Stream an mbox: collect each message's header block, skip bodies."""
    header, in_header, previous_blank = [], False, True
    size = 0
    for line in stream:
        if line.startswith(b'From ') and previous_blank and SEPARATOR.match(line):
            if header:
                collector.add_headers(b''.join(header))
            header, in_header, size = [], True, 0
            previous_blank = False
            continue
        if in_header:
            if line in (b'\n', b'\r\n'):
                in_header = False
            elif size < MAX_HEADER:
                header.append(line)
                size += len(line)
        previous_blank = line in (b'\n', b'\r\n')
    if header:
        collector.add_headers(b''.join(header))


def _eml_headers(stream, collector):
    lines, size = [], 0
    for line in stream:
        if line in (b'\n', b'\r\n') or size >= MAX_HEADER:
            break
        lines.append(line)
        size += len(line)
    collector.add_headers(b''.join(lines))


def scan_mailbox(path, own_addresses=()):
    path = Path(path).expanduser()
    if not path.exists():
        raise ValueError('Nie znaleziono pliku ani folderu: ' + str(path))
    collector = Collector(own_addresses)
    if path.is_dir():
        count = 0
        for file in path.rglob('*'):
            if file.is_file() and file.suffix.lower() in ('.eml', '.mbox', '.mbx'):
                count += 1
                if count > MAX_EML_FILES:
                    break
                with file.open('rb') as stream:
                    (_mbox_headers if file.suffix.lower() in ('.mbox', '.mbx') else _eml_headers)(stream, collector)
    elif path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                name = info.filename.lower()
                if info.is_dir() or not name.endswith(('.mbox', '.mbx', '.eml')):
                    continue
                with archive.open(info) as stream:
                    (_eml_headers if name.endswith('.eml') else _mbox_headers)(io.BufferedReader(stream), collector)
    elif path.suffix.lower() == '.eml':
        with path.open('rb') as stream:
            _eml_headers(stream, collector)
    else:
        with path.open('rb') as stream:
            _mbox_headers(stream, collector)
    if not collector.messages:
        raise ValueError('Nie znaleziono wiadomości. Wskaż plik .mbox (np. z Google Takeout), folder z plikami .eml albo archiwum .zip.')
    return collector


def _column(fields, names):
    lowered = {f.strip().lower(): f for f in fields if isinstance(f, str)}
    for name in names:
        if name in lowered:
            return lowered[name]
    return None


def scan_passwords(text):
    """Website + username pairs from a password-manager CSV.  Passwords are never kept."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Pusty plik eksportu haseł')
    if len(text) > MAX_CSV_BYTES:
        raise ValueError('Plik eksportu haseł jest za duży')
    csv.field_size_limit(1_000_000)
    reader = csv.reader(io.StringIO(text.lstrip('﻿')))
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError('Pusty plik eksportu haseł') from None
    url_col = _column(header, URL_COLUMNS)
    user_col = _column(header, USER_COLUMNS)
    if url_col is None:
        raise ValueError('Nie rozpoznano kolumny z adresem strony (np. url, login_uri, Web Site)')
    url_index = header.index(url_col)
    user_index = header.index(user_col) if user_col is not None else None
    domains, rows = {}, 0
    for row in reader:
        rows += 1
        # Only two cells are taken from the row; nothing else (passwords, notes, TOTP) is kept.
        site = row[url_index].strip() if len(row) > url_index else ''
        user = row[user_index].strip() if user_index is not None and len(row) > user_index else ''
        del row
        for candidate in re.split(r'[\s,]+', site):
            if not candidate:
                continue
            if '://' in candidate and not candidate.lower().startswith(('http://', 'https://')):
                continue  # android://, chrome-extension:// and similar are not websites
            try:
                host = urlsplit(candidate if '://' in candidate else 'https://' + candidate).hostname
            except ValueError:
                continue
            domain = registrable(host)
            if not domain:
                continue
            entry = domains.setdefault(domain, {'messages': 0, 'signals': {'saved_login': 0}, 'first': '', 'last': '', 'senders': {}, 'usernames': []})
            entry['messages'] += 1
            entry['signals']['saved_login'] += 1
            if user and len(user) <= 120 and user not in entry['usernames'] and len(entry['usernames']) < 5:
                entry['usernames'].append(user)
            break
    if not rows:
        raise ValueError('Plik eksportu haseł nie zawiera wpisów')
    return domains, rows


def save(store, project, source, domains):
    """Replace this source's hints for the project, keeping the user's earlier decisions."""
    schema(store)
    if not store.rows('SELECT id FROM projects WHERE id=?', (project,)):
        raise ValueError('Nieznany projekt')
    previous = {r['domain']: r['status'] for r in store.rows('SELECT domain,status FROM account_hints WHERE project=? AND source=?', (project, source))}
    with store.db:
        store.db.execute('DELETE FROM account_hints WHERE project=? AND source=?', (project, source))
        store.db.executemany('INSERT INTO account_hints VALUES(?,?,?,?,?,?,?,?,?,?)', [
            (project, source, domain, entry.get('first', ''), entry.get('last', ''), entry['messages'],
             json.dumps(entry['signals']), json.dumps(sorted(entry.get('senders', {}), key=lambda s: -entry['senders'][s])[:3], ensure_ascii=False),
             json.dumps(entry.get('usernames', []), ensure_ascii=False), previous.get(domain, 'new'))
            for domain, entry in domains.items()])
    return len(domains)


def import_mailbox(store, project, path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError('Podaj ścieżkę do pliku .mbox, folderu .eml lub archiwum .zip')
    own = [r['url'] for r in store.rows("SELECT url FROM nodes WHERE project=? AND kind='email' AND ownership='mine'", (project,))]
    collector = scan_mailbox(path.strip().strip('"'), own)
    saved = save(store, project, 'mail', collector.domains)
    likely = sum(1 for e in collector.domains.values() if ACCOUNT_SIGNALS & set(e['signals']))
    return {'messages': collector.messages, 'domains': saved, 'likely_accounts': likely, 'skipped_personal': collector.skipped_personal}


def import_passwords(store, project, text=None, path=None):
    if path:
        file = Path(str(path).strip().strip('"')).expanduser()
        if not file.is_file():
            raise ValueError('Nie znaleziono pliku: ' + str(file))
        if file.stat().st_size > MAX_CSV_BYTES:
            raise ValueError('Plik eksportu haseł jest za duży')
        text = file.read_text(encoding='utf-8-sig', errors='replace')
    domains, rows = scan_passwords(text)
    saved = save(store, project, 'passwords', domains)
    return {'entries': rows, 'domains': saved}


def decide(store, project, domain, status):
    schema(store)
    if status not in STATUSES:
        raise ValueError('Nieznany stan')
    if not store.rows('SELECT 1 FROM account_hints WHERE project=? AND domain=?', (project, domain)):
        raise ValueError('Nie znaleziono serwisu')
    store.execute('UPDATE account_hints SET status=? WHERE project=? AND domain=?', (status, project, domain))
    return status


def clear(store, project, source):
    schema(store)
    if source not in ('mail', 'passwords'):
        raise ValueError('Nieznane źródło')
    store.execute('DELETE FROM account_hints WHERE project=? AND source=?', (project, source))
    return 'Usunięto'


def view(store, project):
    """Hints merged per domain, strongest account signals first."""
    schema(store)
    merged = {}
    for row in store.rows('SELECT * FROM account_hints WHERE project=?', (project,)):
        entry = merged.setdefault(row['domain'], {'domain': row['domain'], 'sources': [], 'messages': 0, 'signals': {},
                                                  'first_seen': '', 'last_seen': '', 'senders': [], 'usernames': [], 'status': 'new'})
        entry['sources'].append(row['source'])
        entry['messages'] += row['messages'] or 0
        for kind, count in json.loads(row['signals'] or '{}').items():
            entry['signals'][kind] = entry['signals'].get(kind, 0) + count
        for key, field in (('first_seen', 'first_seen'), ('last_seen', 'last_seen')):
            value = row[field] or ''
            if value:
                entry[key] = (min if key == 'first_seen' else max)(entry[key] or value, value)
        entry['senders'] += [s for s in json.loads(row['senders'] or '[]') if s not in entry['senders']]
        entry['usernames'] += [u for u in json.loads(row['usernames'] or '[]') if u not in entry['usernames']]
        if row['status'] != 'new':
            entry['status'] = row['status']
    out = list(merged.values())
    for e in out:
        strong = ACCOUNT_SIGNALS | {'saved_login'}
        e['likely_account'] = bool(strong & set(e['signals']))
        e['score'] = sum(c for k, c in e['signals'].items() if k in strong) * 10 + e['messages']
    out.sort(key=lambda e: (e['status'] == 'ignored', not e['likely_account'], -e['score'], e['domain']))
    nicks = []
    from .search import validate_nickname
    for e in out:
        if e['status'] == 'ignored':
            continue
        for user in e['usernames']:
            if '@' in user:
                continue
            try:
                nick = validate_nickname(user)
            except ValueError:
                continue
            if len(nick) < 3:
                continue
            if nick.casefold() not in {n.casefold() for n in nicks}:
                nicks.append(nick)
    emails = sorted({u.lower() for e in out for u in e['usernames'] if '@' in u and e['status'] != 'ignored'})
    return {'services': out[:500], 'total': len(out), 'nicks': nicks[:30], 'emails': emails[:10]}
