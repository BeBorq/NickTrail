import json
import unittest
import test_discovery
from nicktrail.engine import scan
from nicktrail.demo import FixtureClient


class FocusTests(unittest.TestCase):
    setUp = test_discovery.DiscoveryTests.setUp
    tearDown = test_discovery.DiscoveryTests.tearDown

    def test_focus_does_not_confirm_ownership(self):
        id = self.store.add(self.project, 'https://github.com/fictional-nicktrail', depth=7)
        self.store.set_focus(self.project, id)
        self.assertEqual(self.store.node(id)['ownership'], 'unknown')
        client = FixtureClient()
        scan(self.store, self.project, focused=True, client=client)
        self.assertEqual(client.count, 1)

    def test_focus_expands_only_accepted_links(self):
        id = self.store.add(self.project, 'https://github.com/fictional-nicktrail')
        other = self.store.add(self.project, 'https://nicktrail.example/about', seed=False, depth=9)
        self.store.evidence(
            self.project, id, other, 'links', self.store.node(id)['url'], 'blog', 'Publiczny link'
        )
        self.store.set_focus(self.project, id)
        client = FixtureClient()
        scan(self.store, self.project, focused=True, client=client)
        self.assertEqual(client.count, 1)
        edge = self.store.rows(
            "SELECT id FROM evidence WHERE source=? AND target=? AND relation='links' AND current=1",
            (id, other),
        )[0]['id']
        self.store.decide(edge, 'accepted', True)
        client = FixtureClient()
        scan(self.store, self.project, focused=True, client=client)
        self.assertEqual(client.count, 2)
        self.assertEqual(self.store.node(other)['ownership'], 'unknown')
        client = FixtureClient()
        scan(self.store, self.project, {'depth': 0}, focused=True, client=client)
        self.assertEqual(client.count, 1)

    def test_no_focus_or_rejected_focus(self):
        with self.assertRaises(ValueError):
            scan(self.store, self.project, focused=True)
        id = self.store.add(self.project, 'https://github.com/fictional-nicktrail')
        self.store.decide(id, 'not_mine')
        with self.assertRaises(ValueError):
            self.store.set_focus(self.project, id)

    def test_focus_resume(self):
        id = self.store.add(self.project, 'https://github.com/fictional-nicktrail')
        self.store.set_focus(self.project, id)
        client = FixtureClient()
        scan_id = scan(self.store, self.project, focused=True, client=client, stopped=lambda: True)
        scan(self.store, self.project, resume=scan_id, client=client)
        self.assertEqual(client.count, 1)

    def test_accepted_recommendation_does_not_expand(self):
        root = self.store.add(self.project, 'https://github.com/fictional-nicktrail')
        other = self.store.add(self.project, 'https://nicktrail.example/about')
        self.store.evidence(
            self.project, root, other, 'recommends', self.store.node(root)['url'], 'bio', 'Polecam'
        )
        edge = self.store.rows('SELECT id FROM evidence')[0]['id']
        self.store.decide(edge, 'accepted', True)
        self.store.set_focus(self.project, root)
        client = FixtureClient()
        scan(self.store, self.project, focused=True, client=client)
        self.assertEqual(client.count, 1)

    def test_changed_stable_id_does_not_inherit_last_profile_data(self):
        id = self.store.add(self.project, 'https://github.com/fictional-nicktrail', confirmed=True)
        self.store.execute(
            'UPDATE nodes SET data=? WHERE id=?',
            (json.dumps({'stable_id': 'old-id', 'display': 'Original'}), id),
        )
        scan(self.store, self.project, client=FixtureClient())
        node = self.store.node(id)
        self.assertEqual(node['state'], 'error')
        self.assertEqual(json.loads(node['data'])['stable_id'], 'old-id')
