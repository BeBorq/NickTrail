import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.search import schema
from nicktrail.autoresume import search, progress, branches


class AutoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.s = Store(str(Path(self.tmp.name) / 'test.db'))
        schema(self.s)
        self.p = self.s.project('Fixture')
        self.id = self.s.execute(
            'insert into searches(project,status,requests,options) values(?,?,?,?)',
            (self.p, 'limited', 2, json.dumps({'candidates': 200})),
        ).lastrowid
        for i in range(4):
            self.s.execute(
                'insert into search_tasks(search,platform,term,mode) values(?,?,?,?)',
                (self.id, 'Free', str(i), 'probe'),
            )

    def tearDown(self):
        self.s.db.close()
        self.tmp.cleanup()

    def advance(self, *a, **k):
        row = self.s.rows(
            "select rowid from search_tasks where search=? and state='pending' limit 1", (self.id,)
        )
        if row:
            self.s.execute("update search_tasks set state='not_found' where rowid=?", (row[0]['rowid'],))
        pending = self.s.rows(
            "select count(*) n from search_tasks where search=? and state='pending'", (self.id,)
        )[0]['n']
        self.s.execute(
            'update searches set requests=requests+1,status=? where id=?',
            ('limited' if pending else 'completed', self.id),
        )

    def test_continues_until_all_tasks_finished(self):
        with patch('nicktrail.search.discover', side_effect=self.advance) as call:
            search(self.s, self.p, self.id)
        self.assertEqual(call.call_count, 4)
        self.assertEqual(self.s.rows('select status from searches')[0]['status'], 'completed')

    def test_cancel_and_stall_do_not_loop(self):
        with patch('nicktrail.search.discover') as call:
            search(self.s, self.p, self.id, stopped=lambda: True)
            call.assert_not_called()
        with patch('nicktrail.search.discover') as call:
            search(self.s, self.p, self.id)
            self.assertEqual(call.call_count, 1)

    def test_round_limit_and_cancellable_pause(self):
        with patch('nicktrail.search.discover', side_effect=self.advance) as call:
            search(self.s, self.p, self.id, max_rounds=2)
            self.assertEqual(call.call_count, 2)
        with patch('nicktrail.search.discover') as call:
            search(self.s, self.p, self.id, pause=lambda: True)
            call.assert_not_called()

    def test_candidate_cap_still_applies(self):
        self.s.execute("update search_tasks set platform='GitHub',mode='context'")
        self.s.execute('update searches set options=?', (json.dumps({'candidates': 0}),))
        with patch('nicktrail.search.discover') as call:
            search(self.s, self.p, self.id)
            call.assert_not_called()

    def test_progress_counts_attempts_and_errors_not_identity(self):
        p = progress([{'state': v} for v in ('found', 'not_found', 'blocked', 'error', 'partial', 'pending')])
        self.assertEqual(p['total'], 6)
        self.assertEqual(p['done'], 5)
        self.assertEqual(p['percent'], 83.3)
        self.assertEqual(p['remaining_percent'], 16.7)
        self.assertEqual(progress([])['percent'], 0)

    def test_branch_stall_and_resume(self):
        from nicktrail.branches import schema as bs

        bs(self.s)
        n = self.s.add(self.p, 'https://example.org/fixture')
        id = self.s.execute(
            'insert into branch_runs(project,status,requests,options) values(?,?,?,?)',
            (self.p, 'limited', 1, '{}'),
        ).lastrowid
        self.s.execute('insert into branch_nodes(run,root,node,depth) values(?,?,?,0)', (id, n, n))

        def finish(*a, **k):
            self.s.execute("update branch_nodes set state='found'")
            self.s.execute("update branch_runs set status='completed',requests=2")

        with patch('nicktrail.branches.explore', side_effect=finish) as call:
            branches(self.s, self.p, id)
            self.assertEqual(call.call_count, 1)

    def test_real_free_queue_automatically_finishes_one_hundred_tasks(self):
        from nicktrail.search import discover
        from nicktrail.network import Limit

        class Budget:
            def __init__(self, **kwargs):
                self.count = 0

            def get(self, url):
                if self.count >= 2:
                    raise Limit()
                self.count += 1
                return {'state': 'found', 'text': '<title>Welcome</title>', 'url': url}

        with patch('nicktrail.search.Client', Budget):
            id = discover(self.s, self.p, 'fictional', platforms=['Free'])
            search(self.s, self.p, id)
        tasks = self.s.rows('select * from search_tasks where search=?', (id,))
        p = progress(tasks)
        self.assertEqual(p['done'], 100)
        self.assertEqual(p['percent'], 100)
        self.assertEqual(p['sites_done'], 100)
        self.assertEqual(
            self.s.rows('select status from searches where id=?', (id,))[0]['status'], 'completed'
        )
