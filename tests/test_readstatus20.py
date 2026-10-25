import json
import os
import tempfile
import unittest

from nicktrail.aipacket import PROMPT, build
from nicktrail.readstatus import classify, note, report
from nicktrail.search import schema as search_schema
from nicktrail.storage import Store


class ClassifyTests(unittest.TestCase):
    def test_codes_that_can_mean_a_missing_account(self):
        for state, detail, code in [
            ('not_found', 'HTTP 404', '404'),
            ('not_found', 'HTTP 410', '410'),
            ('not_found', 'Hashnode: strona błędu w odpowiedzi HTTP 200', 'Soft 404'),
            ('not_found', 'PUBLIC_API_PROFILE_NOT_FOUND: exact handle missing', 'API'),
            ('error', 'Zmienił się trwały identyfikator konta pod tym adresem', 'ID'),
        ]:
            info = classify(state, detail)
            self.assertEqual(info['code'], code, detail)
            self.assertTrue(info['may_be_missing'], detail)

    def test_blocks_and_temporary_errors_never_claim_absence(self):
        for detail in (
            'HTTP 403',
            'HTTP 401',
            'HTTP 429',
            'HTTP 500',
            'HTTP 525',
            'TimeoutError',
            'ROBOTS_RESTRICTED: automatyczny odczyt zabroniony',
            'Wyzwanie dostępu',
        ):
            info = classify('blocked', detail)
            self.assertFalse(info['may_be_missing'], detail)
            self.assertIn(info['kind'], ('access', 'policy', 'temporary'), detail)
        self.assertEqual(classify('blocked', 'HTTP 403')['code'], '403')
        self.assertEqual(classify('error', 'HTTP 525')['label'], 'Błąd pośrednika')

    def test_state_without_detail_and_found_profiles(self):
        self.assertEqual(classify('not_found', '')['kind'], 'missing')
        self.assertIsNone(classify('found', ''))


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, 'r.sqlite3'))
        search_schema(self.store)
        self.p = self.store.project('fictional')
        self.old = self.store.apply_profile(
            self.p, 'https://github.com/oldnick', {'alias': 'oldnick', 'stable_id': '7'}
        )
        self.live = self.store.apply_profile(self.p, 'https://gitlab.com/live', {'alias': 'live'})

    def tearDown(self):
        self.store.db.close()
        self.dir.cleanup()

    def nodes(self):
        return [dict(r) for r in self.store.rows('SELECT * FROM nodes WHERE project=?', (self.p,))]

    def test_note_explains_current_problem_state_only(self):
        self.store.execute("UPDATE nodes SET state='not_found' WHERE id=?", (self.old,))
        note(self.store, self.old, 'not_found', 'HTTP 404')
        note(self.store, self.live, 'blocked', 'HTTP 403')  # stale: the profile is found now
        out = report(self.store, self.p, self.nodes())
        self.assertEqual(set(out), {str(self.old)})
        self.assertEqual(out[str(self.old)]['code'], '404')
        self.assertEqual(out[str(self.old)]['source'], 'note')

    def test_older_databases_fall_back_to_search_tasks(self):
        self.store.execute("UPDATE nodes SET state='not_found' WHERE id=?", (self.old,))
        self.store.execute(
            "INSERT INTO searches(project,nickname,started,status,options) VALUES(?,?,?,?,?)",
            (self.p, 'oldnick', '2026-10-01T10:00:00', 'completed', '{}'),
        )
        search = self.store.rows('SELECT id FROM searches')[0]['id']
        self.store.execute(
            "INSERT INTO search_tasks(search,platform,term,mode,state,detail,nodes) VALUES(?,?,?,?,?,?,?)",
            (search, 'GitHub', 'oldnick', 'verify', 'not_found', 'HTTP 410', json.dumps([self.old])),
        )
        out = report(self.store, self.p, self.nodes())
        self.assertEqual(out[str(self.old)]['code'], '410')
        self.assertEqual(out[str(self.old)]['source'], 'search')

    def test_ai_packet_carries_last_read_and_new_prompt(self):
        self.store.execute("UPDATE nodes SET state='not_found' WHERE id=?", (self.old,))
        note(self.store, self.old, 'not_found', 'HTTP 404')
        packet = build(self.store, self.p, [self.old, self.live])['packet']
        by_platform = {p['platform']: p for p in packet['profiles']}
        self.assertEqual(by_platform['GitHub']['last_read']['code'], '404')
        self.assertTrue(by_platform['GitHub']['last_read']['account_may_be_gone'])
        self.assertNotIn('last_read', by_platform['GitLab'])
        for rule in (
            'niezaufane dane',
            'identyfikatorami dowodów',
            'NIE dowodzą wspólnego właściciela',
            'Nie omijaj logowania',
            'MOGŁO_ZOSTAĆ_USUNIĘTE',
            'po polsku',
        ):
            self.assertIn(rule, PROMPT)


if __name__ == '__main__':
    unittest.main()
