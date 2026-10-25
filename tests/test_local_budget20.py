import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.search import discover, results
from nicktrail.diagnostics import reason


class LocalBudget20Tests(unittest.TestCase):
    def test_enrichment_cooldown_is_pending_not_a_finished_block(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            s = Store(Path(tmp) / 'test.db')
            p = s.project('Fictional')

            class C:
                count = 0

                def get(self, *args, **kwargs):
                    self.count += 1
                    return {'state': 'blocked', 'detail': 'HTTP 429; RATE_LIMITED'}

            try:
                with patch(
                    'nicktrail.search.lookup',
                    return_value={
                        'state': 'found',
                        'matches': [
                            {
                                'url': 'https://www.roblox.com/users/123456789/profile',
                                'data': {'alias': 'fictional', 'stable_id': '123456789'},
                                'evidence': [],
                            }
                        ],
                    },
                ):
                    discover(s, p, 'fictional', platforms=['Roblox'], client=C())
                r = results(s, p)[0]
                self.assertEqual(r['run']['status'], 'paused')
                self.assertTrue(any(t['mode'] == 'enrich' and t['state'] == 'pending' for t in r['tasks']))
            finally:
                s.db.close()

    def test_local_domain_budget_keeps_work_pending_and_can_resume(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            s = Store(Path(tmp) / 'test.db')
            p = s.project('Fictional')

            class C:
                count = 0

            calls = []

            def lookup(platform, term, client):
                calls.append(platform)
                return (
                    {'state': 'blocked', 'detail': 'Limit domeny'}
                    if platform == 'GitHub'
                    else {'state': 'not_found', 'matches': []}
                )

            try:
                with patch('nicktrail.search.lookup', side_effect=lookup):
                    id = discover(
                        s, p, 'fictional', platforms=['GitHub', 'RubyGems'], related=True, client=C()
                    )
                r = results(s, p)[0]
                self.assertEqual(r['run']['status'], 'limited')
                self.assertIn('RubyGems', calls)
                self.assertEqual(reason('blocked', 'Limit domeny'), 'LOCAL_BUDGET_EXHAUSTED')
                self.assertTrue(
                    any(t['platform'] == 'GitHub' and t['state'] == 'pending' for t in r['tasks'])
                )
                with (
                    patch('nicktrail.search.lookup', return_value={'state': 'not_found', 'matches': []}),
                    patch(
                        'nicktrail.searchflow.search_related',
                        return_value={'state': 'not_found', 'matches': []},
                    ),
                ):
                    discover(s, p, resume=id, client=C())
                self.assertFalse(
                    any(t['mode'] == 'exact' and t['state'] == 'pending' for t in results(s, p)[0]['tasks'])
                )
                self.assertTrue(
                    s.rows('SELECT peak_pending FROM search_runtime_metrics WHERE search=?', (id,))[0][
                        'peak_pending'
                    ]
                    >= 2
                )
            finally:
                s.db.close()
