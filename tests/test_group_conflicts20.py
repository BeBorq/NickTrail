"""A group may not grow past a contradiction between any two of its members."""
import unittest

from tests.test_entitylinks import ev, mail, members, node, run


class GroupConflictTests(unittest.TestCase):
    def chain(self, extra=()):
        # A-B share a mailbox, B-C declare each other: a strong chain A-B-C.
        nodes = [node(1, 'https://github.com/a1', 'GitHub'), node(2, 'https://gitlab.com/b2', 'GitLab'),
                 node(3, 'https://x.com/c3', 'X'), mail(9, 'one@gmail.com')]
        evidence = [ev(10, 1, 9, 'public_contact_occurrence'), ev(11, 2, 9, 'public_contact_occurrence'),
                    ev(12, 2, 3, 'claims_ownership'), ev(13, 3, 2, 'claims_ownership')] + list(extra)
        return run(nodes, evidence)

    def test_without_conflict_the_chain_joins(self):
        self.assertEqual(members(self.chain()), [{1, 2, 3}])

    def test_conflict_between_ends_blocks_the_weaker_merge(self):
        result = self.chain([ev(20, 1, 3, 'identity_contradiction')])
        groups = members(result)
        self.assertNotIn({1, 2, 3}, groups)
        self.assertFalse(any({1, 3} <= g for g in groups), 'A and C must never share a group')
        blocked = [p for p in result['pairs'] if p.get('blocked_by_group_conflict')]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]['tier'], 'review')
        self.assertTrue(any(f['kind'] == 'group_conflict' and f['evidence'] == [20] for f in blocked[0]['facts']))

    def test_rejected_or_stale_conflict_does_not_block(self):
        self.assertEqual(members(self.chain([ev(20, 1, 3, 'identity_contradiction', decision='rejected')])), [{1, 2, 3}])
        self.assertEqual(members(self.chain([ev(20, 1, 3, 'identity_contradiction', current=0)])), [{1, 2, 3}])

    def test_every_cluster_bridge_lies_inside_its_cluster(self):
        result = self.chain([ev(20, 1, 3, 'identity_contradiction')])
        for c in result['clusters']:
            for b in c['bridges']:
                self.assertTrue({b['a'], b['b']} <= set(c['members']))


if __name__ == '__main__':
    unittest.main()
