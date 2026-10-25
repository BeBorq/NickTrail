import unittest, json
from nicktrail.frontier import priorities, bridge_bonus


class BridgePriority20Tests(unittest.TestCase):
    def test_hub_bonus_does_not_expand_weak_hub_or_override_focus_or_imply_identity(self):
        def node(id, url, alias):
            return {
                'id': id,
                'url': url,
                'kind': 'profile',
                'platform': 'Strona',
                'ownership': 'unknown',
                'state': 'found',
                'data': json.dumps({'alias': alias}),
            }

        nodes = [
            node(1, 'https://github.com/fictional', 'fictional'),
            node(2, 'https://linktr.ee/fictional', 'fictional'),
            node(3, 'https://beacons.ai/unrelated', 'unrelated'),
        ]
        data = {'nodes': nodes, 'evidence': [], 'focus': []}
        p = priorities(data, {'active': True, 'terms': ['fictional'], 'criteria': {}})
        self.assertGreater(p[2]['priority'], p[1]['priority'])
        self.assertFalse(p[3]['expand'])
        self.assertEqual(nodes[1]['ownership'], 'unknown')
        data['focus'] = [{'node': 1}]
        p = priorities(data, {'active': True, 'terms': ['fictional'], 'criteria': {}})
        self.assertGreater(p[1]['priority'], p[2]['priority'])
        self.assertEqual(bridge_bonus('https://linktr.ee.attacker.example/fictional'), 0)
