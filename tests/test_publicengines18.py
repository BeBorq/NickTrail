import unittest, json, tempfile
from pathlib import Path
from nicktrail.publicengines import lookup, fallback
from nicktrail.storage import Store


class PublicEngine18Tests(unittest.TestCase):
    def client(self, body, state='found'):
        class C:
            def get(self, url):
                return {'state': state, 'text': json.dumps(body), 'url': url}

        return C()

    def test_public_engines_exact_ids_and_declared_links(self):
        fixtures = {
            'mastodon': {
                'username': 'fictional',
                'acct': 'fictional',
                'id': '42',
                'url': 'https://synthetic.example/@fictional',
                'note': '<p>https://github.com/fictional</p>',
            },
            'peertube': {
                'name': 'fictional',
                'id': 42,
                'url': 'https://synthetic.example/accounts/fictional',
                'description': 'https://github.com/fictional',
            },
            'nodebb': {
                'userslug': 'fictional',
                'username': 'Fictional',
                'uid': 42,
                'website': 'https://github.com/fictional',
            },
            'mediawiki': {
                'query': {
                    'users': [{'name': 'fictional', 'userid': 42, 'registration': '2020-01-01T00:00:00Z'}]
                }
            },
        }
        for engine, body in fixtures.items():
            with self.subTest(engine=engine):
                r = lookup(engine, 'synthetic.example', 'fictional', self.client(body))
                self.assertEqual(r['state'], 'found')
                self.assertEqual(r['matches'][0]['data']['stable_id'], '42')
                self.assertEqual(bool(r['matches'][0]['evidence']), engine != 'mediawiki')
                self.assertNotIn('ownership', r['matches'][0]['data'])

    def test_mastodon_remote_account_and_wrong_alias_rejected(self):
        body = {
            'username': 'fictional',
            'acct': 'fictional@remote.example',
            'id': '42',
            'url': 'https://remote.example/@fictional',
        }
        self.assertEqual(
            lookup('mastodon', 'synthetic.example', 'fictional', self.client(body))['state'], 'partial'
        )
        self.assertEqual(
            lookup('nodebb', 'synthetic.example', 'fictional', self.client({'userslug': 'other', 'uid': 42}))[
                'state'
            ],
            'partial',
        )

    def test_missing_wiki_and_blocked_access_are_distinct(self):
        self.assertEqual(
            lookup(
                'mediawiki',
                'synthetic.example',
                'fictional',
                self.client({'query': {'users': [{'name': 'fictional', 'missing': True}]}}),
            )['state'],
            'not_found',
        )
        self.assertEqual(
            lookup('mastodon', 'synthetic.example', 'fictional', self.client({}, 'blocked'))['state'],
            'blocked',
        )

    def test_fingerprint_and_route_required_before_fallback_request(self):
        class Never:
            def get(self, url):
                raise AssertionError('No speculative API probing')

        self.assertIsNone(fallback('https://synthetic.example/u/fictional', 'fictional', '', Never()))
        self.assertIsNone(fallback('https://synthetic.example/about', 'fictional', 'Discourse', Never()))
        result = fallback(
            'https://synthetic.example/u/fictional',
            'fictional',
            'Discourse 3.0',
            self.client(
                {'user': {'id': 42, 'username': 'fictional', 'bio_raw': 'https://github.com/fictional'}}
            ),
        )
        self.assertEqual(result['state'], 'found')
        self.assertTrue(result['matches'][0]['evidence'])

    def test_instance_local_ids_cannot_merge_accounts_on_different_hosts(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            s = Store(Path(folder) / 'ids.db')
            p = s.project('Synthetic')
            a = s.apply_profile(
                p, 'https://one.example/@fictional', {'alias': 'fictional', 'stable_id': '42'}
            )
            b = s.apply_profile(p, 'https://two.example/@other', {'alias': 'other', 'stable_id': '42'})
            self.assertNotEqual(a, b)
            self.assertEqual(len(s.snapshot(p)['nodes']), 2)
            self.assertEqual(
                s.apply_profile(p, 'https://one.example/@renamed', {'alias': 'renamed', 'stable_id': '42'}), a
            )
            s.db.close()

    def test_no_arbitrary_host_paths_or_unimplemented_engines(self):
        for engine, host in [
            ('unknown', 'synthetic.example'),
            ('nodebb', 'synthetic.example/private'),
            ('nodebb', 'user:secret@synthetic.example'),
        ]:
            with self.assertRaises(ValueError):
                lookup(engine, host, 'fictional', self.client({}))

    def test_negotiated_json_on_profile_url_is_not_rejected_as_bad_html(self):
        from nicktrail.freeprofiles import probe

        service = {
            'id': 'Fixture',
            'profile_url': 'https://synthetic.example/u/{nick}',
            'detection': {'not_found_titles': ['404 not found']},
        }

        class C:
            calls = 0

            def get(self, url):
                self.calls += 1
                return {
                    'state': 'found',
                    'url': url,
                    'content_type': 'application/json',
                    'text': json.dumps(
                        {
                            'user': {
                                'id': 42,
                                'username': 'fictional',
                                'bio_raw': 'https://github.com/fictional',
                            }
                        }
                    ),
                }

        client = C()
        result = probe(service, 'fictional', client)
        self.assertEqual(result['state'], 'found')
        self.assertEqual(client.calls, 1)
        self.assertTrue(result['matches'][0]['evidence'])
        self.assertEqual(probe(service, 'wrong', client)['state'], 'partial')

    def test_discovered_link_to_negotiated_json_can_be_enriched_without_catalog(self):
        from nicktrail.publicprofile import read

        c = self.client(
            {'user': {'id': 42, 'username': 'Fictional', 'bio_raw': 'https://github.com/fictional'}}
        )
        result = read({'url': 'https://synthetic.example/u/fictional', 'platform': 'Strona'}, c)
        self.assertEqual(result['state'], 'found')
        self.assertEqual(result['data']['id_scope'], 'synthetic.example')
        self.assertTrue(result['evidence'])
