"""Single active network worker per database and explicit crash recovery."""

from contextlib import contextmanager
from pathlib import Path
import json, os
from .storage import now


@contextmanager
def exclusive_runtime(db_path):
    if str(db_path) == ':memory:':
        yield
        return
    path = Path(str(db_path) + '.runtime.lock')
    stream = path.open('a+b')
    try:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError(
                'Inna instancja NickTrail wykonuje operacje sieciowe na tej bazie. Użyj istniejącego panelu lub innej bazy.'
            ) from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        stream.close()


def recover(store):
    """Call only after acquiring the database runtime lock."""
    tables = {r['name'] for r in store.rows("SELECT name FROM sqlite_master WHERE type='table'")}
    counts = {}
    for table in ('searches', 'scans', 'branch_runs'):
        if table not in tables:
            continue
        rows = store.rows(f"SELECT id FROM {table} WHERE status='running'")
        for row in rows:
            store.execute(f"UPDATE {table} SET status='paused',finished=? WHERE id=?", (now(), row['id']))
            if table == 'branch_runs' and 'branch_nodes' in tables:
                store.execute(
                    "UPDATE branch_nodes SET state='pending' WHERE run=? AND state='searching'", (row['id'],)
                )
            if table == 'searches' and 'search_tasks' in tables:
                store.execute(
                    "UPDATE search_tasks SET state='pending' WHERE search=? AND state='searching'",
                    (row['id'],),
                )
        counts[table] = len(rows)
    return counts
