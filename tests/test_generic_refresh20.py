import json, unittest
from unittest.mock import patch
from nicktrail.engines import read


class GenericRefresh20Tests(unittest.TestCase):
    def test_numeric_slug_uses_observed_alias_and_cannot_replace_stable_id(self):
        node = {
            'url': 'https://forum.example/u/1-fictional',
            'platform': 'FictionalForum',
            'data': json.dumps({'alias': 'fictional', 'stable_id': '1'}),
        }
        with (
            patch('nicktrail.engines.instances', return_value={'FictionalForum': {'engine': 'flarum'}}),
            patch(
                'nicktrail.engines.lookup_platform',
                return_value={
                    'state': 'found',
                    'matches': [
                        {'url': node['url'], 'data': {'alias': 'fictional', 'stable_id': '2'}, 'evidence': []}
                    ],
                },
            ) as lookup,
        ):
            result = read(node, None)
            self.assertEqual(lookup.call_args.args[1], 'fictional')
            self.assertEqual(result['state'], 'partial')
            self.assertIn('PERSISTENT_ID_CONFLICT', result['detail'])
