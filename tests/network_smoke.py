"""Opt-in live tests, excluded from unittest discovery; no personal audit."""

import unittest
import json
from nicktrail.adapters import read
from nicktrail.network import Client


class LiveTests(unittest.TestCase):
    def test_fetch_known_accounts_by_durable_id(self):
        from nicktrail.search import lookup

        for platform, alias in (('GitHub', 'octocat'), ('DEV', 'ben'), ('Bluesky', 'bsky.app')):
            with self.subTest(platform=platform):
                client = Client(queries=5, seconds=30)
                result = lookup(platform, alias, client)
                self.assertEqual(result['state'], 'found', result)
                match = result['matches'][0]
                from nicktrail.identity import identify

                node = identify(match['url']) | {'data': json.dumps(match['data'])}
                refreshed = read(node, client)
                self.assertEqual(refreshed['state'], 'found', refreshed)
                self.assertEqual(refreshed['data']['stable_id'], match['data']['stable_id'])

    def test_gitlab_durable_id_access(self):
        from nicktrail.search import lookup
        from nicktrail.identity import identify

        client = Client(queries=5, seconds=30)
        result = lookup('GitLab', 'gitlab-bot', client)
        self.assertEqual(result['state'], 'found', result)
        match = result['matches'][0]
        refreshed = read(identify(match['url']) | {'data': json.dumps(match['data'])}, client)
        if refreshed['state'] == 'blocked':
            self.skipTest('GitLab odmawia odczytu po ID; dokładny publiczny lookup pozostaje dostępny')
        self.assertEqual(refreshed['state'], 'found', refreshed)

    def test_new_public_adapters(self):
        from nicktrail.search import lookup

        for platform, alias in (
            ('Roblox', 'Roblox'),
            ('GitLab', 'gitlab-bot'),
            ('DEV', 'ben'),
            ('Bluesky', 'bsky.app'),
        ):
            with self.subTest(platform=platform):
                result = lookup(platform, alias, Client(queries=5, seconds=30))
                self.assertEqual(result['state'], 'found', result)
                self.assertTrue(result['matches'])

    def test_github_official_example_account(self):
        result = read(
            {'url': 'https://github.com/octocat', 'platform': 'GitHub', 'kind': 'profile'},
            Client(queries=3, seconds=30),
        )
        self.assertEqual(result['state'], 'found', result)
        self.assertEqual(result['data']['stable_id'], '583231')

    def test_public_example_page(self):
        result = read(
            {'url': 'https://example.com', 'platform': 'Strona', 'kind': 'page'},
            Client(queries=3, seconds=30),
        )
        self.assertEqual(result['state'], 'found', result)


if __name__ == '__main__':
    unittest.main()
