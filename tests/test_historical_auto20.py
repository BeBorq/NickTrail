import json
import os
import tempfile
import unittest
from unittest.mock import patch

from nicktrail.archives import after_search, auto_targets
from nicktrail.storage import Store


class Wayback:
    calls = []
    blocked_after = None

    def __init__(self, **kwargs):
        self.count = 0
        self.cooldowns = {}

    def defer_host(self, *a):
        pass

    def get(self, url):
        Wayback.calls.append(url)
        self.count += 1
        if Wayback.blocked_after is not None and len(Wayback.calls) > Wayback.blocked_after:
            return {'state': 'blocked', 'detail': 'HTTP 429; RATE_LIMITED'}
        from urllib.parse import parse_qs, urlsplit
        original = parse_qs(urlsplit(url).query)['url'][0]
        body = {'archived_snapshots': {'closest': {'available': True, 'status': '200',
                'url': 'https://web.archive.org/web/20150101000000/' + original, 'timestamp': '20150101000000'}}}
        return {'state': 'found', 'text': json.dumps(body), 'url': url}


class HistoricalAutoTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, 'h.sqlite3'))
        self.p = self.store.project('fictional')
        self.mine = self.store.apply_profile(self.p, 'https://github.com/seed', {'alias': 'seed', 'stable_id': '1'})
        self.store.decide(self.mine, 'mine')
        self.other = [self.store.apply_profile(self.p, f'https://gitlab.com/n{i}', {'alias': f'n{i}'}) for i in range(4)]
        self.store.decide(self.other[0], 'not_mine')
        Wayback.calls, Wayback.blocked_after = [], None

    def tearDown(self):
        self.store.db.close()
        self.dir.cleanup()

    def test_targets_start_with_your_account_skip_rejected_and_respect_limit(self):
        targets = auto_targets(self.store, self.p, 3)
        self.assertEqual(targets[0], self.mine)
        self.assertNotIn(self.other[0], targets)
        self.assertEqual(len(targets), 3)

    def test_checks_metadata_only_and_stops_on_archive_rate_limit(self):
        with patch('nicktrail.network.Client', Wayback):
            result = after_search(self.store, self.p, '2015-01-01', limit=3)
        self.assertEqual([r['state'] for r in result['results']], ['available'] * 3)
        self.assertTrue(all('archive.org/wayback/available' in u for u in Wayback.calls))
        Wayback.calls, Wayback.blocked_after = [], 1
        self.store.execute('DELETE FROM archive_checks')
        with patch('nicktrail.network.Client', Wayback):
            result = after_search(self.store, self.p, '2016-01-01', limit=3)
        self.assertEqual([r['state'] for r in result['results']], ['available', 'blocked'])


if __name__ == '__main__':
    unittest.main()
