"""Estimated finish time of a search from the pace of its recently finished tasks.

Each task gets a finish timestamp (SQLite trigger), so the estimate also works
after a restart.  Different task kinds (catalog probes, API lookups, weak
searches) have very different costs, so each kind uses its own recent pace when
there are enough samples.  This is an estimate of the planned work, not a
promise: limits, pauses, new queue items and service slowdowns change it.
"""

import time
from datetime import datetime, timedelta, timezone

SAMPLE = 40
MIN_SAMPLE = 5


def schema(store):
    columns = {r['name'] for r in store.rows('PRAGMA table_info(search_tasks)')}
    if 'finished' not in columns:
        store.execute('ALTER TABLE search_tasks ADD COLUMN finished TEXT')
    store.execute(
        """CREATE TRIGGER IF NOT EXISTS search_tasks_finished AFTER UPDATE OF state ON search_tasks
        WHEN NEW.state NOT IN ('pending','searching') AND (OLD.state IN ('pending','searching') OR OLD.finished IS NULL)
        BEGIN UPDATE search_tasks SET finished=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE rowid=NEW.rowid; END"""
    )


def _kind(mode):
    mode = (mode or '').split('|')[0]
    return mode if mode in ('probe', 'exact', 'enrich') else 'other'


def _parse(value):
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)


def _pace(times):
    """Tasks per second over the sample, ignoring idle gaps longer than 2 minutes (pauses/restarts)."""
    times = sorted(times)
    busy = sum(min(120.0, (b - a).total_seconds()) for a, b in zip(times, times[1:]))
    return (len(times) - 1) / busy if busy > 0 and len(times) >= MIN_SAMPLE else None


WAIT_WORDS = (
    'http 429',
    'rate_limited',
    'przerwa zalecona przez api',
    'retry-after',
    'limit domeny',
    'local_domain_budget',
)


def waiting(store, pending):
    """Why the remaining tasks wait: grouped by service, with any active provider cooldown."""
    groups = {}
    for r in pending:
        detail = (r['detail'] or '').strip()
        reason = 'limit' if any(w in detail.casefold() for w in WAIT_WORDS) else 'queue'
        key = (r['platform'], reason)
        groups.setdefault(
            key, {'platform': r['platform'], 'reason': reason, 'tasks': 0, 'detail': detail[:160]}
        )['tasks'] += 1
    from .cooldowns import waiting as cooldown_waiting

    cd = cooldown_waiting(store)
    cooldowns = [
        {
            'host': h['host'],
            'until': datetime.fromtimestamp(h['until_epoch'], timezone.utc).isoformat(timespec='seconds'),
            'until_epoch': h['until_epoch'],
            'blocks': h['blocks'],
        }
        for h in cd['hosts']
    ]
    return {
        'groups': sorted(groups.values(), key=lambda g: -g['tasks']),
        'cooldowns': cooldowns,
        'now_epoch': cd['now_epoch'],
        'total_blocks': cd['total_blocks'],
    }


def estimate(store, search_id, now=None, running=True):
    if search_id is None:
        return None
    now = now or datetime.now(timezone.utc)
    rows = store.rows(
        "SELECT platform,mode,state,detail,finished FROM search_tasks WHERE search=?", (search_id,)
    )
    pending = [r for r in rows if r['state'] in ('pending', 'searching')]
    finished = sorted((r for r in rows if r['finished']), key=lambda r: r['finished'], reverse=True)
    if not pending:
        return {'state': 'done', 'pending': 0}
    if not running:
        # Nothing is working on the queue, so a finish time would be fiction.
        return {
            'state': 'paused',
            'pending': len(pending),
            'waiting': waiting(store, pending),
            'detail': 'Wyszukiwanie nie trwa. Pozostałe zadania czekają na wznowienie.',
        }
    overall = _pace([_parse(r['finished']) for r in finished[:SAMPLE]])
    if overall is None:
        return {
            'state': 'warming_up',
            'pending': len(pending),
            'detail': 'Za mało ukończonych zadań, żeby oszacować czas.',
        }
    seconds = 0.0
    by_kind = {}
    for kind in {_kind(r['mode']) for r in pending}:
        count = sum(_kind(r['mode']) == kind for r in pending)
        pace = (
            _pace([_parse(r['finished']) for r in finished if _kind(r['mode']) == kind][:SAMPLE]) or overall
        )
        by_kind[kind] = {'pending': count, 'tasks_per_minute': round(pace * 60, 1)}
        seconds += count / pace
    last = _parse(finished[0]['finished'])
    idle = (now - last).total_seconds()
    return {
        'state': 'estimate',
        'pending': len(pending),
        'eta_seconds': round(seconds),
        'finish_at': (now + timedelta(seconds=seconds)).isoformat(timespec='seconds'),
        'tasks_per_minute': round(overall * 60, 1),
        'by_kind': by_kind,
        'stalled': idle > 120,
        'waiting': waiting(store, pending),
        'detail': 'Szacunek z tempa ostatnich zadań. Limity rundy, przerwy serwisów i nowe zadania w kolejce mogą go zmienić.',
    }
