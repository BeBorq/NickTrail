import json
import unittest
import test_discovery
from nicktrail.engine import scan, record
from nicktrail.demo import FixtureClient
from nicktrail.adapters import read


class ReliabilityTests(unittest.TestCase):
    setUp = test_discovery.DiscoveryTests.setUp
    tearDown = test_discovery.DiscoveryTests.tearDown

    def test_durable_id_rename_keeps_decisions_focus_and_history(self):
        id = self.store.apply_profile(
            self.project, 'https://github.com/old-fictional', {'stable_id': '123', 'alias': 'old-fictional'}
        )
        self.store.decide(id, 'mine')
        self.store.set_focus(self.project, id)
        same = self.store.apply_profile(
            self.project, 'https://github.com/new-fictional', {'stable_id': '123', 'alias': 'new-fictional'}
        )
        self.assertEqual(id, same)
        self.assertEqual(self.store.node(id)['ownership'], 'mine')
        self.assertEqual(self.store.snapshot(self.project)['focus'][0]['node'], id)
        self.assertEqual(len(self.store.snapshot(self.project)['addresses']), 2)
        from nicktrail.related import alias_suggestions

        self.assertEqual(
            {s['alias'] for s in alias_suggestions(self.store, self.project)},
            {'old-fictional', 'new-fictional'},
        )

    def test_reused_url_and_same_nickname_different_services_never_merge(self):
        id = self.store.apply_profile(self.project, 'https://github.com/fictional', {'stable_id': '123'})
        self.store.decide(id, 'mine')
        with self.assertRaises(ValueError):
            self.store.apply_profile(self.project, 'https://github.com/fictional', {'stable_id': '456'})
        other = self.store.apply_profile(self.project, 'https://gitlab.com/fictional', {'stable_id': '123'})
        self.assertNotEqual(id, other)
        self.assertEqual(self.store.node(other)['ownership'], 'unknown')

    def test_known_github_is_fetched_by_id_and_renamed(self):
        id = self.store.apply_profile(self.project, 'https://github.com/old-fictional', {'stable_id': '123'})

        class API:
            def get(self, url):
                assert url == 'https://api.github.com/user/123'
                return {'state': 'found', 'text': '{"id":123,"login":"new-fictional"}'}

        result = read(self.store.node(id), API())
        self.assertEqual(result['canonical_url'], 'https://github.com/new-fictional')

    def test_old_accepted_link_is_not_traversed_after_removal(self):
        id = self.store.add(self.project, 'https://github.com/fictional-nicktrail')
        other = self.store.add(self.project, 'https://deleted-link.example')
        self.store.evidence(self.project, id, other, 'links', self.store.node(id)['url'], 'bio', 'Old link')
        edge = self.store.rows('SELECT id FROM evidence')[0]['id']
        self.store.decide(edge, 'accepted', True)
        self.store.set_focus(self.project, id)
        client = FixtureClient()
        scan(self.store, self.project, client=client, focused=True)
        self.assertEqual(client.count, 1)
        e = self.store.rows('SELECT * FROM evidence WHERE id=?', (edge,))[0]
        self.assertEqual(e['current'], 0)
        self.assertEqual(e['decision'], 'accepted')

    def test_network_failure_preserves_current_evidence_and_last_data(self):
        id = self.store.add(self.project, 'https://github.com/fictional-nicktrail', confirmed=True)
        scan(self.store, self.project, client=FixtureClient())
        old = self.store.node(id)['data']

        class Failure:
            count = 0

            def get(self, url):
                raise TimeoutError()

        scan(self.store, self.project, client=Failure())
        self.assertEqual(self.store.node(id)['data'], old)
        self.assertTrue(all(e['current'] for e in self.store.snapshot(self.project)['evidence']))

    def test_lightweight_result_does_not_erase_profile_fields(self):
        id = self.store.apply_profile(
            self.project,
            'https://github.com/fictional',
            {'stable_id': '123', 'display': 'Name', 'declared_location': 'PL'},
        )
        same = self.store.apply_profile(
            self.project, 'https://github.com/fictional', {'stable_id': '123', 'display': None}, partial=True
        )
        self.assertEqual(id, same)
        self.assertEqual(json.loads(self.store.node(id)['data'])['display'], 'Name')

    def test_ownership_claim_is_not_copied_to_every_url(self):
        from nicktrail.identity import classify

        mine = 'https://github.com/my-fictional'
        other = 'https://github.com/other-fictional'
        text = 'Mój GitHub to ' + mine + ', dzięki ' + other
        self.assertEqual(classify(text, mine), 'claims_ownership')
        self.assertEqual(classify(text, other), 'mentions')
        text = 'Polecam projekt ' + other + '. Mój GitHub to ' + mine
        self.assertEqual(classify(text, mine), 'claims_ownership')
        self.assertEqual(classify(text, other), 'recommends')

    def test_invalid_api_identifier_never_becomes_a_profile(self):
        class BadAPI:
            def get(self, url):
                return {'state': 'found', 'text': '{"id":null,"login":"fictional"}'}

        with self.assertRaises(ValueError):
            read({'url': 'https://github.com/fictional', 'platform': 'GitHub', 'kind': 'profile'}, BadAPI())

    def test_unexpected_failure_is_not_reported_as_completed(self):
        self.store.add(self.project, 'https://github.com/fictional-nicktrail', confirmed=True)

        class Broken:
            count = 0

            def get(self, url):
                raise RuntimeError('fixture failure')

        # rc16: one broken read no longer ends the scan, but it is never hidden either:
        # the profile is recorded as an error with the cause, not as found.
        scan_id = scan(self.store, self.project, client=Broken())
        observation = self.store.rows('SELECT state,detail FROM observations WHERE scan=?', (scan_id,))[0]
        self.assertEqual(observation['state'], 'error')
        self.assertIn('RuntimeError', observation['detail'])
        self.assertNotEqual(self.store.snapshot(self.project)['nodes'][0]['state'], 'found')

    def test_encoded_paths_and_markdown_do_not_make_fake_account_names(self):
        from nicktrail.identity import identify
        from nicktrail.adapters import extract

        self.assertNotEqual(identify('https://github.com/owner%2Frepo')['kind'], 'profile')
        self.assertNotEqual(identify('https://github.com/fake_name')['kind'], 'profile')
        links = extract('Mój GitHub to `https://github.com/fictional`', 'https://fictional.example')
        self.assertEqual(links[0]['url'], 'https://github.com/fictional')
        self.assertEqual(links[0]['relation'], 'claims_ownership')
        links = extract('Mój GitHub to https://GitHub.com/Fictional#bio', 'https://fictional.example')
        self.assertEqual(links[0]['url'], 'https://github.com/fictional')
        self.assertEqual(links[0]['relation'], 'claims_ownership')
