"""rc16 code review: regression tests for the fixed defects."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from nicktrail.network import headers_allowed
from nicktrail.storage import Store


class Headers(unittest.TestCase):
    def test_keyed_gaming_apis_may_send_their_own_headers_only_to_their_host(self):
        self.assertTrue(headers_allowed({'Client-Id': 'x', 'Authorization': 'Bearer y'}, 'https', 'api.twitch.tv'))
        self.assertTrue(headers_allowed({'X-Authorization': 'k', 'Accept': 'application/json'}, 'https', 'xbl.io'))
        self.assertFalse(headers_allowed({'Client-Id': 'x', 'Authorization': 'Bearer y'}, 'https', 'evil.example'))
        self.assertFalse(headers_allowed({'X-Authorization': 'k', 'Accept': 'application/json'}, 'http', 'xbl.io'))
        self.assertFalse(headers_allowed({'Cookie': 'a'}, 'https', 'api.twitch.tv'))
        self.assertTrue(headers_allowed({'hibp-api-key': 'k'}, 'https', 'haveibeenpwned.com'))


class RobotsThroughWrappers(unittest.TestCase):
    """Profile pages read through the branch tree must use the client's robots.txt check."""

    def test_branch_reads_use_profile_get(self):
        from nicktrail.branches import explore

        class Client:
            def __init__(self):
                self.count = 0
                self.profile_calls = []

            def get(self, url, **kwargs):
                self.count += 1
                return {'state': 'found', 'text': '<main><p>Fictional page with enough visible public text for the test.</p></main>', 'url': url}

            def profile_get(self, url):
                self.profile_calls.append(url)
                self.count += 1
                return {'state': 'blocked', 'detail': 'ROBOTS_RESTRICTED: automatyczny odczyt zabroniony'}

        with tempfile.TemporaryDirectory() as folder:
            store = Store(os.path.join(folder, 't.sqlite3'))
            project = store.project('Fixture')
            root = store.add(project, 'https://fixture.example/about')
            client = Client()
            explore(store, project, [root], client=client)
            self.assertIn('https://fixture.example/about', client.profile_calls)
            self.assertNotEqual(store.node(root)['state'], 'found')
            store.db.close()


class Sensitive(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.folder.name, 's.sqlite3'))
        self.p = self.store.project('Fixture')

    def tearDown(self):
        self.store.db.close(); self.folder.cleanup()

    def test_marker_survives_a_full_re_read_and_is_derived_from_the_host(self):
        url = 'https://www.pornhub.com/users/fictional'
        id = self.store.apply_profile(self.p, url, {'alias': 'fictional', 'sensitive': True, 'sensitive_category': 'adult'})
        self.store.apply_profile(self.p, url, {'alias': 'fictional', 'bio': 'x'}, node_id=id)
        data = json.loads(self.store.node(id)['data'])
        self.assertTrue(data['sensitive'])
        other = self.store.apply_profile(self.p, 'https://xhamster.com/users/someone', {'alias': 'someone'})
        self.assertTrue(json.loads(self.store.node(other)['data'])['sensitive'])

    def test_export_leaves_out_sensitive_profiles_and_their_search_scope(self):
        from nicktrail.exporting import export
        from nicktrail.search import schema
        schema(self.store)
        self.store.apply_profile(self.p, 'https://www.xvideos.com/profiles/fictional', {'alias': 'fictional'})
        sid = self.store.execute("INSERT INTO searches(project,nickname,started,status,options) VALUES(?,?,?,?,?)", (self.p, 'fictional', 'now', 'completed', '{}')).lastrowid
        self.store.execute("INSERT INTO search_sources(search,platform,state,detail) VALUES(?,?,?,?)", (sid, 'Sensitive', 'found', 'Xvideos:fictional / nick lub alias: znaleziono'))
        self.store.execute("INSERT INTO search_sources(search,platform,state,detail) VALUES(?,?,?,?)", (sid, 'GitHub', 'not_found', 'fictional: brak'))
        text = export(self.store, self.p, 'json')
        self.assertNotIn('xvideos', text.lower())
        self.assertIn('GitHub', text)
        self.assertIn('xvideos', export(self.store, self.p, 'json', include_sensitive=True).lower())


class Confirmation(unittest.TestCase):
    def test_confirming_an_existing_unknown_entry_marks_it_mine_but_never_overrides_not_mine(self):
        store = Store(':memory:')
        p = store.project('Fixture')
        nick = store.add(p, 'fictional', 'alias')            # e.g. created by a search
        self.assertEqual(store.node(nick)['ownership'], 'unknown')
        store.add(p, 'fictional', 'alias', True)             # the user confirms it
        self.assertEqual(store.node(nick)['ownership'], 'mine')
        rejected = store.add(p, 'https://github.com/someone-else')
        store.decide(rejected, 'not_mine')
        store.add(p, 'https://github.com/someone-else', confirmed=True)
        self.assertEqual(store.node(rejected)['ownership'], 'not_mine')
        for bad in ('', '   ', 'a\nb', None, 'x' * 2001):
            with self.assertRaises(ValueError):
                store.add(p, bad, 'alias')
        store.db.close()


if __name__ == '__main__':
    unittest.main()
