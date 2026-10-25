import json, tempfile, unittest
from pathlib import Path
from nicktrail.storage import Store
from nicktrail.accountentities import api_fields
from nicktrail.graphsignals import analyze
from nicktrail.ranking import evaluate
from nicktrail.pools import classify
from nicktrail.adapters import read


class AccountEntity20Tests(unittest.TestCase):
    def test_platform_organization_is_visible_exact_hit_but_not_person_bridge(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            s = Store(Path(tmp) / 'test.db')
            p = s.project('Fictional')
            try:
                a = s.apply_profile(p, 'https://dev.to/fictional-a', {'alias': 'fictional-a'})
                org = s.apply_profile(
                    p,
                    'https://github.com/fictional',
                    {'alias': 'fictional', **api_fields({'type': 'Organization'})},
                )
                b = s.apply_profile(p, 'https://gitlab.com/fictional-b', {'alias': 'fictional-b'})
                s.decide(a, 'mine')
                for source, target in ((a, org), (org, b)):
                    s.evidence(
                        p, source, target, 'links', s.node(source)['url'], 'bio', 'Fictional project link'
                    )
                snapshot = s.snapshot(p)
                self.assertFalse(analyze(snapshot).get(b))
                r = evaluate(snapshot, {}, ['fictional'])
                pool = classify(snapshot, r, ['fictional'])[str(org)]
                self.assertTrue(pool['exact_supplied_alias'])
                self.assertTrue(pool['primary_visible'])
                self.assertEqual(pool['pool'], 'POSSIBLE_LEADS')
                self.assertEqual(pool['identity_evidence'], 'INSUFFICIENT')
                self.assertEqual(s.node(org)['ownership'], 'unknown')
                from nicktrail.frontier import priorities

                self.assertFalse(
                    priorities(snapshot, {'active': True, 'terms': ['fictional'], 'criteria': {}})[org][
                        'expand'
                    ]
                )
            finally:
                s.db.close()

    def test_api_type_is_explicit_and_user_does_not_prove_a_person(self):
        class C:
            def get(self, url):
                return {
                    'state': 'found',
                    'text': json.dumps(
                        {'id': 123, 'login': 'fictional', 'type': 'Organization', 'bio': 'public project'}
                    ),
                }

        r = read({'url': 'https://github.com/fictional', 'platform': 'GitHub', 'kind': 'profile'}, C())
        self.assertEqual(r['data']['entity_type'], 'organization')
        self.assertEqual(api_fields({'type': 'User'})['entity_type'], 'account')
        self.assertEqual(api_fields({'name': 'Fictional Org'}), {})
