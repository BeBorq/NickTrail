import json, unittest
from nicktrail.publicprofile import ProfileHTML
from nicktrail.freeprofiles import lookup
from nicktrail.evaluation import benchmark, builtin_cases


class StructuredTests(unittest.TestCase):
    def page(self, data):
        p = ProfileHTML()
        p.feed('<script type="application/ld+json">' + json.dumps(data) + '</script>')
        return p

    def test_profilepage_mainentity_contacts_and_sameas(self):
        base = 'https://keybase.io/fictional'
        data = {
            '@type': 'ProfilePage',
            'url': base,
            'mainEntity': {
                '@type': 'Person',
                'name': 'Fictional Person',
                'url': 'https://personal.example',
                'email': 'public-person@example.org',
                'sameAs': [{'@id': 'https://github.com/fictional'}],
            },
        }
        p = self.page(data)
        self.assertEqual(len(p.persons(base)), 1)
        self.assertEqual(p.same_as(base), ['https://github.com/fictional'])
        proof = p.person_evidence(base)
        self.assertEqual(
            {e.get('url') or e.get('email') for e in proof},
            {'https://github.com/fictional', 'https://personal.example', 'public-person@example.org'},
        )
        self.assertTrue(all(e['location'].startswith('jsonld.') for e in proof))

        class Client:
            def get(self, url):
                return {
                    'state': 'found',
                    'text': '<script type="application/ld+json">' + json.dumps(data) + '</script>',
                    'url': url,
                }

        self.assertEqual(lookup('Keybase:fictional', Client())['state'], 'found')

    def test_article_author_and_other_profile_never_become_owner(self):
        for kind, url in [
            ('Article', 'https://keybase.io/fictional'),
            ('ProfilePage', 'https://keybase.io/other'),
        ]:
            p = self.page(
                {
                    '@type': kind,
                    'url': url,
                    'mainEntity': {
                        '@type': 'Person',
                        'email': 'person@example.org',
                        'sameAs': 'https://github.com/other',
                    },
                }
            )
            self.assertEqual(p.person_evidence('https://keybase.io/fictional'), [])

    def test_malformed_type_and_case_sensitive_paths_remain_uncertain(self):
        self.assertEqual(
            self.page({'@type': None, 'url': 'https://example.org'}).persons('https://example.org'), []
        )
        p = self.page(
            {'@type': 'Person', 'url': 'https://example.org/Alice', 'sameAs': 'https://github.com/fixture'}
        )
        self.assertEqual(p.same_as('https://example.org/alice'), [])

    def test_benchmark_metrics_and_graph_ablation(self):
        from unittest.mock import patch

        report = benchmark()
        self.assertEqual(report['cases'], 40)
        self.assertEqual(report['hit_at_1'], 1)
        with patch('nicktrail.ranking.analyze', return_value={}):
            before = benchmark()
        self.assertGreater(report['mrr'], before['mrr'])
        self.assertGreater(report['hit_at_1'], before['hit_at_1'])
        self.assertEqual(report['recall_at_5'], 1)
        self.assertAlmostEqual(report['precision_at_5'], 0.2)
