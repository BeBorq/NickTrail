import json
import unittest
import test_discovery
from unittest.mock import patch
from test_multisearch import PublicFixture
from nicktrail.search import discover, results, hints
from nicktrail.related import terms_for, alias_suggestions
from nicktrail.network import Limit


class RelatedFixture(PublicFixture):
    def get(self, url):
        body = None
        if '/search/users?' in url:
            body = {'items': [{'id': 10, 'login': 'fictional-dev'}]}
        elif 'users?search=' in url:
            body = [{'id': 11, 'username': 'fictional_more'}]
        elif 'users/search?keyword=' in url:
            body = {'data': [{'id': 12, 'name': 'fictional123', 'displayName': 'Fikcyjna postać'}]}
        elif '/users/old-fictional' in url:
            body = {'id': 20, 'login': 'old-fictional'}
        if body is None:
            return super().get(url)
        self.count += 1
        self.calls.append(url)
        return {'state': 'found', 'text': json.dumps(body)}


class RelatedTests(unittest.TestCase):
    def setUp(self):
        test_discovery.DiscoveryTests.setUp(self)
        self.config = patch('nicktrail.keyed.configured', return_value=False)
        self.config.start()
        self.addCleanup(self.config.stop)

    tearDown = test_discovery.DiscoveryTests.tearDown

    def test_different_names_are_candidates_not_identity_links(self):
        client = RelatedFixture()
        discover(self.store, self.project, 'fictional', client=client, related=True)
        self.assertEqual(client.count, 12)
        found = [n for n in self.store.snapshot(self.project)['nodes'] if n['state'] == 'found']
        variants = [
            n
            for n in found
            if json.loads(n['data']).get('alias') in ('fictional-dev', 'fictional_more', 'fictional123')
        ]
        self.assertEqual(len(variants), 3)
        self.assertTrue(all(n['ownership'] == 'unknown' for n in variants))
        es = self.store.snapshot(self.project)['evidence']
        self.assertFalse(any(e['target'] in [n['id'] for n in variants] for e in es))
        self.assertTrue(
            all(
                any(
                    h['node'] == n['id'] and h['basis'] == 'service_search'
                    for h in hints(self.store, self.project)
                )
                for n in variants
            )
        )

    def test_explicit_alias_is_traced_without_inferred_ownership(self):
        discover(
            self.store,
            self.project,
            'fictional',
            platforms=['GitHub'],
            aliases=['old-fictional'],
            client=RelatedFixture(),
        )
        hint = next(h for h in hints(self.store, self.project) if h['basis'] == 'provided_alias')
        self.assertEqual(hint['term'], 'old-fictional')
        self.assertEqual(self.store.node(hint['node'])['ownership'], 'unknown')

    def test_partial_search_keeps_completed_exact_lookup_and_resumes(self):
        class Budget(RelatedFixture):
            def get(self, url):
                if '/search/users?' in url:
                    raise Limit()
                return super().get(url)

        id = discover(
            self.store, self.project, 'fictional', platforms=['GitHub'], related=True, client=Budget()
        )
        run = results(self.store, self.project)[0]
        self.assertEqual(run['run']['status'], 'limited')
        self.assertEqual(run['sources'][0]['state'], 'partial')
        self.assertEqual(run['tasks'][0]['state'], 'found')
        client = RelatedFixture()
        discover(self.store, self.project, resume=id, client=client)
        self.assertEqual(client.count, 1)
        self.assertEqual(results(self.store, self.project)[0]['run']['status'], 'completed')

    def test_alias_limits_and_case_insensitive_dedup(self):
        self.assertEqual(
            terms_for('fictional', ['FICTIONAL', 'old-fictional']), ['fictional', 'old-fictional']
        )
        with self.assertRaises(ValueError):
            terms_for('fictional', ['a', 'b', 'c', 'd', 'e'])
        with self.assertRaises(ValueError):
            discover(self.store, self.project, 'fictional', aliases=['../bad'])
        self.assertFalse(self.store.snapshot(self.project)['nodes'])

    def test_alias_suggestions_ignore_mentions_repositories_and_rejections(self):
        root = self.store.apply_profile(
            self.project, 'https://github.com/fictional', {'stable_id': '1', 'alias': 'fictional'}
        )
        good = self.store.add(self.project, 'https://dev.to/old-fictional')
        other = self.store.add(self.project, 'https://github.com/stranger')
        self.store.evidence(
            self.project, root, good, 'claims_ownership', self.store.node(root)['url'], 'bio', 'My profile'
        )
        self.store.evidence(
            self.project, root, other, 'mentions', self.store.node(root)['url'], 'bio', 'Thanks'
        )
        self.store.set_focus(self.project, root)
        suggested = alias_suggestions(self.store, self.project)
        self.assertEqual({s['alias'] for s in suggested}, {'fictional', 'old-fictional'})
        self.store.decide(good, 'not_mine')
        self.assertEqual([s['alias'] for s in alias_suggestions(self.store, self.project)], ['fictional'])

    def test_candidate_budget_is_explicit_and_does_not_claim_completeness(self):
        client = RelatedFixture()
        discover(
            self.store,
            self.project,
            'fictional',
            platforms=['Bluesky'],
            related=True,
            options={'candidates': 1},
            client=client,
        )
        run = results(self.store, self.project)[0]
        self.assertEqual(run['run']['status'], 'limited')
        self.assertEqual(run['sources'][0]['state'], 'partial')
        self.assertEqual(len(hints(self.store, self.project)), 2)
        self.assertIn('limit kandydatów', run['sources'][0]['detail'])
