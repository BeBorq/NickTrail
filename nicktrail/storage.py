import json
import sqlite3
from urllib.parse import urlsplit
from threading import RLock

SCHEMA_LOCK = RLock()
from datetime import datetime, timezone
from .identity import identify, email_key


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        with SCHEMA_LOCK:
            self.path = path
            self.db = sqlite3.connect(path, timeout=15)
            self.db.row_factory = sqlite3.Row
            self.db.executescript('''
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS nodes(id INTEGER PRIMARY KEY,project INTEGER REFERENCES projects ON DELETE CASCADE,
              url TEXT,platform TEXT,kind TEXT,ownership TEXT DEFAULT 'unknown',seed INTEGER DEFAULT 0,
              depth INTEGER DEFAULT 0,state TEXT DEFAULT 'unverified',data TEXT DEFAULT '{}',created TEXT,
              UNIQUE(project,url));
            CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY,project INTEGER REFERENCES projects ON DELETE CASCADE,
              source INTEGER REFERENCES nodes ON DELETE CASCADE,target INTEGER REFERENCES nodes ON DELETE CASCADE,
              relation TEXT,source_url TEXT,location TEXT,snippet TEXT,fetched TEXT,method TEXT,
              assessment TEXT DEFAULT 'clue',decision TEXT DEFAULT 'unknown',contradictions TEXT DEFAULT '',
              author TEXT DEFAULT '',post_date TEXT DEFAULT '',context TEXT DEFAULT 'own',
              UNIQUE(source,target,relation,source_url,location,snippet));
            CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY,project INTEGER REFERENCES projects ON DELETE CASCADE,
              started TEXT,finished TEXT,status TEXT,queue TEXT,visited TEXT DEFAULT '[]',requests INTEGER DEFAULT 0,
              options TEXT,notes TEXT DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS observations(scan INTEGER REFERENCES scans ON DELETE CASCADE,
              node INTEGER REFERENCES nodes ON DELETE CASCADE,state TEXT,data TEXT,detail TEXT,
              PRIMARY KEY(scan,node));
            CREATE TABLE IF NOT EXISTS focus(project INTEGER PRIMARY KEY REFERENCES projects ON DELETE CASCADE,
              node INTEGER REFERENCES nodes ON DELETE CASCADE,selected TEXT);
            CREATE TABLE IF NOT EXISTS profile_addresses(project INTEGER REFERENCES projects ON DELETE CASCADE,
              node INTEGER REFERENCES nodes ON DELETE CASCADE,url TEXT,first_seen TEXT,last_seen TEXT,
              PRIMARY KEY(node,url));
            ''')
            columns = {row['name'] for row in self.db.execute('PRAGMA table_info(evidence)')}
            for name, definition in (
                ('current', 'INTEGER NOT NULL DEFAULT 1'),
                ('last_seen', "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in columns:
                    self.execute(f'ALTER TABLE evidence ADD COLUMN {name} {definition}')
            # `seed` marks a top-level item (also every search hit); `user_added` marks what the
            # user typed or imported. Older databases: declarations are the user's by definition.
            if 'user_added' not in {row['name'] for row in self.db.execute('PRAGMA table_info(nodes)')}:
                self.execute('ALTER TABLE nodes ADD COLUMN user_added INTEGER NOT NULL DEFAULT 0')
                self.execute("UPDATE nodes SET user_added=1 WHERE platform='Deklaracja' AND ownership='mine'")
        from .readstatus import schema as read_status_schema

        read_status_schema(self)
        from .settings import apply as apply_settings

        apply_settings(self)

    def execute(self, sql, args=()):
        cur = self.db.execute(sql, args)
        self.db.commit()
        return cur

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    def project(self, name):
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValueError('Nazwa projektu: 1–200 znaków')
        return self.execute("INSERT INTO projects(name) VALUES(?)", (name.strip(),)).lastrowid

    def add(self, project, value, kind="url", confirmed=False, seed=True, depth=0):
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 2000
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("Wpis: 1–2000 znaków, bez znaków sterujących")
        if kind in ("url", "domain"):
            item = identify(("https://" + value) if kind == "domain" and "://" not in value else value)
        else:
            if kind not in ("alias", "email", "display", "country", "language", "discord"):
                raise ValueError("Nieznany typ")
            item = {
                "url": email_key(value) if kind == "email" else value.strip(),
                "platform": "Deklaracja",
                "kind": kind,
            }
            if kind == "email":
                return self._add_email(project, value, item["url"], confirmed, seed, depth)
        if kind == 'discord':
            import re

            if not re.fullmatch(r'[A-Za-z0-9_.]{2,32}(?:#[0-9]{4})?', value):
                raise ValueError('Nieprawidłowa publiczna deklaracja Discord')
            item = {'url': 'discord:' + value, 'platform': 'Discord', 'kind': 'discord'}
        cur = self.execute(
            """INSERT INTO nodes(project,url,platform,kind,ownership,seed,depth,created)
          VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project,url) DO UPDATE SET
          seed=MAX(nodes.seed,excluded.seed),depth=MIN(nodes.depth,excluded.depth)""",
            (
                project,
                item["url"],
                item["platform"],
                item["kind"],
                "mine" if confirmed else "unknown",
                int(seed),
                depth,
                now(),
            ),
        )
        id = self.rows("SELECT id FROM nodes WHERE project=? AND url=?", (project, item["url"]))[0]["id"]
        # Confirming an entry that already exists (e.g. a nick a search added earlier as
        # "unknown") must still record the user's confirmation.
        if confirmed:
            self.execute("UPDATE nodes SET ownership='mine' WHERE id=? AND ownership='unknown'", (id,))
        return id

    def _add_email(self, project, value, exact, confirmed, seed, depth):
        """One node per mailbox: provider-equivalent forms share the canonical node.

        An existing node for the same mailbox is reused even if it was stored
        before canonical keys existed, so new observations never split a
        mailbox.  Every exact published form is kept in data.published_forms.
        """
        from .emailid import canonical_key

        try:
            url, meta = canonical_key(value)
        except ValueError:
            url, meta = exact, None
        existing = None
        if meta is not None:
            for row in self.rows("SELECT id,url FROM nodes WHERE project=? AND kind='email'", (project,)):
                try:
                    same = row["url"] == url or canonical_key(row["url"])[0] == url
                except ValueError:
                    same = False
                if same and (existing is None or row["url"] == url):
                    existing = row
        if existing is None:
            self.execute(
                """INSERT INTO nodes(project,url,platform,kind,ownership,seed,depth,created)
              VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project,url) DO UPDATE SET
              seed=MAX(nodes.seed,excluded.seed),depth=MIN(nodes.depth,excluded.depth)""",
                (
                    project,
                    url,
                    "Deklaracja",
                    "email",
                    "mine" if confirmed else "unknown",
                    int(seed),
                    depth,
                    now(),
                ),
            )
            id = self.rows("SELECT id FROM nodes WHERE project=? AND url=?", (project, url))[0]["id"]
        else:
            id = existing["id"]
            self.execute(
                "UPDATE nodes SET seed=MAX(seed,?),depth=MIN(depth,?) WHERE id=?", (int(seed), depth, id)
            )
            if confirmed and self.node(id)["ownership"] == "unknown":
                self.execute("UPDATE nodes SET ownership='mine' WHERE id=?", (id,))
        self._remember_email_form(id, exact)
        return id

    def _remember_email_form(self, id, exact):
        node = self.node(id)
        try:
            data = json.loads(node["data"] or "{}")
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        forms = [f for f in data.get("published_forms", []) if isinstance(f, str)]
        if exact != node["url"] and exact not in forms and len(forms) < 20:
            data["published_forms"] = sorted(forms + [exact])
            self.execute(
                "UPDATE nodes SET data=? WHERE id=?",
                (json.dumps(data, ensure_ascii=False, sort_keys=True), id),
            )

    def node(self, id):
        rows = self.rows("SELECT * FROM nodes WHERE id=?", (id,))
        if not rows:
            raise ValueError("Nieznany element")
        return rows[0]

    def decide(self, id, decision, relation=False):
        choices = ("accepted", "rejected", "unknown") if relation else ("mine", "not_mine", "unknown")
        if decision not in choices:
            raise ValueError("Nieznana ocena")
        self.execute(
            f"UPDATE {'evidence' if relation else 'nodes'} SET {'decision' if relation else 'ownership'}=? WHERE id=?",
            (decision, id),
        )

    def evidence(
        self, project, source, target, relation, source_url, location, snippet, method="parser", **extra
    ):
        self.execute(
            """INSERT INTO evidence(project,source,target,relation,source_url,location,snippet,fetched,method,assessment,author,post_date,context,last_seen,current)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1) ON CONFLICT(source,target,relation,source_url,location,snippet)
          DO UPDATE SET last_seen=excluded.last_seen,current=1""",
            (
                project,
                source,
                target,
                relation,
                source_url,
                location,
                snippet[:500],
                now(),
                method,
                "one_sided" if relation == "claims_ownership" else "clue",
                extra.get("author", ""),
                extra.get("date", ""),
                extra.get("context", "own"),
                now(),
            ),
        )
        reverse = self.rows(
            "SELECT id FROM evidence WHERE source=? AND target=? AND relation='links' AND decision!='rejected' AND current=1 AND method!='manual_observation'",
            (target, source),
        )
        if relation == "links" and method != 'manual_observation' and reverse:
            self.execute(
                "UPDATE evidence SET assessment='reciprocal' WHERE ((source=? AND target=?) OR (source=? AND target=?)) AND relation='links' AND decision!='rejected' AND current=1 AND method!='manual_observation'",
                (source, target, target, source),
            )

    def remember_address(self, node_id, url):
        node = self.node(node_id)
        self.execute(
            '''INSERT INTO profile_addresses VALUES(?,?,?,?,?) ON CONFLICT(node,url)
          DO UPDATE SET last_seen=excluded.last_seen''',
            (node['project'], node_id, url, now(), now()),
        )

    def apply_profile(self, project, url, data, node_id=None, seed=True, depth=0, partial=False):
        """Deduplicate only exact platform + durable ID; a reused URL is an explicit conflict."""
        item = identify(url)
        existing = self.rows('SELECT * FROM nodes WHERE project=? AND url=?', (project, item['url']))
        stable = str(data.get('stable_id') or '')
        if existing:
            old = json.loads(existing[0]['data']).get('stable_id')
            if stable and old and str(old) != stable:
                self.execute("UPDATE nodes SET state='error' WHERE id=?", (existing[0]['id'],))
                raise ValueError(
                    'Zmiana trwałego ID pod tym samym adresem; wcześniejsze oceny nie zostały przeniesione'
                )
        candidates = (
            self.rows(
                "SELECT * FROM nodes WHERE project=? AND platform=? AND kind='profile'",
                (project, item['platform']),
            )
            if stable
            else []
        )
        same = next(
            (
                n
                for n in candidates
                if str(json.loads(n['data']).get('stable_id') or '') == stable
                and urlsplit(n['url']).hostname == urlsplit(item['url']).hostname
            ),
            None,
        )
        if node_id is not None:
            node = self.node(node_id)
            if node['project'] != project or node['platform'] != item['platform']:
                raise ValueError('Niezgodny projekt lub platforma profilu')
            old = json.loads(node['data']).get('stable_id')
            if old and stable and urlsplit(node['url']).hostname != urlsplit(item['url']).hostname:
                raise ValueError('ID instancji nie potwierdza konta w innej domenie')
            if old and stable and str(old) != stable:
                raise ValueError('Niezgodny trwały identyfikator')
            same = node
        if same and (not existing or existing[0]['id'] == same['id']):
            id = same['id']
            self.remember_address(id, same['url'])
            self.execute('UPDATE nodes SET url=?,kind=? WHERE id=?', (item['url'], item['kind'], id))
        elif same and existing and same['id'] != existing[0]['id']:
            # Do not merge two rows with potentially conflicting human decisions silently.
            raise ValueError('Dwa wpisy tego samego konta wymagają ręcznego przeglądu')
        else:
            id = self.add(project, item['url'], seed=seed, depth=depth)
        self.execute(
            'UPDATE nodes SET seed=MAX(seed,?),depth=MIN(depth,?) WHERE id=?', (int(seed), depth, id)
        )
        self.remember_address(id, item['url'])
        previous = json.loads(self.node(id)['data'])
        if partial:
            data = previous | {k: v for k, v in data.items() if v is not None}
        # The sensitive marker must survive a later full re-read, or exports and the AI
        # packet would start including an adult-site profile the user never opted into.
        from .sensitive import is_sensitive_url, CATEGORY

        if previous.get('sensitive') or data.get('sensitive') or is_sensitive_url(item['url']):
            data = dict(data)
            data['sensitive'] = True
            data.setdefault('sensitive_category', previous.get('sensitive_category', CATEGORY))
        self.execute(
            "UPDATE nodes SET state='found',data=? WHERE id=?",
            (json.dumps(data, ensure_ascii=False, sort_keys=True), id),
        )
        return id

    def snapshot(self, project, scan_limit=None):
        scans = (
            self.rows('SELECT * FROM scans WHERE project=? ORDER BY id', (project,))
            if scan_limit is None
            else list(
                reversed(
                    self.rows(
                        'SELECT * FROM scans WHERE project=? ORDER BY id DESC LIMIT ?',
                        (project, int(scan_limit)),
                    )
                )
            )
        )
        return {
            "projects": self.rows("SELECT * FROM projects WHERE id=?", (project,)),
            "nodes": self.rows("SELECT * FROM nodes WHERE project=? ORDER BY id", (project,)),
            "evidence": self.rows("SELECT * FROM evidence WHERE project=? ORDER BY id", (project,)),
            "scans": scans,
            "focus": self.rows("SELECT * FROM focus WHERE project=?", (project,)),
            'addresses': self.rows('SELECT * FROM profile_addresses WHERE project=?', (project,)),
        }

    def set_focus(self, project, node_id=None):
        if node_id is None:
            self.execute("DELETE FROM focus WHERE project=?", (project,))
            return
        node = self.node(node_id)
        if (
            node['project'] != project
            or node['kind'] not in ('profile', 'page')
            or node['ownership'] == 'not_mine'
        ):
            raise ValueError('Wybierz nieodrzucony profil z tego projektu')
        self.execute("INSERT OR REPLACE INTO focus VALUES(?,?,?)", (project, node_id, now()))

    def compare(self, first, second):
        a, b = [self.rows("SELECT * FROM observations WHERE scan=?", (s,)) for s in (first, second)]
        old = {x["node"]: x for x in a}
        return [
            {
                "node": x["node"],
                "change": (
                    "unavailable"
                    if x["state"] != "found"
                    else (
                        "new"
                        if x["node"] not in old or old[x["node"]]["state"] != "found"
                        else "changed" if x["data"] != old[x["node"]]["data"] else "unchanged"
                    )
                ),
            }
            for x in b
        ]
