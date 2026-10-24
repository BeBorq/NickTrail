import os
import tempfile
import time
import unittest
from unittest import mock

from nicktrail import autoresume
from nicktrail.cooldowns import schema as cooldown_schema
from nicktrail.search import schema as search_schema
from nicktrail.storage import Store


class CooldownWaitTests(unittest.TestCase):
    """A search left only with tasks paused by a provider's HTTP 429 must not stop at 99%."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, 'c.sqlite3'))
        search_schema(self.store); cooldown_schema(self.store)
        self.p = self.store.project('fictional')
        self.store.execute("INSERT INTO searches(project,nickname,started,status,options) VALUES(?,?,?,?,?)", (self.p, 'nick', '2026-10-22T21:00:00', 'paused', '{}'))
        self.id = self.store.rows('SELECT id FROM searches')[0]['id']
        self.store.execute("INSERT INTO search_tasks(search,platform,term,mode,state,detail) VALUES(?,?,?,?,?,?)", (self.id, 'Roblox', 'nick', 'related', 'pending', 'Przerwa zalecona przez API'))
        self.calls = []

    def tearDown(self):
        self.store.db.close(); self.dir.cleanup()

    def fake_discover(self, store, project, resume=None, stopped=None, stop_after_exact=False):
        self.calls.append(time.time())
        store.execute("UPDATE search_tasks SET state='found',detail='' WHERE search=?", (resume,))
        store.execute("UPDATE searches SET status='completed' WHERE id=?", (resume,))

    def cooldown(self, seconds):
        self.store.execute('INSERT INTO provider_cooldowns(host,until_epoch,updated,blocks) VALUES(?,?,?,?)', ('users.roblox.com', time.time() + seconds, time.time(), 6))

    def run_search(self, stopped=lambda: False):
        with mock.patch('nicktrail.search.discover', self.fake_discover):
            return autoresume.search(self.store, self.p, self.id, stopped, lambda: time.sleep(0.1) or stopped())

    def test_waits_out_a_short_provider_pause_then_finishes(self):
        self.cooldown(1.5)
        started = time.time()
        self.run_search()
        self.assertEqual(len(self.calls), 1)
        self.assertGreaterEqual(self.calls[0] - started, 1.5)
        self.assertEqual(self.store.rows("SELECT state FROM search_tasks")[0]['state'], 'found')

    def test_long_pause_is_not_waited_for(self):
        self.cooldown(3600)
        self.run_search()
        self.assertEqual(self.calls, [])
        # rc15: a long pause no longer leaves the whole search hanging; the refusing
        # task is closed as blocked (manual check) and the search can finish.
        task = self.store.rows('SELECT state,detail FROM search_tasks')[0]
        self.assertEqual(task['state'], 'blocked')
        self.assertIn('Sprawdź ręcznie', task['detail'])
        self.assertEqual(self.store.rows('SELECT status FROM searches')[0]['status'], 'completed')

    def test_stop_interrupts_the_wait(self):
        self.cooldown(60)
        started = time.time()
        self.run_search(stopped=lambda: time.time() - started > 0.3)
        self.assertEqual(self.calls, [])
        self.assertLess(time.time() - started, 5)

    def test_eta_reports_paused_search_instead_of_a_finish_time(self):
        from nicktrail.eta import estimate, schema
        schema(self.store); self.cooldown(60)
        out = estimate(self.store, self.id, running=False)
        self.assertEqual(out['state'], 'paused')
        self.assertEqual(out['waiting']['groups'][0]['platform'], 'Roblox')
        self.assertEqual(out['waiting']['groups'][0]['reason'], 'limit')
        self.assertTrue(out['waiting']['cooldowns'])
        self.assertEqual(out['waiting']['cooldowns'][0]['blocks'], 6)
        self.assertIn('now_epoch', out['waiting'])


if __name__ == '__main__':
    unittest.main()
