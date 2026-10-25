"""rc17: forgotten-account hints from the user's own mailbox / password export, and archive search."""

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from nicktrail import accounthints, archivesearch
from nicktrail.storage import Store

MBOX = (
    b'From 1@x Mon Jan  3 10:00:00 +0000 2022\n'
    b'From: Shinden <noreply@shinden.pl>\nSubject: =?utf-8?q?Witamy!_Potwierd=C5=BA_konto?=\nDate: Mon, 03 Jan 2022 10:00:00 +0000\n\n'
    b'Body line.\n\nFrom the body without escaping, no year here\n\n'
    b'From 2@x Tue Jan  4 10:00:00 +0000 2022\n'
    b'From: Riot Games <noreply@mail.accounts.riotgames.com>\nSubject: New login to your account\nDate: Tue, 04 Jun 2024 10:00:00 +0000\n\nx\n\n'
    b'From 3@x Wed Jan  5 10:00:00 +0000 2022\n'
    b'From: Jan Kowalski <jan.kowalski@gmail.com>\nSubject: Hej\nDate: Wed, 05 Jan 2022 10:00:00 +0000\n\nx\n\n'
    b'From 4@x Thu Jan  6 10:00:00 +0000 2022\n'
    b'From: Me <ada@example.org>\nSubject: Sent by me\nDate: Thu, 06 Jan 2022 10:00:00 +0000\n\nx\n'
)
CSV = (
    'name,url,username,password,note\n'
    'shinden,https://shinden.pl/,fictional_nick,TOPSECRET1,\n'
    'google,https://accounts.google.com,ada@example.org,TOPSECRET2,\n'
    'app,android://hash@com.example.app/,x,TOPSECRET3,\n'
)


class MailboxAndPasswords(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.folder.name, 'h.sqlite3'))
        self.p = self.store.project('Fixture')
        self.store.add(self.p, 'ada@example.org', 'email', True)

    def tearDown(self):
        self.store.db.close()
        self.folder.cleanup()

    def test_mbox_headers_only_grouped_by_service_and_people_skipped(self):
        path = Path(self.folder.name) / 'mail.mbox'
        path.write_bytes(MBOX)
        result = accounthints.import_mailbox(self.store, self.p, str(path))
        self.assertEqual(result['messages'], 4)
        self.assertEqual(result['skipped_personal'], 1)
        view = accounthints.view(self.store, self.p)
        domains = {s['domain']: s for s in view['services']}
        self.assertEqual(set(domains), {'shinden.pl', 'riotgames.com'})  # own and personal mail left out
        self.assertEqual(domains['shinden.pl']['signals'], {'welcome': 1})
        self.assertEqual(domains['riotgames.com']['signals'], {'login': 1})
        stored = json.dumps(self.store.rows('SELECT * FROM account_hints'))
        self.assertNotIn('Witamy', stored)  # subjects are never stored

    def test_zip_and_eml_folder(self):
        archive = Path(self.folder.name) / 'takeout.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('Takeout/Mail/All.mbox', MBOX)
        self.assertEqual(accounthints.import_mailbox(self.store, self.p, str(archive))['domains'], 2)
        emls = Path(self.folder.name) / 'eml'
        emls.mkdir()
        (emls / 'a.eml').write_bytes(
            b'From: GitHub <noreply@github.com>\nSubject: Please verify your email\n\nbody'
        )
        self.assertEqual(accounthints.import_mailbox(self.store, self.p, str(emls))['domains'], 1)

    def test_password_export_keeps_site_and_login_but_never_the_password(self):
        result = accounthints.import_passwords(self.store, self.p, text=CSV)
        self.assertEqual(result, {'entries': 3, 'domains': 2})
        dump = json.dumps(self.store.rows('SELECT * FROM account_hints'))
        self.assertNotIn('TOPSECRET', dump)
        view = accounthints.view(self.store, self.p)
        self.assertEqual(view['nicks'], ['fictional_nick'])
        self.assertEqual(view['emails'], ['ada@example.org'])
        self.assertNotIn('example.app', dump)  # android:// entries are not websites

    def test_decisions_survive_a_re_import_and_feed_the_archive_search(self):
        accounthints.import_passwords(self.store, self.p, text=CSV)
        accounthints.decide(self.store, self.p, 'shinden.pl', 'mine')
        accounthints.import_passwords(self.store, self.p, text=CSV)
        self.assertEqual(
            {s['domain']: s['status'] for s in accounthints.view(self.store, self.p)['services']}[
                'shinden.pl'
            ],
            'mine',
        )
        ids = [s['id'] for s in archivesearch.sites(self.store, self.p)]
        self.assertIn('domain-shinden.pl', ids)

    def test_project_deletion_removes_hints(self):
        accounthints.import_passwords(self.store, self.p, text=CSV)
        self.store.execute('DELETE FROM projects WHERE id=?', (self.p,))
        self.assertEqual(self.store.rows('SELECT COUNT(*) n FROM account_hints')[0]['n'], 0)


class ArchiveSearch(unittest.TestCase):
    def test_numbered_profile_address_is_found_as_unverified_candidate(self):
        from nicktrail.search import discover, results

        rows = [
            ['original', 'timestamp', 'statuscode'],
            ['https://shinden.pl/user/123456-fictional/posts', '20230101120000', '200'],
            ['https://shinden.pl/user/7-fictionalx', '20230101120000', '200'],
        ]
        sent = []

        class Client:
            count = 0

            def get(self, url, **kwargs):
                sent.append(url)
                return {'state': 'found', 'text': json.dumps(rows if 'shinden.pl' in url else [])}

        store = Store(':memory:')
        p = store.project('Fixture')
        with patch.dict(archivesearch.SITES, {'shinden': archivesearch.SITES['shinden']}, clear=True):
            discover(store, p, 'fictional', platforms=['Archive'], client=Client())
        nodes = {n['url']: n for n in store.rows('SELECT * FROM nodes')}
        self.assertIn('https://shinden.pl/user/123456-fictional', nodes)
        self.assertNotIn('https://shinden.pl/user/7-fictionalx', nodes)
        node = nodes['https://shinden.pl/user/123456-fictional']
        self.assertEqual(node['ownership'], 'unknown')
        self.assertEqual(node['state'], 'unverified')
        self.assertTrue(json.loads(node['data'])['indexed_only'])
        self.assertTrue(all(u.startswith('https://web.archive.org/cdx/search/cdx?') for u in sent))
        self.assertTrue(all('fictional' in u for u in sent))
        store.db.close()


if __name__ == '__main__':
    unittest.main()
