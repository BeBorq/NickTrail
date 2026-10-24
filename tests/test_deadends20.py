import json
import os
import tempfile
import unittest

from nicktrail.deadends import report
from nicktrail.engine import record
from nicktrail.storage import Store


class DeadEndTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, 'd.sqlite3'))
        self.p = self.store.project('fictional')
        self.seed = self.store.apply_profile(self.p, 'https://github.com/seed', {'alias': 'seed', 'stable_id': '1'})
        self.store.decide(self.seed, 'mine')

    def tearDown(self):
        self.store.db.close()
        self.dir.cleanup()

    def kinds(self):
        return {(d['kind'], d['url']) for d in report(self.store, self.p)['dead_ends']}

    def test_declared_alias_hub_and_email_are_reported_without_queries(self):
        other = self.store.apply_profile(self.p, 'https://gitlab.com/other-nick', {'alias': 'other-nick'})
        hub = self.store.add(self.p, 'https://linktr.ee/hubname', seed=False)
        self.store.execute("UPDATE nodes SET state='blocked' WHERE id=?", (hub,))
        record(self.store, self.store.node(self.seed), [
            {'url': 'https://gitlab.com/other-nick', 'relation': 'links', 'location': 'bio', 'snippet': 'x'},
            {'url': 'https://linktr.ee/hubname', 'relation': 'links', 'location': 'bio', 'snippet': 'x'},
            {'email': 'only-here@gmail.com', 'relation': 'public_contact_occurrence', 'location': 'bio', 'snippet': 'x'}])
        found = self.kinds()
        self.assertIn(('ALIAS_DEAD_END', 'https://gitlab.com/other-nick'), found)
        self.assertIn(('IDENTITY_HUB_DEAD_END', 'https://linktr.ee/hubname'), found)
        self.assertIn(('EMAIL_DEAD_END', 'only-here@gmail.com'), found)
        self.assertIn(('ALIAS_DEAD_END', 'https://github.com/seed'), found)

    def test_searched_alias_and_rejected_accounts_are_not_dead_ends(self):
        self.store.apply_profile(self.p, 'https://gitlab.com/other-nick', {'alias': 'other-nick'})
        record(self.store, self.store.node(self.seed), [{'url': 'https://gitlab.com/other-nick', 'relation': 'links', 'location': 'bio', 'snippet': 'x'}])
        from nicktrail.search import schema
        schema(self.store)
        search = self.store.execute("INSERT INTO searches(project,nickname,started,status,options) VALUES(?,?,?,?,?)", (self.p, 'seed', '', 'completed', '{}')).lastrowid
        self.store.execute("INSERT INTO search_tasks(search,platform,term,mode) VALUES(?,?,?,?)", (search, 'GitHub', 'other-nick', 'exact'))
        self.assertFalse({k for k in self.kinds() if k[0] == 'ALIAS_DEAD_END'})
        other = self.store.rows("SELECT id FROM nodes WHERE url='https://gitlab.com/other-nick'")[0]['id']
        self.store.execute("DELETE FROM search_tasks")
        self.store.decide(other, 'not_mine')
        self.assertNotIn(('ALIAS_DEAD_END', 'https://gitlab.com/other-nick'), self.kinds())

    def test_unconnected_same_nick_account_is_not_reported(self):
        self.store.apply_profile(self.p, 'https://gitlab.com/seed', {'alias': 'seed'})
        self.assertNotIn('https://gitlab.com/seed', {u for _, u in self.kinds()})


if __name__ == '__main__':
    unittest.main()
