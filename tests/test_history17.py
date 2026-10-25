import json, tempfile, unittest
from pathlib import Path
from nicktrail.storage import Store, now
from nicktrail.profilehistory import timeline
from nicktrail.diagnostics import reason


class History17Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / 'test.db')
        self.addCleanup(self.s.db.close)
        self.p = self.s.project('Synthetic')
        self.n = self.s.add(self.p, 'https://github.com/synthetic')

    def observation(self, state, data):
        scan = self.s.execute(
            'insert into scans(project,started,status,queue,options) values(?,?,?,?,?)',
            (self.p, now(), 'completed', '[]', '{}'),
        ).lastrowid
        self.s.execute(
            'insert into observations values(?,?,?,?,?)', (scan, self.n, state, json.dumps(data), 'fixture')
        )
        return scan

    def test_failed_read_does_not_erase_previous_profile_fields(self):
        self.observation('found', {'alias': 'old', 'bio': 'old description'})
        self.observation('blocked', {})
        self.observation('found', {'alias': 'new', 'bio': 'new description'})
        result = timeline(self.s, self.p, self.n)
        self.assertEqual(len(result['observations']), 3)
        self.assertFalse(result['observations'][1]['changes'])
        self.assertEqual({r['field'] for r in result['observations'][0]['changes']}, {'alias', 'bio'})
        self.assertFalse(result['observations'][0]['identity_confirmed'])
        self.assertEqual(self.s.node(self.n)['ownership'], 'unknown')

    def test_project_boundary_and_bounded_results(self):
        with self.assertRaises(ValueError):
            timeline(self.s, self.s.project('Other'), self.n)
        for i in range(4):
            self.observation('found', {'alias': 'synthetic', 'bio': str(i)})
        result = timeline(self.s, self.p, self.n, 2)
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['observations']), 2)
        self.assertFalse(result['observations'][-1]['changes'])

    def test_diagnostic_reasons_preserve_distinct_failures(self):
        for code, detail in [
            ('ROBOTS_RESTRICTED', 'robots.txt unavailable'),
            ('RATE_LIMITED', 'HTTP 429'),
            ('JS_REQUIRED', 'Enable JavaScript'),
            ('PROFILE_ALIAS_MISMATCH', 'PROFILE_ALIAS_MISMATCH: another user'),
            ('PROFILE_SCHEMA_MISMATCH', 'PROFILE_SCHEMA_MISMATCH: bad shape'),
            ('SOFT_404', 'soft-404'),
        ]:
            self.assertEqual(reason('partial', detail), code)
        self.assertEqual(reason('blocked'), 'BLOCKED_BY_PLATFORM')
