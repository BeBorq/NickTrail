import json
import unittest

from nicktrail.adapters import read
from nicktrail.entitylinks import CLAIM_LOCATIONS

USER = {'id': 101, 'login': 'adafict', 'bio': 'Compilers', 'blog': '', 'avatar_url': ''}


class Client:
    def __init__(self, social):
        self.social = social
        self.urls = []

    def get(self, url, headers=None):
        self.urls.append(url)
        if url.endswith('/social_accounts'):
            return self.social
        return {'state': 'found', 'text': json.dumps(USER)}


NODE = {
    'id': 1,
    'url': 'https://github.com/adafict',
    'platform': 'GitHub',
    'kind': 'profile',
    'data': '{}',
    'ownership': 'mine',
}


class GithubSocialTests(unittest.TestCase):
    def test_owner_declared_social_accounts_become_claim_links(self):
        social = {
            'state': 'found',
            'text': json.dumps(
                [
                    {'provider': 'twitter', 'url': 'https://twitter.com/ada_fx'},
                    {'provider': 'generic', 'url': 'https://hackerone.com/adasec'},
                    {'provider': 'bad', 'url': 'javascript:alert(1)'},
                    'not a dict',
                ]
            ),
        }
        client = Client(social)
        out = read(NODE, client)
        self.assertEqual(out['state'], 'found')
        declared = [e for e in out['evidence'] if e['location'] == 'github.social_accounts']
        self.assertEqual(
            sorted(e['url'] for e in declared), ['https://hackerone.com/adasec', 'https://x.com/ada_fx']
        )
        self.assertTrue(all(e['relation'] == 'links' for e in declared))
        self.assertIn('https://api.github.com/users/adafict/social_accounts', client.urls)
        self.assertIn('github.social_accounts', CLAIM_LOCATIONS)

    def test_candidates_do_not_spend_the_extra_call(self):
        client = Client({'state': 'found', 'text': '[]'})
        read(NODE | {'ownership': 'unknown'}, client)
        self.assertFalse([u for u in client.urls if u.endswith('/social_accounts')])

    def test_failed_social_request_does_not_break_profile_read(self):
        for social in (
            {'state': 'blocked', 'detail': 'HTTP 403'},
            {'state': 'found', 'text': 'not json'},
            {'state': 'found', 'text': json.dumps({'message': 'rate limit'})},
        ):
            out = read(NODE, Client(social))
            self.assertEqual(out['state'], 'found')
            self.assertFalse([e for e in out['evidence'] if e['location'] == 'github.social_accounts'])


if __name__ == '__main__':
    unittest.main()
