"""End-to-end regression floors on the fictional scenario web (no network)."""

import tempfile
import unittest

from tests import scenario_web as S


class ScenarioFloors(unittest.TestCase):
    def measure(self, persona):
        with tempfile.TemporaryDirectory() as directory:
            store, project = S.run(persona=persona, workdir=directory)
            try:
                return S.score(store, project, persona)
            finally:
                store.db.close()

    def test_different_nicks_linked_by_rel_me_hub_and_email(self):
        r = self.measure(S.PERSONA)
        self.assertGreaterEqual(len(r['truth_found']), 9)
        self.assertGreaterEqual(len(r['seed_cluster_truth']), 8)
        self.assertEqual((r['false_clusters'], r['seed_cluster_false']), ([], []))
        self.assertNotIn('https://github.com/adafict2', r['seed_cluster_truth'])
        self.assertGreaterEqual(r['average_precision'], 0.95)

    def test_security_researcher_profile_bridges_by_declared_link(self):
        # Pattern from a real self-audit: a bug-bounty/security profile joined to
        # the person's other accounts by a declared, reciprocal link (not by nick).
        r = self.measure(S.PERSONA)
        self.assertIn('https://hackerone.com/adasec', r['truth_found'])
        self.assertIn('https://hackerone.com/adasec', r['seed_cluster_truth'])

    def test_mailbox_written_differently_links_accounts_and_organization_stays_out(self):
        r = self.measure(S.BORYS)
        self.assertIn('https://gitlab.com/bkowal', r['seed_cluster_truth'])
        self.assertIn('https://borys.example', r['truth_found'])
        self.assertEqual((r['false_clusters'], r['seed_cluster_false']), ([], []))

    def test_old_nick_of_durable_account_finds_forgotten_accounts(self):
        r = self.measure(S.CEZARY)
        self.assertEqual(len(r['truth_found']), 3)
        self.assertNotIn('PERSISTENT_ID_DEAD_END', r['dead_ends'])


if __name__ == '__main__':
    unittest.main()
