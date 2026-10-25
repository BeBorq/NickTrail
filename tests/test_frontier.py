import json, tempfile, unittest
from pathlib import Path
from nicktrail.storage import Store
from nicktrail.search import schema
from nicktrail.branches import explore, history
from nicktrail.frontier import priorities, ordered_services, snapshot
from nicktrail.engine import scan


class FrontierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.s = Store(str(Path(self.tmp.name) / 'test.db'))
        self.p = self.s.project('Fixture')
        schema(self.s)

    def tearDown(self):
        self.s.db.close()
        self.tmp.cleanup()

    def test_category_priority_keeps_cross_category_exploration(self):
        id = self.s.apply_profile(self.p, 'https://github.com/fixture', {'alias': 'fixture'})
        self.s.decide(id, 'mine')
        records = ordered_services(snapshot(self.s, self.p))
        self.assertEqual(len(records), 100)
        self.assertEqual(records[0]['category'], 'developer')
        self.assertNotEqual(records[2]['category'], 'developer')

    def test_weak_candidate_is_read_but_not_expanded(self):
        a = self.s.apply_profile(self.p, 'https://linktr.ee/exact', {'alias': 'exact'})
        b = self.s.apply_profile(self.p, 'https://linktr.ee/unrelated', {'alias': 'unrelated'})
        self.s.execute(
            'insert into searches(project,nickname,status,options) values(?,?,?,?)',
            (self.p, 'exact', 'completed', json.dumps({'_terms': ['exact'], '_criteria': {}})),
        )

        class Client:
            count = 0
            calls = []

            def get(self, url):
                self.count += 1
                self.calls.append(url)
                link = 'https://example.org/' + ('a' if url.endswith('/exact') else 'b')
                return {
                    'state': 'found',
                    'url': url,
                    'text': '<main><p>Fictional public profile biography with enough visible text for the supported public reader.</p><a href="'
                    + link
                    + '">Website</a></main>',
                }

        c = Client()
        explore(self.s, self.p, [b, a], client=c)
        rows = history(self.s, self.p)[0]['nodes']
        self.assertEqual(c.calls[0], 'https://linktr.ee/exact')
        self.assertTrue(any(n['root'] == a and n['depth'] > 0 for n in rows))
        self.assertFalse(any(n['root'] == b and n['depth'] > 0 for n in rows))
        self.assertIn('Rozwijanie odłożone', next(n for n in rows if n['node'] == b)['detail'])

    def test_late_graph_bridge_revives_previously_weak_root(self):
        a = self.s.apply_profile(self.p, 'https://github.com/reference', {'alias': 'reference'})
        b = self.s.apply_profile(self.p, 'https://github.com/old', {'alias': 'old'})
        x = self.s.add(self.p, 'https://x.com/shared')
        self.s.set_focus(self.p, a)
        scope = {'active': True, 'terms': ['reference'], 'criteria': {}}
        self.assertFalse(priorities(snapshot(self.s, self.p), scope)[b]['expand'])
        self.s.evidence(self.p, a, x, 'links', 'https://github.com/reference', 'bio', 'X')
        self.s.evidence(self.p, b, x, 'links', 'https://github.com/old', 'bio', 'X')
        self.assertTrue(priorities(snapshot(self.s, self.p), scope)[b]['expand'])

    def test_generic_page_read_preserves_structured_fields(self):
        n = self.s.apply_profile(
            self.p,
            'https://personal.example',
            {'alias': 'old', 'display': 'Fictional Name', 'stable_id': 'fixture'},
        )

        class Client:
            count = 0

            def get(self, url):
                self.count += 1
                return {
                    'state': 'found',
                    'url': url,
                    'text': '<main><p>A public personal website biography with sufficiently long visible text but no structured account fields.</p></main>',
                }

        scan(self.s, self.p, targets=[n], client=Client())
        data = json.loads(self.s.node(n)['data'])
        self.assertEqual(data['alias'], 'old')
        self.assertEqual(data['stable_id'], 'fixture')

    def test_probed_profile_does_not_become_confirmed_by_generic_html_on_refresh(self):
        n = self.s.apply_profile(
            self.p, 'https://keybase.io/fixture', {'alias': 'fixture', 'public_probe': 'Keybase'}
        )

        class Client:
            count = 0

            def get(self, url):
                self.count += 1
                return {
                    'state': 'found',
                    'url': url,
                    'text': '<main><p>A generic website welcome screen with sufficiently long visible text but absolutely no profile metadata.</p></main>',
                }

        scan(self.s, self.p, targets=[n], client=Client())
        self.assertEqual(self.s.node(n)['state'], 'partial')

    def test_live_bridge_requeues_expansion_without_second_profile_request(self):
        a = self.s.apply_profile(
            self.p, 'https://github.com/reference', {'alias': 'reference', 'stable_id': '101'}
        )
        b = self.s.apply_profile(self.p, 'https://github.com/old', {'alias': 'old', 'stable_id': '102'})
        self.s.set_focus(self.p, a)
        self.s.execute(
            'insert into searches(project,nickname,status,options) values(?,?,?,?)',
            (self.p, 'reference', 'completed', json.dumps({'_terms': ['reference'], '_criteria': {}})),
        )

        class Client:
            count = 0

            def __init__(self):
                self.calls = []

            def get(self, url):
                self.count += 1
                self.calls.append(url)
                if 'api.github.com' in url:
                    first = url.endswith('/101')
                    data = {
                        'id': 101 if first else 102,
                        'login': 'reference' if first else 'old',
                        'bio': 'https://x.com/shared' + (' https://personal.example' if not first else ''),
                    }
                    return {'state': 'found', 'text': json.dumps(data), 'url': url}
                return {
                    'state': 'found',
                    'url': url,
                    'text': '<main><p>Fictional personal website biography with sufficiently long public content and no external links.</p></main>',
                }

        c = Client()
        explore(self.s, self.p, [a, b], client=c)
        rows = history(self.s, self.p)[0]['nodes']
        self.assertTrue(any(n['root'] == b and n['depth'] > 0 for n in rows))
        self.assertEqual(c.calls.count('https://api.github.com/user/102'), 1)
