import tempfile, json, unittest
from pathlib import Path
from nicktrail.storage import Store, now
from nicktrail.diagnostics import explain
from nicktrail.search import schema


class Diagnostics18Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / 'fixture.db')
        self.addCleanup(self.s.db.close)
        self.p = self.s.project('Synthetic')
        schema(self.s)

    def test_saved_blocked_node_keeps_actual_latest_read_reason(self):
        node = self.s.add(self.p, 'https://github.com/fictional')
        self.s.execute('update nodes set state=? where id=?', ('blocked', node))
        scan = self.s.execute(
            'insert into scans(project,started,status,queue,options) values(?,?,?,?,?)',
            (self.p, now(), 'completed', '[]', '{}'),
        ).lastrowid
        self.s.execute(
            'insert into observations values(?,?,?,?,?)',
            (scan, node, 'blocked', '{}', 'HTTP 429 Retry-After'),
        )
        result = explain(self.s, self.p, 'https://github.com/fictional', {})
        self.assertEqual(result['code'], 'RATE_LIMITED')
        self.assertEqual(result['last_matching_read']['scan'], scan)
        self.s.execute('update nodes set state=? where id=?', ('found', node))
        self.assertEqual(explain(self.s, self.p, 'https://github.com/fictional', {})['code'], 'PROFILE_FOUND')

    def test_pending_interruption_and_unsupported_do_not_invent_username_failure(self):
        search = self.s.execute(
            'insert into searches(project,nickname,status,options) values(?,?,?,?)',
            (self.p, 'fictional', 'paused', json.dumps({'_terms': ['fictional']})),
        ).lastrowid
        self.s.execute(
            'insert into search_tasks(search,platform,term,mode,state,nodes,detail) values(?,?,?,?,?,?,?)',
            (search, 'GitHub', 'fictional', 'exact', 'pending', '[]', ''),
        )
        self.assertEqual(
            explain(self.s, self.p, 'https://github.com/fictional', {})['code'], 'QUEUE_INTERRUPTED'
        )
        self.s.execute(
            'update search_tasks set state=?,detail=? where search=?',
            ('unsupported', 'Automation unavailable', search),
        )
        self.assertEqual(
            explain(self.s, self.p, 'https://github.com/fictional', {})['code'], 'AUTOMATION_UNAVAILABLE'
        )
        self.s.execute('update search_tasks set detail=? where search=?', ('USERNAME_RULE_REJECTED', search))
        self.assertEqual(
            explain(self.s, self.p, 'https://github.com/fictional', {})['code'], 'USERNAME_RULE_REJECTED'
        )
