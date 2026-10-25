import tempfile, json, unittest
from pathlib import Path
from nicktrail.storage import Store
from nicktrail.search import schema, results
from nicktrail.diagnostics import manual_queue, completeness
from nicktrail.manualreview import resolve


class Manual18Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / 'm.db')
        self.addCleanup(self.s.db.close)
        self.p = self.s.project('Synthetic')
        schema(self.s)
        self.search = self.s.execute(
            'insert into searches(project,status,options) values(?,?,?)',
            (self.p, 'completed', json.dumps({'_terms': ['fictional'], '_platforms': ['GitHub']})),
        ).lastrowid
        self.s.execute(
            'insert into search_tasks(search,platform,term,mode,state,detail) values(?,?,?,?,?,?)',
            (self.search, 'GitHub', 'fictional', 'exact', 'blocked', 'HTTP 429'),
        )

    def item(self):
        return next(r for r in results(self.s, self.p) if r['run']['id'] == self.search)

    def test_manual_mine_is_not_automatic_existence_and_stays_in_normal_project(self):
        q = manual_queue(self.item(), self.s)[0]
        self.assertEqual(q['url'], 'https://github.com/fictional')
        r = resolve(self.s, self.p, self.search, 'GitHub', 'fictional', 'exact', 'mine', q['url'])
        node = self.s.node(r['node'])
        self.assertEqual(node['ownership'], 'mine')
        self.assertEqual(node['state'], 'unverified')
        self.assertEqual(r['network_calls'], 0)
        self.assertEqual(manual_queue(self.item(), self.s)[0]['review']['status'], 'mine')
        report = completeness(self.item(), self.s, self.s.snapshot(self.p))
        self.assertEqual(report['outcome_report']['manual_checks_remaining'], 0)
        resolve(self.s, self.p, self.search, 'GitHub', 'fictional', 'exact', 'unresolved')
        self.assertEqual(self.s.node(r['node'])['ownership'], 'mine')
        self.assertEqual(manual_queue(self.item(), self.s)[0]['review']['node'], r['node'])

    def test_cross_project_or_unlisted_source_or_wrong_platform_is_refused(self):
        with self.assertRaises(ValueError):
            resolve(
                self.s,
                self.s.project('Other'),
                self.search,
                'GitHub',
                'fictional',
                'exact',
                'mine',
                'https://github.com/fictional',
            )
        with self.assertRaises(ValueError):
            resolve(
                self.s,
                self.p,
                self.search,
                'Missing',
                'fictional',
                'exact',
                'mine',
                'https://github.com/fictional',
            )
        with self.assertRaises(ValueError):
            resolve(
                self.s,
                self.p,
                self.search,
                'GitHub',
                'fictional',
                'exact',
                'mine',
                'https://dev.to/fictional',
            )

    def test_index_results_become_individual_manual_items(self):
        node = self.s.add(self.p, 'https://github.com/indexed')
        self.s.execute(
            'insert into search_tasks(search,platform,term,mode,state,nodes) values(?,?,?,?,?,?)',
            (self.search, 'SearXNG', 'fictional', 'context', 'found', json.dumps([node])),
        )
        q = next(q for q in manual_queue(self.item(), self.s) if q['status'] == 'INDEX_ONLY')
        self.assertEqual(q['node'], node)
        r = resolve(self.s, self.p, self.search, 'SearXNG', q['term'], q['mode'], 'not_mine', q['url'])
        self.assertEqual(self.s.node(r['node'])['ownership'], 'not_mine')

    def test_application_home_cannot_be_declared_as_public_account(self):
        with self.assertRaises(ValueError):
            resolve(self.s, self.p, self.search, 'GitHub', 'fictional', 'exact', 'mine', 'https://x.com/home')

    def test_exact_manual_check_precedes_many_weak_items_and_reviewed_moves_last(self):
        search = self.s.execute(
            'insert into searches(project,status,options) values(?,?,?)',
            (self.p, 'completed', json.dumps({'_terms': ['fictional'], '_platforms': ['GitHub']})),
        ).lastrowid
        for i in range(40):
            self.s.execute(
                'insert into search_tasks(search,platform,term,mode,state,detail) values(?,?,?,?,?,?)',
                (search, 'GitHub', 'weak' + str(i), 'related', 'partial', 'weak fixture'),
            )
        self.s.execute(
            'insert into search_tasks(search,platform,term,mode,state,detail) values(?,?,?,?,?,?)',
            (search, 'GitHub', 'fictional', 'exact', 'blocked', 'ROBOTS_RESTRICTED'),
        )
        item = next(r for r in results(self.s, self.p) if r['run']['id'] == search)
        queue = manual_queue(item, self.s)
        self.assertEqual(queue[0]['alias'], 'fictional')
        self.assertIn('Dokładny podany alias', queue[0]['priority_reason'])
        self.assertFalse(queue[0]['priority_is_identity_confidence'])
        resolve(self.s, self.p, search, 'GitHub', 'fictional', 'exact', 'mine', queue[0]['url'])
        self.assertEqual(manual_queue(item, self.s)[-1]['alias'], 'fictional')
