import json
import unittest
from unittest.mock import patch
import test_discovery
from nicktrail.exporting import export
from nicktrail.keyed import steam_lookup, mastodon_lookup, read_keyed


class AdditionsTests(unittest.TestCase):
    setUp = test_discovery.DiscoveryTests.setUp
    tearDown = test_discovery.DiscoveryTests.tearDown

    def test_html_export_escapes_untrusted_content_and_redacts(self):
        self.store.add(self.project, '<script>alert(1)</script>', 'display')
        self.store.add(self.project, 'private@example.com', 'email')
        text = export(self.store, self.project, 'html', omit_email=True)
        self.assertNotIn('<script>', text)
        self.assertIn('&lt;script&gt;', text)
        self.assertNotIn('private@example.com', text)

    def test_keyed_steam_uses_stable_id_without_saving_secret(self):
        class Client:
            def get(self, url):
                return {
                    'state': 'found',
                    'text': json.dumps(
                        {'response': {'success': 1, 'steamid': '123'}}
                        if 'Resolve' in url
                        else {'response': {'players': [{'steamid': '123', 'personaname': 'Fikcja'}]}}
                    ),
                }

        with patch.dict('os.environ', {'NICKTRAIL_STEAM_KEY': 'fictional-secret'}):
            result = steam_lookup('fictional', Client())
        self.assertEqual(result['data']['stable_id'], '123')
        self.assertNotIn('fictional-secret', json.dumps(result))

    def test_mastodon_keeps_instance_and_never_sends_token_elsewhere(self):
        class Client:
            count = 0

            def get(self, url, headers=None):
                self.count += 1
                assert url.startswith('https://fictional.example/')
                assert headers == {'Authorization': 'Bearer fictional-token'}
                return {
                    'state': 'found',
                    'text': json.dumps(
                        {
                            'id': '1',
                            'username': 'fictional',
                            'acct': 'fictional',
                            'fields': [],
                            'note': '<a href="https://github.com/fictional">Mon profil</a>',
                        }
                    ),
                }

        with patch.dict(
            'os.environ',
            {
                'NICKTRAIL_MASTODON_INSTANCE': 'https://fictional.example',
                'NICKTRAIL_MASTODON_TOKEN': 'fictional-token',
            },
        ):
            client = Client()
            result = mastodon_lookup('fictional', client)
            self.assertIn('fictional.example', result['data']['stable_id'])
            self.assertNotIn('fictional-token', json.dumps(result))
            rejected = read_keyed({'platform': 'Mastodon', 'url': 'https://other.example/@fictional'}, client)
            self.assertEqual(rejected['state'], 'unsupported')
            self.assertEqual(client.count, 1)

    def test_structured_social_field_is_link_not_identity(self):
        from nicktrail.adapters import public_account_fields

        evidence = public_account_fields({'github_username': 'fictional', 'twitter_username': 'bad/name'})
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]['url'], 'https://github.com/fictional')
        self.assertEqual(evidence[0]['relation'], 'links')

    def test_credentials_never_follow_cross_host_redirect(self):
        from nicktrail.network import Client

        class Response:
            status = 302

            def getheader(self, key, default=''):
                return 'https://other.example/' if key == 'Location' else default

        class Connection:
            count = 0

            def __init__(self, *args, **kwargs):
                pass

            def request(self, *args, **kwargs):
                Connection.count += 1

            def getresponse(self):
                return Response()

            def close(self):
                pass

        with (
            patch('nicktrail.network.PinnedTLS', Connection),
            patch('nicktrail.network.public_addresses', return_value=['93.184.216.34']),
        ):
            result = Client(delay=0).get(
                'https://fictional.example/', headers={'Authorization': 'Bearer fictional'}
            )
            self.assertEqual(result['state'], 'blocked')
            result = Client(delay=0).get('https://fictional.example/?key=fictional')
            self.assertEqual(result['state'], 'blocked')
            self.assertEqual(Connection.count, 2)

    def test_resolver_post_never_follows_redirect(self):
        from nicktrail.network import Client

        class Response:
            status = 307

            def getheader(self, key, default=''):
                return 'https://other.example/' if key == 'Location' else default

        class Connection:
            def __init__(self, *args, **kwargs):
                pass

            def request(self, *args, **kwargs):
                pass

            def getresponse(self):
                return Response()

            def close(self):
                pass

        with (
            patch('nicktrail.network.PinnedTLS', Connection),
            patch('nicktrail.network.public_addresses', return_value=['93.184.216.34']),
        ):
            result = Client(delay=0).post_json(
                'https://users.roblox.com/v1/usernames/users', {'usernames': ['fictional']}
            )
            self.assertEqual(result['state'], 'blocked')

    def test_exports_have_working_profile_links_but_never_script_links(self):
        id = self.store.add(self.project, 'https://github.com/fictional')
        self.store.evidence(
            self.project, id, id, 'mentions', 'javascript:alert(1)', 'imported_post', 'Untrusted source'
        )
        html = export(self.store, self.project, 'html')
        self.assertIn('href="https://github.com/fictional"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertNotIn('href="javascript:', html)
        self.assertIn('<https://github.com/fictional>', export(self.store, self.project, 'markdown'))
