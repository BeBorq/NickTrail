"""rc15: one refusing or misbehaving site must not stop the whole search."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nicktrail.search import discover, results
from nicktrail.storage import Store


class Client:
    count = 0


class SearchResilience(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, 'r.sqlite3'))
        self.p = self.store.project('Fictional')

    def tearDown(self):
        self.store.db.close(); self.dir.cleanup()

    def tasks(self):
        return {(t['platform'], t['mode']): t for t in results(self.store, self.p)[0]['tasks']}

    def test_unexpected_error_on_one_site_skips_it_and_continues(self):
        def lookup(platform, term, client):
            if platform == 'GitHub':
                raise RuntimeError('odd response')
            return {'state': 'not_found', 'detail': 'brak'}
        with patch('nicktrail.search.lookup', side_effect=lookup):
            id = discover(self.store, self.p, 'fictional', platforms=['GitHub', 'GitLab'], client=Client())
        status = self.store.rows('SELECT status FROM searches WHERE id=?', (id,))[0]['status']
        self.assertEqual(status, 'completed')
        tasks = self.tasks()
        self.assertEqual(tasks[('GitHub', 'exact')]['state'], 'error')
        self.assertIn('RuntimeError', tasks[('GitHub', 'exact')]['detail'])
        self.assertEqual(tasks[('GitLab', 'exact')]['state'], 'not_found')
        log = os.path.join(self.dir.name, 'r.sqlite3.errors.log')
        self.assertTrue(os.path.exists(log))
        self.assertIn('odd response', Path(log).read_text(encoding='utf-8'))

    def test_rate_limited_task_is_given_up_after_three_rounds(self):
        calls = []
        def lookup(platform, term, client):
            calls.append(platform)
            if platform == 'GitHub':
                return {'state': 'blocked', 'detail': 'HTTP 429; RATE_LIMITED'}
            return {'state': 'not_found', 'detail': 'brak'}
        with patch('nicktrail.search.lookup', side_effect=lookup):
            id = discover(self.store, self.p, 'fictional', platforms=['GitHub', 'GitLab'], client=Client())
            self.assertEqual(self.tasks()[('GitHub', 'exact')]['state'], 'pending')
            # Another platform was not held up by the refusing one.
            self.assertEqual(self.tasks()[('GitLab', 'exact')]['state'], 'not_found')
            discover(self.store, self.p, resume=id, client=Client())
            discover(self.store, self.p, resume=id, client=Client())
        github = self.tasks()[('GitHub', 'exact')]
        self.assertEqual(github['state'], 'blocked')
        self.assertIn('3 razy', github['detail'])
        self.assertEqual(calls.count('GitHub'), 3)


if __name__ == '__main__':
    unittest.main()
