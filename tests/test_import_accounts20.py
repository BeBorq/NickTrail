import os
import tempfile
import unittest

from nicktrail.imports import import_accounts
from nicktrail.storage import Store


class ImportAccountsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, 'i.sqlite3'))
        self.p = self.store.project('fictional')

    def tearDown(self):
        self.store.db.close()
        self.dir.cleanup()

    def owned(self):
        return sorted(n['url'] for n in self.store.snapshot(self.p)['nodes'] if n['ownership'] == 'mine')

    def test_urls_and_service_handle_become_confirmed_anchors(self):
        r = import_accounts(
            self.store,
            self.p,
            [
                'https://github.com/quillonior',
                'hackerone: quillon',
                'bugcrowd: quillon',
                'x: quillonior',
                '# a comment',
                '',
                'https://github.com/quillonior',
            ],
            mine=True,
        )
        self.assertEqual(r['added'], 4)
        self.assertEqual(r['confirmed'], 4)
        self.assertEqual(r['invalid_count'], 0)
        self.assertIn('https://bugcrowd.com/quillon', self.owned())
        self.assertIn('https://hackerone.com/quillon', self.owned())

    def test_without_mine_it_only_adds_candidates(self):
        r = import_accounts(self.store, self.p, ['https://gitlab.com/quillon'], mine=False)
        self.assertEqual((r['added'], r['confirmed']), (1, 0))
        self.assertEqual(self.owned(), [])

    def test_bad_lines_are_reported_not_fatal(self):
        r = import_accounts(
            self.store,
            self.p,
            ['not a url', 'ftp://evil.example/x', 'http://localhost/a', 'random words here'],
            mine=True,
        )
        self.assertEqual(r['added'], 0)
        self.assertGreaterEqual(r['invalid_count'], 3)

    def test_private_and_app_route_urls_are_rejected(self):
        r = import_accounts(
            self.store,
            self.p,
            ['http://127.0.0.1/x', 'https://github.com/settings/profile?token=secret'],
            mine=True,
        )
        self.assertEqual(r['added'], 0)

    def test_unknown_project(self):
        with self.assertRaises(ValueError):
            import_accounts(self.store, 999, ['https://github.com/x'])


if __name__ == '__main__':
    unittest.main()
