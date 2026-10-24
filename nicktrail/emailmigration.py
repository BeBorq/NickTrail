"""Explicit, backed-up migration of existing e-mail nodes to canonical mailbox keys.

New observations already reuse one node per mailbox (`Store._add_email`).  This
migration normalizes rows stored before that change:

* a lone e-mail node is renamed to its canonical key; the old exact address is
  kept in ``data.published_forms``;
* several nodes of one mailbox are merged into one only when it is safe:
  their ownership decisions agree (``unknown`` is compatible with anything),
  and every row referencing a duplicate can be moved without colliding with an
  existing row.  Otherwise the group is left untouched and reported, so no user
  decision or evidence row is ever dropped;
* evidence rows keep their IDs and decisions; only their endpoint is moved.

`plan()` is read-only.  `apply()` first writes a full SQLite backup, then runs
in one transaction and records itself in ``schema_migrations``; running it
again finds nothing to do.  Profile nodes and HIBP checks are not touched.
"""
import json
import os
import sqlite3
import time

from .emailid import canonical_key

NAME = 'email_canonical_v1'
# Columns holding JSON lists of node IDs (no foreign key can protect them).
JSON_NODE_LISTS = (('scans', 'queue'), ('scans', 'visited'), ('search_sources', 'nodes'), ('search_tasks', 'nodes'))


def _data(raw):
    try:
        value = json.loads(raw or '{}')
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _groups(db):
    out, invalid = {}, []
    for row in db.execute("SELECT id,project,url,ownership,data FROM nodes WHERE kind='email' ORDER BY id"):
        try:
            key = canonical_key(row['url'])[0]
        except ValueError:
            invalid.append(row['id'])
            continue
        out.setdefault((row['project'], key), []).append(dict(row))
    return out, invalid


def plan(store):
    """Describe what apply() would do. Never writes."""
    db = store.db
    groups, invalid = _groups(db)
    renames, merges, conflicts = [], [], []
    for (project, key), rows in sorted(groups.items()):
        if len(rows) == 1:
            if rows[0]['url'] != key:
                taken = db.execute('SELECT id FROM nodes WHERE project=? AND url=?', (project, key)).fetchone()
                if taken:
                    conflicts.append({'project': project, 'nodes': [rows[0]['id'], taken['id']],
                                      'reason': 'Kanoniczny adres jest już zajęty przez inny wpis'})
                else:
                    renames.append({'project': project, 'node': rows[0]['id']})
            continue
        decisions = {r['ownership'] for r in rows} - {'unknown'}
        if len(decisions) > 1:
            conflicts.append({'project': project, 'nodes': [r['id'] for r in rows],
                              'reason': 'Sprzeczne decyzje własności; wymaga ręcznej oceny'})
            continue
        survivor = next((r for r in rows if r['url'] == key), rows[0])
        merges.append({'project': project, 'survivor': survivor['id'],
                       'duplicates': [r['id'] for r in rows if r['id'] != survivor['id']]})
    return {'migration': NAME, 'renames': renames, 'merges': merges, 'conflicts': conflicts,
            'invalid_nodes': invalid,
            'note': 'Adresy nie są wypisywane. Sprawdzanie HIBP i profile kont nie są zmieniane.'}


def _references(db):
    refs = []
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        for fk in db.execute(f'PRAGMA foreign_key_list("{table}")'):
            if fk[2] == 'nodes':
                refs.append((table, fk[3]))
    return refs


def _move_json_lists(db, duplicate, survivor):
    for table, column in JSON_NODE_LISTS:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            continue
        if column not in {c[1] for c in db.execute(f'PRAGMA table_info("{table}")')}:
            continue
        for rowid, raw in db.execute(f'SELECT rowid,"{column}" FROM "{table}" WHERE "{column}" LIKE ?', ('%' + str(duplicate) + '%',)).fetchall():
            try:
                values = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(values, list) or duplicate not in values:
                continue
            moved = list(dict.fromkeys(survivor if v == duplicate else v for v in values))
            db.execute(f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?', (json.dumps(moved), rowid))


def _merge(db, refs, survivor, duplicates):
    """Move every reference; return the blocking table if any row would collide."""
    for duplicate in duplicates:
        for table, column in refs:
            db.execute(f'UPDATE OR IGNORE "{table}" SET "{column}"=? WHERE "{column}"=?', (survivor, duplicate))
            if db.execute(f'SELECT 1 FROM "{table}" WHERE "{column}"=? LIMIT 1', (duplicate,)).fetchone():
                return table
        _move_json_lists(db, duplicate, survivor)
    rows = [dict(r) for r in db.execute('SELECT * FROM nodes WHERE id IN (%s)' % ','.join('?' * (len(duplicates) + 1)),
                                        (survivor, *duplicates))]
    keep = next(r for r in rows if r['id'] == survivor)
    data = _data(keep['data'])
    forms = set(data.get('published_forms', []))
    for r in rows:
        forms |= set(_data(r['data']).get('published_forms', []))
        forms.add(r['url'])
    ownership = next((r['ownership'] for r in rows if r['ownership'] != 'unknown'), 'unknown')
    db.execute('DELETE FROM nodes WHERE id IN (%s)' % ','.join('?' * len(duplicates)), duplicates)
    key = canonical_key(keep['url'])[0]
    data['published_forms'] = sorted(f for f in forms if f != key)[:20]
    if not data['published_forms']:
        del data['published_forms']
    db.execute('UPDATE nodes SET url=?,ownership=?,seed=?,depth=?,data=? WHERE id=?',
               (key, ownership, max(r['seed'] for r in rows), min(r['depth'] for r in rows),
                json.dumps(data, ensure_ascii=False, sort_keys=True), survivor))
    return None


def apply(store, db_path, backup_dir=None):
    """Back up the database, then apply the plan in one transaction."""
    proposal = plan(store)
    db = store.db
    if not (proposal['renames'] or proposal['merges']):
        return proposal | {'applied': False, 'backup': None, 'blocked': []}
    db.execute('CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY,applied TEXT,summary TEXT)')
    db.commit()
    stamp = time.strftime('%Y%m%d-%H%M%S')
    target_dir = backup_dir or os.path.dirname(os.path.abspath(db_path))
    backup_path = os.path.join(target_dir, os.path.basename(db_path) + '.before-' + NAME + '-' + stamp + '.sqlite3')
    backup = sqlite3.connect(backup_path)
    try:
        db.backup(backup)
    finally:
        backup.close()
    refs = _references(db)
    blocked = []
    previous = db.isolation_level
    db.isolation_level = None
    try:
        db.execute('BEGIN IMMEDIATE')
        for item in proposal['renames']:
            row = db.execute('SELECT url,data FROM nodes WHERE id=?', (item['node'],)).fetchone()
            data = _data(row['data'])
            data['published_forms'] = sorted(set(data.get('published_forms', [])) | {row['url']})[:20]
            db.execute('UPDATE nodes SET url=?,data=? WHERE id=?',
                       (canonical_key(row['url'])[0], json.dumps(data, ensure_ascii=False, sort_keys=True), item['node']))
        for item in proposal['merges']:
            db.execute('SAVEPOINT email_group')
            table = _merge(db, refs, item['survivor'], item['duplicates'])
            if table:
                db.execute('ROLLBACK TO email_group')
                blocked.append(item | {'reason': 'Kolizja wierszy w tabeli ' + table + '; grupa pozostawiona bez zmian'})
            db.execute('RELEASE email_group')
        summary = {'renamed': len(proposal['renames']), 'merged_groups': len(proposal['merges']) - len(blocked),
                   'blocked': len(blocked), 'conflicts': len(proposal['conflicts'])}
        db.execute('INSERT OR REPLACE INTO schema_migrations VALUES(?,?,?)',
                   (NAME, time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), json.dumps(summary)))
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise
    finally:
        db.isolation_level = previous
    return proposal | {'applied': True, 'backup': backup_path, 'blocked': blocked, 'summary': summary}
