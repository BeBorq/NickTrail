import json, tempfile, unittest
from pathlib import Path
from nicktrail.storage import Store
from nicktrail.search import schema, discover
from nicktrail.variants import proposals
from nicktrail.independence import group, provenance
from nicktrail.branches import explore


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / 'test.db')
        self.addCleanup(self.s.db.close)
        self.p = self.s.project('Synthetic')
        schema(self.s)

    def test_variants_are_bounded_and_never_invent_suffixes(self):
        self.assertEqual(proposals(['simple']), [])
        aliases = [r['alias'] for r in proposals(['test_user', 'testuser'])]
        self.assertEqual(aliases, ['test-user', 'test.user'])
        self.assertLessEqual(len(proposals(['first_user', 'second_user', 'third_user', 'fourth_user'])), 8)

    def test_variants_follow_exact_stage_and_survive_resume(self):
        class Client:
            count = 0

            def get(self, url):
                raise AssertionError('Stopped queue must not perform HTTP')

        id = discover(
            self.s, self.p, 'test_user', ['GitHub'], client=Client(), variants=True, stopped=lambda: True
        )
        tasks = self.s.rows('select * from search_tasks where search=?', (id,))
        self.assertTrue(any(t['mode'] == 'variant' for t in tasks))
        self.assertEqual(len(self.s.rows('select * from search_variants where search=?', (id,))), 3)
        discover(self.s, self.p, resume=id, client=Client(), stopped=lambda: True)
        self.assertEqual(len(tasks), len(self.s.rows('select * from search_tasks where search=?', (id,))))

    def test_origin_key_recovers_uncheckpointed_branch(self):
        root = self.s.add(self.p, 'https://linktr.ee/synthetic')

        class Client:
            count = 0

        first = explore(
            self.s, self.p, [root], client=Client(), stopped=lambda: True, origin_key='search:1:batch:0'
        )
        second = explore(
            self.s, self.p, [root], client=Client(), stopped=lambda: True, origin_key='search:1:batch:0'
        )
        self.assertEqual(first, second)
        self.assertEqual(len(self.s.rows('select * from branch_runs')), 1)
        self.assertEqual(len(self.s.rows('select * from branch_nodes')), 1)
        self.s.execute("update branch_runs set status='completed' where id=?", (first,))
        self.assertEqual(
            explore(self.s, self.p, [root], client=Client(), origin_key='search:1:batch:0'), first
        )

    def test_pages_of_one_website_are_one_source(self):
        a = {'id': 1, 'url': 'https://www.synthetic.example/about', 'kind': 'page', 'platform': 'Strona'}
        self.assertEqual(group(a), group(a | {'id': 2, 'url': 'https://synthetic.example/contact'}))
        b = {
            'id': 3,
            'url': 'https://github.com/synthetic',
            'kind': 'profile',
            'platform': 'GitHub',
            'data': '{}',
        }
        self.assertNotEqual(group(a), group(b))
        self.assertEqual(
            group(b | {'data': json.dumps({'stable_id': 42})}),
            group(b | {'url': 'https://github.com/renamed', 'data': json.dumps({'stable_id': 42})}),
        )

    def test_provenance_preserves_rejected_and_stale_status(self):
        node = {'id': 1, 'url': 'https://synthetic.example', 'kind': 'page', 'platform': 'Strona'}
        result = provenance(
            {
                'nodes': [node],
                'evidence': [
                    {
                        'id': 5,
                        'source': 1,
                        'source_url': node['url'],
                        'method': 'parser',
                        'current': 0,
                        'decision': 'rejected',
                    }
                ],
            }
        )
        self.assertFalse(result['5']['current'])

    def test_ranking_counts_one_website_once_and_rejected_edges_never(self):
        from nicktrail.engine import record
        from nicktrail.ranking import evaluate

        root = self.s.apply_profile(self.p, 'https://github.com/synthetic', {'alias': 'synthetic'})
        for path in ('about', 'contact', 'bio'):
            source = self.s.apply_profile(self.p, 'https://synthetic.example/' + path, {'title': 'Synthetic'})
            record(
                self.s,
                self.s.node(source),
                [
                    {
                        'url': self.s.node(root)['url'],
                        'relation': 'links',
                        'location': 'bio',
                        'snippet': 'public link',
                    }
                ],
            )
        result = evaluate(self.s.snapshot(self.p))['nodes'][str(root)]
        self.assertEqual(result['raw_link_count'], 3)
        self.assertEqual(result['link_count'], 1)
        self.s.execute("update evidence set decision='rejected'")
        result = evaluate(self.s.snapshot(self.p))['nodes'][str(root)]
        self.assertEqual(result['link_count'], 0)
