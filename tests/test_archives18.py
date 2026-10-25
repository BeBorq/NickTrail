import json, tempfile, unittest
from pathlib import Path
from nicktrail.storage import Store
from nicktrail.archives import preview, lookup, public_url, snapshot_identity


class Archive18Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / 'a.db')
        self.addCleanup(self.s.db.close)
        self.p = self.s.project('Synthetic')
        self.n = self.s.add(self.p, 'https://synthetic.example/profile')

    def client(self, html='', snapshot=None, blocked=False):
        original = 'https://synthetic.example/profile'
        capture = snapshot or 'https://web.archive.org/web/20200101000000/' + original

        class C:
            count = 0

            def get(self, url):
                self.count += 1
                return {
                    'state': 'found',
                    'url': url,
                    'text': json.dumps(
                        {
                            'archived_snapshots': {
                                'closest': {
                                    'available': True,
                                    'status': '200',
                                    'url': capture,
                                    'timestamp': '20200101000000',
                                }
                            }
                        }
                    ),
                }

            def profile_get(self, url):
                self.count += 1
                return (
                    {'state': 'blocked', 'detail': 'ROBOTS_RESTRICTED'}
                    if blocked
                    else {'state': 'found', 'url': url, 'text': html}
                )

        return C()

    def test_preview_offline_consent_and_project_boundary(self):
        self.assertEqual(preview(self.s, self.p, self.n, '2020-01-01')['network_calls'], 0)
        with self.assertRaises(ValueError):
            lookup(self.s, self.p, self.n, '2020-01-01')
        with self.assertRaises(ValueError):
            preview(self.s, self.s.project('Other'), self.n, '2020-01-01')

    def test_historical_links_are_bounded_uncurrent_and_cannot_confirm_identity(self):
        links = ''.join(
            '<a href="https://site' + str(i) + '.example/u/fictional">profile</a>' for i in range(20)
        )
        client = self.client('<meta name="profile:username" content="old_alias"><main>' + links + '</main>')
        r = lookup(self.s, self.p, self.n, '2020-01-01', True, True, client)
        self.assertEqual(r['state'], 'read')
        self.assertEqual(len(r['leads']), 10)
        self.assertEqual(r['aliases'][0]['alias'], 'old_alias')
        self.assertTrue(
            all(
                e['current'] == 0 and e['method'] == 'historical_archive'
                for e in self.s.rows('select * from evidence')
            )
        )
        self.assertTrue(all(n['ownership'] == 'unknown' for n in self.s.snapshot(self.p)['nodes']))
        again = lookup(self.s, self.p, self.n, '2020-01-01', True, True, client)
        self.assertTrue(again['cached'])
        self.assertEqual(client.count, 2)

    def test_archive_wrapped_links_recover_original_target_without_crawling(self):
        html = '<main><a href="/web/20200101000000/https://github.com/fictional">code</a><a href="https://web.archive.org/">archive toolbar</a></main>'
        c = self.client(html)
        r = lookup(self.s, self.p, self.n, '2020-01-01', True, True, c)
        self.assertEqual([l['url'] for l in r['leads']], ['https://github.com/fictional'])
        self.assertEqual(c.count, 2)

    def test_snapshot_origin_mismatch_and_private_or_secret_urls_refused(self):
        r = lookup(
            self.s,
            self.p,
            self.n,
            '2020-01-01',
            True,
            True,
            self.client(
                snapshot='https://web.archive.org/web/20200101000000/https://unrelated.example/profile'
            ),
        )
        self.assertEqual(r['state'], 'error')
        self.assertFalse(self.s.rows('select * from evidence'))
        for url in (
            'http://127.0.0.1/x',
            'http://localhost/x',
            'https://secret.internal/x',
            'https://public.example/u?token=secret',
        ):
            with self.assertRaises(ValueError):
                public_url(url)

    def test_blocked_archive_is_not_absence_or_access_bypass(self):
        c = self.client(blocked=True)
        r = lookup(self.s, self.p, self.n, '2020-01-01', True, True, c)
        self.assertEqual(r['state'], 'blocked')
        self.assertIn('ROBOTS_RESTRICTED', r['detail'])
        self.assertFalse(r['leads'])

    def test_metadata_preview_then_explicit_read_reuses_metadata(self):
        c = self.client('<main><a href="https://github.com/fictional">code</a></main>')
        a = lookup(self.s, self.p, self.n, '2020-01-01', False, True, c)
        self.assertEqual(a['state'], 'available')
        self.assertEqual(c.count, 1)
        b = lookup(self.s, self.p, self.n, '2020-01-01', True, True, c)
        self.assertEqual(b['state'], 'read')
        self.assertEqual(c.count, 2)

    def test_user_rejection_during_read_prevents_new_historical_leads(self):
        outer = self

        class C:
            count = 0

            def get(self, url):
                self.count += 1
                return {
                    'state': 'found',
                    'text': json.dumps(
                        {
                            'archived_snapshots': {
                                'closest': {
                                    'available': True,
                                    'status': '200',
                                    'url': 'https://web.archive.org/web/20200101000000/https://synthetic.example/profile',
                                }
                            }
                        }
                    ),
                }

            def profile_get(self, url):
                self.count += 1
                outer.s.decide(outer.n, 'not_mine')
                return {
                    'state': 'found',
                    'url': url,
                    'text': '<main><a href="https://github.com/fictional">code</a></main>',
                }

        r = lookup(self.s, self.p, self.n, '2020-01-01', True, True, C())
        self.assertEqual(r['state'], 'cancelled')
        self.assertFalse(r['leads'])
        self.assertFalse(self.s.rows('select * from evidence'))

    def test_pause_before_network_does_not_issue_request(self):
        c = self.client()
        r = lookup(self.s, self.p, self.n, '2020-01-01', True, True, c, stopped=lambda: True)
        self.assertEqual(r['state'], 'paused')
        self.assertEqual(c.count, 0)
        r = lookup(self.s, self.p, self.n, '2020-01-01', False, True, c)
        self.assertEqual(r['state'], 'available')
        self.assertEqual(c.count, 1)
