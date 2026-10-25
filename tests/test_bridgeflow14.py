import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.engine import record, scan
from nicktrail.bridgeflow import run, preview
from nicktrail.network import Limit


class LoopFixture:
    def __init__(self, maximum=80):
        self.count = 0
        self.calls = []
        self.maximum = maximum
        self.cache = {}

    def get(self, url, **kw):
        if url in self.cache:
            return self.cache[url]
        if self.count >= self.maximum:
            raise Limit('fixture budget')
        self.count += 1
        self.calls.append(url)
        if url.startswith(('https://api.github.com/users/', 'https://api.github.com/user/')):
            alias = url.rsplit('/', 1)[-1]
            alias = {'1': 'seed', '2': 'completely-old'}.get(alias, alias)
            body = {
                'id': 1 if alias == 'seed' else 2,
                'login': alias,
                'bio': 'public profile',
                'blog': 'https://personal.example' if alias == 'seed' else '',
            }
            text = json.dumps(body)
        elif url == 'https://personal.example':
            text = '<p>Public personal homepage with a biography long enough for normal public HTML reading. Welcome to my website.</p>'
        elif url.endswith('robots.txt'):
            text = 'User-agent: *\nDisallow: /private'
        elif url.endswith('sitemap.xml'):
            text = '<urlset><url><loc>https://personal.example/about</loc></url><url><loc>https://personal.example/private</loc></url></urlset>'
        elif url.endswith('/about'):
            text = '<p>My public biography and a link to a very old account with a different username, now used for development.</p><a rel="me" href="https://github.com/completely-old">Code</a>'
        else:
            return {'state': 'not_found', 'detail': 'fixture HTTP 404'}
        result = {'state': 'found', 'text': text, 'url': url}
        self.cache[url] = result
        return result


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.s = Store(str(Path(self.tmp.name) / 't.db'))
        self.p = self.s.project('Fictional')
        self.root = self.s.add(self.p, 'https://github.com/seed')
        self.s.set_focus(self.p, self.root)

    def tearDown(self):
        self.s.db.close()
        self.tmp.cleanup()

    def test_difficult_chain_generates_different_alias_and_records_provenance(self):
        c = LoopFixture()
        result = run(self.s, self.p, self.root, platforms=['GitHub'], client=c)
        aliases = [l for l in result['leads'] if l['kind'] == 'alias']
        self.assertIn('completely-old', [l['value'] for l in aliases])
        old = next(l for l in aliases if l['value'] == 'completely-old')
        self.assertEqual(len(old['evidence']), 3)
        self.assertTrue(any('users/completely-old' in u for u in c.calls))
        self.assertLessEqual(result['requests'], 80)
        self.assertEqual(self.s.node(self.root)['state'], 'found')
        self.assertTrue(
            all(n['state'] == 'found' for n in self.s.rows("select state from nodes where platform='GitHub'"))
        )
        self.assertEqual(self.s.rows("select count(*) n from nodes where ownership!='unknown'")[0]['n'], 0)
        self.assertFalse(self.s.rows("select * from nodes where kind='alias'"))
        self.assertTrue(self.s.rows("select * from candidate_hints where basis='derived_public_lead'"))
        self.assertTrue(
            self.s.rows(
                "select * from observations o join nodes n on n.id=o.node where n.url='https://personal.example/about'"
            )
        )
        second = run(self.s, self.p, self.root, platforms=['GitHub'], client=LoopFixture())
        self.assertEqual(second['leads'], [])

    def test_weak_manual_stale_and_rejected_sources_do_not_generate_aliases(self):
        self.s.apply_profile(self.p, 'https://github.com/seed', {'alias': 'seed'}, node_id=self.root)
        other = self.s.apply_profile(self.p, 'https://github.com/foreign', {'alias': 'foreign'})
        record(
            self.s,
            self.s.node(self.root),
            [
                {
                    'url': 'https://github.com/foreign',
                    'relation': 'links',
                    'location': 'bio',
                    'snippet': 'fixture',
                    'method': 'manual_observation',
                }
            ],
        )
        self.assertNotIn('foreign', [l['value'] for l in preview(self.s, self.p, self.root)])
        self.s.execute("update evidence set method='parser',current=0")
        self.assertNotIn('foreign', [l['value'] for l in preview(self.s, self.p, self.root)])
        self.s.execute("update evidence set current=1,decision='rejected'")
        self.assertNotIn('foreign', [l['value'] for l in preview(self.s, self.p, self.root)])

    def test_global_budget_and_cancel(self):
        c = LoopFixture(3)
        result = run(self.s, self.p, self.root, {'queries': 3}, platforms=['GitHub'], client=c)
        self.assertLessEqual(result['requests'], 3)
        self.assertEqual(result['status'], 'limited')
        c = LoopFixture()
        result = run(self.s, self.p, self.root, platforms=['GitHub'], client=c, stopped=lambda: True)
        self.assertEqual(c.count, 0)
        self.assertEqual(result['status'], 'paused')

    def test_explicit_deep_candidate_is_read_without_changing_default_depth(self):
        id = self.s.add(self.p, 'https://github.com/deep', seed=False, depth=5)
        sid = scan(self.s, self.p, targets=[id], client=LoopFixture())
        self.assertEqual(
            self.s.rows('select state from observations where scan=?', (sid,))[0]['state'], 'found'
        )

    def test_email_never_becomes_external_query(self):
        self.s.apply_profile(self.p, 'https://github.com/seed', {'alias': 'seed'}, node_id=self.root)
        record(
            self.s,
            self.s.node(self.root),
            [
                {
                    'email': 'person@example.org',
                    'relation': 'public_contact_occurrence',
                    'location': 'bio',
                    'snippet': 'public',
                }
            ],
        )
        self.assertFalse(
            any(l['kind'] == 'email' or '@' in l['value'] for l in preview(self.s, self.p, self.root))
        )

    def test_reverse_proof_directory_generates_alias_without_promoting_ownership(self):
        class ProofFixture(LoopFixture):
            def get(self, url, **kw):
                if 'keybase.io/_/api/' not in url:
                    return super().get(url, **kw)
                if url in self.cache:
                    return self.cache[url]
                self.count += 1
                self.calls.append(url)
                valid = 'github=seed' in url or 'usernames=differentname' in url
                body = {
                    'status': {'code': 0},
                    'them': (
                        [
                            {
                                'id': 'b' * 32,
                                'basics': {'username': 'differentname'},
                                'profile': {},
                                'proofs_summary': {
                                    'all': [
                                        {
                                            'proof_type': 'github',
                                            'nametag': 'seed',
                                            'state': 1,
                                            'service_url': 'https://github.com/seed',
                                        }
                                    ]
                                },
                            }
                        ]
                        if valid
                        else []
                    ),
                }
                result = {'state': 'found', 'text': json.dumps(body), 'url': url}
                self.cache[url] = result
                return result

        result = run(self.s, self.p, self.root, platforms=['Keybase'], client=ProofFixture())
        self.assertIn('github:seed', [l['value'] for l in result['leads']])
        self.assertIn('differentname', [l['value'] for l in result['leads']])
        self.assertEqual(self.s.rows("select count(*) n from nodes where ownership!='unknown'")[0]['n'], 0)

    def test_previously_searched_alias_still_generates_reverse_proof_query(self):
        from nicktrail.search import discover

        discover(self.s, self.p, 'seed', platforms=['GitHub'], client=LoopFixture())
        leads = preview(self.s, self.p, self.root)
        self.assertNotIn(('alias', 'seed'), [(l['kind'], l['value']) for l in leads])
        self.assertIn(('proof', 'github:seed'), [(l['kind'], l['value']) for l in leads])

    def test_explicit_loop_root_works_when_last_search_and_focus_are_unrelated(self):
        from nicktrail.search import discover

        discover(self.s, self.p, 'noise', platforms=['GitHub'], client=LoopFixture())
        unrelated = self.s.rows("select id from nodes where url='https://github.com/noise'")[0]['id']
        self.s.set_focus(self.p, unrelated)
        result = run(self.s, self.p, self.root, platforms=['GitHub'], client=LoopFixture())
        self.assertIn('completely-old', [l['value'] for l in result['leads']])
        self.assertEqual(
            self.s.rows('select node from focus where project=?', (self.p,))[0]['node'], unrelated
        )


class HistoricalAliasLeadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.s = Store(str(Path(self.tmp.name) / 't.db'))
        self.p = self.s.project('Fictional')

    def tearDown(self):
        self.s.db.close()
        self.tmp.cleanup()

    def test_renamed_durable_account_offers_its_old_nick_as_lead(self):
        id = self.s.apply_profile(
            self.p, 'https://github.com/old-handle', {'alias': 'old-handle', 'stable_id': '77'}
        )
        self.s.apply_profile(
            self.p, 'https://github.com/new-handle', {'alias': 'new-handle', 'stable_id': '77'}
        )
        leads = preview(self.s, self.p, id)
        old = [l for l in leads if l['value'] == 'old-handle']
        self.assertEqual(len(old), 1)
        self.assertEqual(old[0]['historical'], 'https://github.com/old-handle')
        self.assertIn(('alias', 'new-handle'), [(l['kind'], l['value']) for l in leads])

    def test_account_without_durable_id_or_rejected_gives_no_historical_lead(self):
        id = self.s.apply_profile(self.p, 'https://github.com/plain', {'alias': 'plain'})
        self.s.remember_address(id, 'https://github.com/elsewhere')
        self.assertNotIn('elsewhere', [l['value'] for l in preview(self.s, self.p, id)])
