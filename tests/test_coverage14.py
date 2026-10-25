import json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from nicktrail.providers import lookup, REGISTRY
from nicktrail.community import STACK, read
from nicktrail.forums import HOSTS
from nicktrail.identity import identify
from nicktrail.storage import Store
from nicktrail.search import discover


class Fixture:
    def __init__(self, body, state='found'):
        self.body = body
        self.state = state
        self.calls = []
        self.count = 0
        self.cooldowns = []

    def get(self, url, **kw):
        self.count += 1
        self.calls.append(url)
        return {'state': self.state, 'text': json.dumps(self.body), 'url': url}

    def defer_host(self, host, seconds):
        self.cooldowns.append((host, seconds))


class CoverageTests(unittest.TestCase):
    def test_all_forum_hosts_have_dispatch_and_identity(self):
        self.assertEqual(len(HOSTS), 12)
        for id, host in HOSTS.items():
            with self.subTest(id=id):
                client = Fixture(
                    {
                        'user': {
                            'id': 42,
                            'username': 'fixture',
                            'bio_raw': 'My old account https://github.com/oldname',
                        }
                    }
                )
                self.assertEqual(lookup(id, 'fixture', client)['state'], 'found')
                self.assertEqual(identify('https://' + host + '/u/fixture')['platform'], id)
                self.assertIn(
                    'github.com/oldname', lookup(id, 'fixture', client)['matches'][0]['evidence'][0]['url']
                )

    def test_stack_search_is_not_exact_identity_and_extracts_website(self):
        body = {
            'items': [
                {
                    'user_id': 42,
                    'display_name': 'Other Nick',
                    'about_me': '<a href="https://github.com/oldnick">my code</a>',
                    'website_url': 'https://personal.example',
                }
            ],
            'has_more': False,
        }
        for id in STACK:
            result = lookup(id, 'fixture', Fixture(body))
            self.assertEqual(result['state'], 'found')
            match = result['matches'][0]
            self.assertNotIn('alias', match['data'])
            self.assertEqual(len(match['evidence']), 2)
            self.assertEqual(identify(match['url'] + '/name')['url'], match['url'])

    def test_backoff_and_quota_stop_more_requests(self):
        c = Fixture({'items': [], 'backoff': 60, 'quota_remaining': 0})
        self.assertEqual(lookup('StackOverflow', 'fixture', c)['state'], 'partial')
        self.assertEqual(c.cooldowns, [('api.stackexchange.com', 60)])

    def test_chess_mismatched_id_not_a_hit(self):
        self.assertEqual(
            lookup('ChessCom', 'fixture', Fixture({'username': 'other', 'player_id': 42}))['state'], 'partial'
        )
        self.assertEqual(
            lookup('Lichess', 'fixture', Fixture({'username': 'fixture', 'id': 'other'}))['state'], 'partial'
        )

    def test_lichess_description_links_and_chess_id(self):
        r = lookup(
            'Lichess',
            'fixture',
            Fixture(
                {
                    'username': 'Fixture',
                    'id': 'fixture',
                    'profile': {'bio': 'My account https://github.com/oldname'},
                }
            ),
        )
        self.assertEqual(r['state'], 'found')
        self.assertEqual(len(r['evidence']), 1)
        self.assertNotIn('stable_id', r['data'])
        r = lookup('ChessCom', 'fixture', Fixture({'username': 'Fixture', 'player_id': 42}))
        self.assertEqual(r['data']['stable_id'], '42')

    def test_optional_indexes_do_not_require_brave_and_deduplicate(self):
        bodies = {
            'SearXNG': {
                'results': [
                    {'url': 'https://site.example/a'},
                    {'url': 'https://site.example/a'},
                    {'url': 'javascript:bad'},
                ]
            },
            'Mojeek': {
                'response': {
                    'status': 'OK',
                    'results': [{'url': 'https://site.example/a', 'desc': 'public text'}],
                }
            },
            'GoogleCSE': {'items': [{'link': 'https://site.example/a', 'snippet': 'public text'}]},
        }
        env = {
            'NICKTRAIL_SEARXNG_URL': 'https://search.example',
            'NICKTRAIL_MOJEEK_KEY': 'test-key',
            'NICKTRAIL_GOOGLE_KEY': 'test-key',
            'NICKTRAIL_GOOGLE_CX': 'engine',
        }
        with patch.dict(os.environ, env, clear=True):
            for provider, body in bodies.items():
                result = lookup(provider, 'old alias', Fixture(body))
                self.assertEqual(len(result['matches']), 1)
                self.assertEqual(result['matches'][0]['evidence'], [])
                self.assertTrue(result['matches'][0]['data']['indexed_only'])

    def test_missing_or_malformed_index_and_partial(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(lookup('SearXNG', 'fixture', None)['state'], 'unsupported')
        with patch.dict(os.environ, {'NICKTRAIL_SEARXNG_URL': 'https://search.example'}, clear=True):
            with self.assertRaises(ValueError):
                lookup('SearXNG', 'fixture', Fixture({}))
            self.assertEqual(
                lookup('SearXNG', 'fixture', Fixture({'results': [], 'unresponsive_engines': ['a']}))[
                    'state'
                ],
                'partial',
            )

    def test_simultaneous_indexes_merge_nodes_and_keep_separate_hints(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            s = Store(str(Path(tmp) / 'test.db'))
            p = s.project('fixture')

            def result(platform, term, client):
                return {
                    'state': 'found',
                    'matches': [
                        {
                            'url': 'https://site.example/a',
                            'data': {
                                'indexed_only': True,
                                'search_title': platform + ' title',
                                'search_snippet': platform + ' snippet',
                            },
                            'evidence': [],
                        }
                    ],
                }

            env = {
                'NICKTRAIL_SEARXNG_URL': 'https://search.example',
                'NICKTRAIL_GOOGLE_KEY': 'test',
                'NICKTRAIL_GOOGLE_CX': 'engine',
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch('nicktrail.search.lookup', side_effect=result),
            ):
                id = discover(s, p, 'fixture', platforms=['SearXNG', 'GoogleCSE'], client=Fixture({}))
            self.assertEqual(len(s.rows('select distinct node from candidate_hints')), 1)
            node = s.node(s.rows('select node from candidate_hints')[0]['node'])
            self.assertEqual(node['state'], 'unverified')
            self.assertEqual(len(s.rows('select platform from search_tasks where search=?', (id,))), 2)
            origins = s.rows('select platform,snippet from indexed_results where search=?', (id,))
            self.assertEqual({o['platform'] for o in origins}, {'SearXNG', 'GoogleCSE'})
            self.assertEqual({o['snippet'] for o in origins}, {'SearXNG snippet', 'GoogleCSE snippet'})
            s.db.close()
