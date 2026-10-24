"""Discovery from several accounts the user picked, on the fictional scenario web."""
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from tests import scenario_web as S


class MultiRootTests(unittest.TestCase):
    def test_two_picked_accounts_share_one_budget_and_rejected_is_skipped(self):
        from nicktrail.bridgeflow import run_many
        with tempfile.TemporaryDirectory() as directory:
            store, project = S.run(persona=S.PERSONA, workdir=directory, bridges=False)
            try:
                nodes = {n['url']: n['id'] for n in store.snapshot(project)['nodes'] if n['state'] == 'found'}
                seed = nodes[S.PERSONA['seed']]
                other = next(i for u, i in nodes.items() if u != S.PERSONA['seed'] and 'gitlab' in u)
                rejected = next(i for u, i in nodes.items() if i not in (seed, other))
                store.decide(rejected, 'not_mine')
                before = len(store.snapshot(project)['nodes'])
                with ExitStack() as stack:
                    for module in S.CLIENT_MODULES:
                        stack.enter_context(patch(module + '.Client', S.FixtureWeb))
                    client = S.FixtureWeb(queries=120, seconds=180)
                    out = run_many(store, project, [seed, other, rejected, seed], {'queries': 90, 'seconds': 180}, client=client)
                self.assertEqual(out['roots'], [seed, other, rejected])
                self.assertEqual(out['budget_per_account'], {'queries': 30, 'seconds': 60, 'per_domain': 15})
                self.assertEqual([r['root'] for r in out['runs']], [seed, other, rejected])
                self.assertEqual(out['runs'][2]['status'], 'skipped')
                self.assertNotEqual(out['runs'][0]['status'], 'skipped')
                self.assertGreaterEqual(len(store.snapshot(project)['nodes']), before)
                self.assertEqual(store.node(rejected)['ownership'], 'not_mine', 'labels never change')
            finally:
                store.db.close()

    def test_limits(self):
        from nicktrail.bridgeflow import run_many
        with self.assertRaises(ValueError):
            run_many(None, 1, [])
        with self.assertRaises(ValueError):
            run_many(None, 1, list(range(11)))


if __name__ == '__main__':
    unittest.main()
