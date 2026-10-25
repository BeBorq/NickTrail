import json
import tempfile
import unittest
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path
from nicktrail.storage import Store
from nicktrail.discovery import prepare_nickname
from nicktrail.engine import scan
from nicktrail.demo import FixtureClient


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.store = Store(Path(self.tmp.name) / 'discovery.sqlite3')
        self.project = self.store.project('Fikcyjny')

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_lookup_keeps_unknown_ownership_and_does_not_expand(self):
        ids = prepare_nickname(self.store, self.project, 'fictional-nicktrail')
        client = FixtureClient()
        scan(self.store, self.project, client=client, targets=ids)
        self.assertEqual(client.count, 1)
        self.assertEqual(self.store.node(ids[0])['state'], 'found')
        self.assertEqual(self.store.node(ids[0])['ownership'], 'unknown')
        candidates = [
            n
            for n in self.store.snapshot(self.project)['nodes']
            if n['url'] == 'https://nicktrail.example/about'
        ]
        self.assertEqual(candidates[0]['state'], 'unverified')
        self.assertFalse(self.store.snapshot(self.project)['evidence'][0]['relation'] == 'claims_ownership')

    def test_candidate_permission_survives_pause_resume(self):
        ids = prepare_nickname(self.store, self.project, 'fictional-nicktrail')
        client = FixtureClient()
        scan_id = scan(self.store, self.project, client=client, targets=ids, stopped=lambda: True)
        saved = self.store.rows('SELECT * FROM scans WHERE id=?', (scan_id,))[0]
        self.assertEqual(json.loads(saved['options'])['_targets'], ids)
        scan(self.store, self.project, client=client, resume=scan_id)
        self.assertEqual(client.count, 1)
        self.assertEqual(self.store.node(ids[0])['ownership'], 'unknown')

    def test_rejected_and_unselected_nodes_are_never_read(self):
        ids = prepare_nickname(self.store, self.project, 'fictional-nicktrail')
        self.store.decide(ids[0], 'not_mine')
        self.store.add(self.project, 'https://nicktrail.example/about', confirmed=True)
        client = FixtureClient()
        scan(self.store, self.project, client=client, targets=ids)
        self.assertEqual(client.count, 0)
        again = prepare_nickname(self.store, self.project, 'fictional-nicktrail')
        self.assertEqual(ids, again)
        self.assertEqual(self.store.node(ids[0])['ownership'], 'not_mine')

    def test_foreign_project_and_invalid_targets(self):
        other = self.store.project('Inny')
        id = self.store.add(other, 'https://github.com/fictional-nicktrail')
        for targets in ([id], [], ['1']):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                scan(self.store, self.project, targets=targets)
        self.assertFalse(self.store.snapshot(self.project)['scans'])

    def test_bad_nicknames_do_not_create_nodes(self):
        for nickname in (
            '',
            '../login',
            'a?x=1',
            '-alice',
            'alice-',
            'a--b',
            'ąlice',
            'a' * 40,
            'settings',
            'a b',
        ):
            with self.subTest(nickname=nickname), self.assertRaises(ValueError):
                prepare_nickname(self.store, self.project, nickname)
        self.assertFalse(self.store.snapshot(self.project)['nodes'])

    def test_normal_scan_still_does_not_read_candidates(self):
        prepare_nickname(self.store, self.project, 'fictional-nicktrail')
        client = FixtureClient()
        scan(self.store, self.project, client=client)
        self.assertEqual(client.count, 0)

    def test_limits_also_apply_to_explicit_candidates(self):
        ids = prepare_nickname(self.store, self.project, 'fictional-nicktrail')
        client = FixtureClient()
        id = scan(self.store, self.project, {'profiles': 0}, client=client, targets=ids)
        self.assertEqual(client.count, 0)
        self.assertEqual(
            self.store.rows('SELECT status FROM scans WHERE id=?', (id,))[0]['status'], 'limited'
        )

    def test_strict_limit_validation(self):
        for opts in ({'queries': True}, {'queries': -1}, {'unknown': 1}):
            with self.subTest(opts=opts), self.assertRaises(ValueError):
                scan(self.store, self.project, opts)

    def test_cli_search_uses_shared_engine(self):
        from nicktrail.__main__ import main

        path = str(Path(self.tmp.name) / 'cli.sqlite3')
        out = io.StringIO()
        with patch('sys.argv', ['nicktrail', '--db', path, 'create', 'Test']), redirect_stdout(out):
            main()
        out = io.StringIO()
        with (
            patch(
                'sys.argv', ['nicktrail', '--db', path, 'search', '1', 'fictional-nicktrail', '--github-only']
            ),
            patch('nicktrail.engine.Client', return_value=FixtureClient()),
            redirect_stdout(out),
        ):
            main()
        result = json.loads(out.getvalue())
        self.assertEqual(result['nodes'][0]['state'], 'found')
        self.assertEqual(result['nodes'][0]['ownership'], 'unknown')


if __name__ == '__main__':
    unittest.main()
