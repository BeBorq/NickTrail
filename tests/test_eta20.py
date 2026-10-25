import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from nicktrail.eta import estimate
from nicktrail.search import schema
from nicktrail.storage import Store


class EtaTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, 'e.sqlite3'))
        schema(self.store)
        project = self.store.project('p')
        self.search = self.store.execute(
            "INSERT INTO searches(project,nickname,started,status,options) VALUES(?,?,?,?,?)",
            (project, 'x', '', 'running', '{}'),
        ).lastrowid

    def tearDown(self):
        self.store.db.close()
        self.dir.cleanup()

    def add(self, n, mode, state='pending'):
        for i in range(n):
            self.store.execute(
                'INSERT INTO search_tasks(search,platform,term,mode,state) VALUES(?,?,?,?,?)',
                (
                    self.search,
                    'Free',
                    f'{mode}{i}:{len(self.store.rows("SELECT 1 FROM search_tasks"))}',
                    mode,
                    state,
                ),
            )

    def test_trigger_stamps_finished_tasks_and_estimate_uses_pace_per_kind(self):
        self.add(30, 'probe')
        self.add(4, 'exact')
        self.assertEqual(estimate(self.store, self.search)['state'], 'warming_up')
        self.store.execute("UPDATE search_tasks SET state='not_found' WHERE rowid<=10")
        self.assertEqual(
            self.store.rows("SELECT count(*) n FROM search_tasks WHERE finished IS NOT NULL")[0]['n'], 10
        )
        base = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
        for i in range(10):  # one probe every 2 s
            self.store.execute(
                'UPDATE search_tasks SET finished=? WHERE rowid=?',
                ((base + timedelta(seconds=2 * i)).strftime('%Y-%m-%dT%H:%M:%S.%fZ'), i + 1),
            )
        result = estimate(self.store, self.search, now=base + timedelta(seconds=20))
        self.assertEqual(result['state'], 'estimate')
        self.assertEqual(result['pending'], 24)
        self.assertEqual(result['by_kind']['probe']['tasks_per_minute'], 30.0)
        self.assertAlmostEqual(result['eta_seconds'], 24 * 2, delta=1)
        self.assertFalse(result['stalled'])
        self.assertTrue(estimate(self.store, self.search, now=base + timedelta(minutes=30))['stalled'])

    def test_pauses_do_not_inflate_pace_and_done_state(self):
        self.add(8, 'probe', 'not_found')
        base = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
        stamps = [0, 1, 2, 3, 3600, 3601, 3602, 3603]  # a one-hour pause in the middle
        for i, s in enumerate(stamps):
            self.store.execute(
                'UPDATE search_tasks SET finished=? WHERE rowid=?',
                ((base + timedelta(seconds=s)).strftime('%Y-%m-%dT%H:%M:%S.%fZ'), i + 1),
            )
        self.add(10, 'probe')
        result = estimate(self.store, self.search, now=base + timedelta(seconds=3604))
        self.assertLess(result['eta_seconds'], 200)
        self.store.execute("UPDATE search_tasks SET state='not_found'")
        self.assertEqual(estimate(self.store, self.search)['state'], 'done')


if __name__ == '__main__':
    unittest.main()
