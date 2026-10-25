import unittest
from nicktrail.definition_import import convert


class ImportLimits20Tests(unittest.TestCase):
    def test_sherlock_limit_exclusion_and_import_provenance(self):
        payload = {name: {'url': 'https://' + name + '.example/{}'} for name in ('first', 'second', 'third')}
        r = convert(
            'Sherlock',
            payload,
            'a' * 40,
            'MIT License\nCopyright (c) 2019 Sherlock Project',
            limit=1,
            excluded_routes=['https://first.example/{nick}'],
        )
        self.assertEqual(len(r['services']), 1)
        self.assertEqual(r['services'][0]['name'], 'second')
        self.assertTrue(r['services'][0]['provenance']['imported_at'])
        self.assertTrue(r['imported_at'])
