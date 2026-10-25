import json
import unittest
import io
from contextlib import redirect_stdout
from unittest.mock import patch
import test_discovery
from nicktrail.search import discover, results
from nicktrail.network import Limit, Client


class PublicFixture:
    def __init__(self):
        self.count = 0
        self.calls = []

    def get(self, url):
        self.count += 1
        self.calls.append(url)
        if 'api.github.com/search/' in url:
            data = {'items': [{'id': 1, 'login': 'fictional'}]}
        elif 'api.github.com' in url:
            data = {
                'id': 1,
                'login': 'fictional',
                'bio': 'Mój GitHub to https://github.com/another-fictional',
            }
        elif 'users.roblox.com/v1/users/' in url:
            data = {'id': 42, 'name': 'fictional', 'description': 'Public description'}
        elif 'users/search?keyword=' in url:
            data = {'data': [{'id': 42, 'name': 'fictional'}]}
        elif 'gitlab.com/api' in url:
            data = [{'id': 2, 'username': 'fictional', 'name': 'Fikcyjna postać'}]
        elif 'codeberg.org/api' in url or 'gitea.com/api' in url:
            data = {'id': 4, 'login': 'fictional'}
        elif 'dev.to/api' in url:
            assert '/users/by_username?url=' in url
            data = {'id': 3, 'username': 'fictional', 'name': 'Fikcyjna postać'}
        elif 'searchActors' in url:
            data = {
                'actors': [
                    {'did': 'did:plc:fiction', 'handle': 'fictional.bsky.social', 'displayName': 'Fikcja'},
                    {'did': 'did:plc:other', 'handle': 'another.example', 'displayName': 'Fikcja'},
                ]
            }
        elif 'getProfile' in url:
            data = {
                'did': 'did:plc:fiction',
                'handle': 'fictional.bsky.social',
                'description': 'https://fictional.example',
            }
        else:
            raise AssertionError(url)
        return {'state': 'found', 'text': json.dumps(data)}

    def post_json(self, url, payload):
        self.count += 1
        self.calls.append(url)
        assert payload['usernames'] == ['fictional']
        return {
            'state': 'found',
            'text': json.dumps({'data': [{'id': 42, 'name': 'fictional', 'displayName': 'Fikcyjna postać'}]}),
        }


class MultiSearchTests(unittest.TestCase):
    def setUp(self):
        test_discovery.DiscoveryTests.setUp(self)
        self.key_config = patch('nicktrail.keyed.configured', return_value=False)
        self.key_config.start()
        self.addCleanup(self.key_config.stop)

    tearDown = test_discovery.DiscoveryTests.tearDown

    def test_five_sources_and_two_bluesky_results(self):
        client = PublicFixture()
        id = discover(self.store, self.project, 'fictional', client=client)
        self.assertEqual(client.count, 8)
        found = [n for n in self.store.snapshot(self.project)['nodes'] if n['state'] == 'found']
        self.assertEqual(len(found), 7)
        self.assertTrue(all(n['ownership'] == 'unknown' for n in found))
        self.assertEqual(
            next(n for n in found if n['platform'] == 'Roblox')['url'],
            'https://www.roblox.com/users/42/profile',
        )
        from nicktrail.search import ACTIVE, LIMITED

        self.assertEqual(
            {s['platform'] for s in results(self.store, self.project)[0]['sources']},
            set(ACTIVE) | set(LIMITED),
        )
        self.assertEqual(results(self.store, self.project)[0]['run']['status'], 'completed')
        self.assertTrue(
            any(
                n['state'] == 'unverified'
                for n in self.store.snapshot(self.project)['nodes']
                if n['url'] == 'https://github.com/another-fictional'
            )
        )

    def test_pause_resume_and_decisions(self):
        client = PublicFixture()
        id = discover(self.store, self.project, 'fictional', client=client, stopped=lambda: True)
        self.assertEqual(client.count, 0)
        discover(self.store, self.project, client=client, resume=id)
        node = next(
            n
            for n in self.store.snapshot(self.project)['nodes']
            if n['platform'] == 'GitHub' and n['state'] == 'found'
        )
        self.store.decide(node['id'], 'not_mine')
        discover(self.store, self.project, 'fictional', client=PublicFixture())
        self.assertEqual(self.store.node(node['id'])['ownership'], 'not_mine')

    def test_limit_does_not_invent_absence(self):
        class Budget(PublicFixture):
            def get(self, url):
                raise Limit()

        id = discover(self.store, self.project, 'fictional', client=Budget())
        result = results(self.store, self.project)[0]
        self.assertEqual(result['run']['status'], 'limited')
        self.assertEqual(result['sources'][0]['state'], 'pending')
        self.assertFalse(any(n['state'] == 'found' for n in self.store.snapshot(self.project)['nodes']))

    def test_blocked_source_does_not_stop_others(self):
        class Blocked(PublicFixture):
            def get(self, url):
                if 'api.github.com' in url:
                    self.count += 1
                    return {'state': 'blocked', 'detail': 'HTTP 403'}
                return super().get(url)

        discover(self.store, self.project, 'fictional', client=Blocked())
        sources = results(self.store, self.project)[0]['sources']
        self.assertEqual(sources[0]['state'], 'blocked')
        self.assertTrue(any(s['platform'] == 'DEV' and s['state'] == 'found' for s in sources))

    def test_unsupported_sources_do_not_create_fake_profiles(self):
        discover(self.store, self.project, 'fictional', platforms=['Steam'], client=PublicFixture())
        self.assertEqual(len(self.store.snapshot(self.project)['nodes']), 1)
        self.assertTrue(
            all(s['state'] == 'unsupported' for s in results(self.store, self.project)[0]['sources'])
        )

    def test_invalid_nickname_or_sources(self):
        for nick in ('../secret', 'https://example.com', 'a b'):
            with self.assertRaises(ValueError):
                discover(self.store, self.project, nick)
        with self.assertRaises(ValueError):
            discover(self.store, self.project, 'fictional', platforms=['invented'])
        with self.assertRaises(ValueError):
            Client().post_json('https://example.com/reset', {})

    def test_cli_search_defaults_to_all_public_sources(self):
        from nicktrail.__main__ import main
        from pathlib import Path

        path = str(Path(self.tmp.name) / 'cli.sqlite3')
        with (
            patch('sys.argv', ['nicktrail', '--db', path, 'create', 'Fikcyjny']),
            redirect_stdout(io.StringIO()),
        ):
            main()
        out = io.StringIO()
        with (
            patch('sys.argv', ['nicktrail', '--db', path, 'search', '1', 'fictional']),
            patch('nicktrail.search.Client', return_value=PublicFixture()),
            redirect_stdout(out),
        ):
            main()
        self.assertEqual(len([s for s in json.loads(out.getvalue())['sources'] if s['state'] == 'found']), 6)

    def test_missing_exact_profile_keeps_last_data_and_decision(self):
        discover(self.store, self.project, 'fictional', platforms=['GitHub'], client=PublicFixture())
        node = next(n for n in self.store.snapshot(self.project)['nodes'] if n['state'] == 'found')
        self.store.decide(node['id'], 'mine')

        class Missing(PublicFixture):
            def get(self, url):
                self.count += 1
                return {'state': 'not_found', 'detail': 'HTTP 404'}

        discover(self.store, self.project, 'fictional', platforms=['GitHub'], client=Missing())
        current = self.store.node(node['id'])
        self.assertEqual(current['data'], node['data'])
        self.assertEqual(current['state'], 'not_found')
        self.assertEqual(current['ownership'], 'mine')

    def test_bluesky_search_absence_is_not_account_absence(self):
        discover(self.store, self.project, 'fictional', platforms=['Bluesky'], client=PublicFixture())
        node = next(n for n in self.store.snapshot(self.project)['nodes'] if n['state'] == 'found')

        class Missing(PublicFixture):
            def get(self, url):
                self.count += 1
                return {'state': 'found', 'text': '{"actors":[]}'}

        discover(self.store, self.project, 'fictional', platforms=['Bluesky'], client=Missing())
        self.assertEqual(self.store.node(node['id'])['state'], 'found')

    def test_discovery_identity_change_requires_review(self):
        discover(self.store, self.project, 'fictional', platforms=['GitHub'], client=PublicFixture())
        node = next(n for n in self.store.snapshot(self.project)['nodes'] if n['state'] == 'found')
        self.store.decide(node['id'], 'mine')

        class Changed(PublicFixture):
            def get(self, url):
                self.count += 1
                return {'state': 'found', 'text': '{"id":999,"login":"fictional"}'}

        discover(self.store, self.project, 'fictional', platforms=['GitHub'], client=Changed())
        self.assertEqual(self.store.node(node['id'])['state'], 'error')
        self.assertEqual(json.loads(self.store.node(node['id'])['data'])['stable_id'], '1')
