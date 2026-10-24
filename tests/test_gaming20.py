import json
import os
import unittest
from unittest import mock

from nicktrail import gaming
from nicktrail.identity import identify
from nicktrail.providers import REGISTRY
from nicktrail.routes import profile_url


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.headers = None
        self.url = None
    def get(self, url, headers=None):
        self.url = url; self.headers = headers
        return self.response


class GamingTests(unittest.TestCase):
    def test_registered_keyed_and_not_in_defaults(self):
        for p in ('Twitch', 'Xbox'):
            self.assertIn(p, REGISTRY)
            self.assertTrue(REGISTRY[p].required_env)
        from nicktrail.scanmodes import policy
        self.assertNotIn('Twitch', policy('STANDARD')['platforms'])
        self.assertNotIn('Xbox', policy('DEEP')['platforms'])

    def test_identify_and_profile_urls(self):
        self.assertEqual(identify('https://www.twitch.tv/quillonior')['kind'], 'profile')
        self.assertEqual(identify('https://www.twitch.tv/directory')['kind'], 'page')
        self.assertEqual(identify('https://account.xbox.com/en-us/profile?gamertag=quillon111111')['kind'], 'profile')
        self.assertEqual(profile_url('Twitch', 'quillonior'), 'https://www.twitch.tv/quillonior')
        self.assertTrue(profile_url('Xbox', 'quillon111111').startswith('https://account.xbox.com/'))

    @mock.patch.dict(os.environ, {'NICKTRAIL_TWITCH_CLIENT_ID': 'cid', 'NICKTRAIL_TWITCH_TOKEN': 'tok'})
    def test_twitch_match_extracts_bio_and_sends_auth_headers(self):
        body = {'data': [{'id': '12345', 'login': 'quillonior', 'display_name': 'Quillon',
                          'description': 'Code at https://github.com/quillonior', 'profile_image_url': 'https://x/i.png'}]}
        client = FakeClient({'state': 'found', 'text': json.dumps(body)})
        out = gaming.twitch_lookup('quillonior', client)
        self.assertEqual(out['state'], 'found')
        self.assertEqual(out['data']['stable_id'], 'twitch:12345')
        self.assertEqual(client.headers['Client-Id'], 'cid')
        self.assertTrue(client.headers['Authorization'].startswith('Bearer '))
        self.assertTrue(any('github.com/quillonior' in str(e) for e in out['evidence']))

    @mock.patch.dict(os.environ, {'NICKTRAIL_TWITCH_CLIENT_ID': 'cid', 'NICKTRAIL_TWITCH_TOKEN': 'tok'})
    def test_twitch_no_account(self):
        client = FakeClient({'state': 'found', 'text': json.dumps({'data': []})})
        self.assertEqual(gaming.twitch_lookup('nobodyhere', client)['state'], 'not_found')

    @mock.patch.dict(os.environ, {'NICKTRAIL_XBOX_KEY': 'k'})
    def test_xbox_match_and_header(self):
        body = {'profileUsers': [{'id': '2814', 'settings': [{'id': 'Gamertag', 'value': 'quillon111111'},
                {'id': 'Bio', 'value': 'see https://hackerone.com/quillon'}, {'id': 'GameDisplayPicRaw', 'value': 'https://x/p.png'}]}]}
        client = FakeClient({'state': 'found', 'text': json.dumps(body)})
        out = gaming.xbox_lookup('quillon111111', client)
        self.assertEqual(out['state'], 'found')
        self.assertEqual(out['data']['stable_id'], 'xbox:2814')
        self.assertEqual(client.headers['X-Authorization'], 'k')
        self.assertIn('account.xbox.com', out['url'])

    @mock.patch.dict(os.environ, {'NICKTRAIL_XBOX_KEY': 'k'})
    def test_xbox_wrong_gamertag_is_not_a_match(self):
        body = {'profileUsers': [{'id': '1', 'settings': [{'id': 'Gamertag', 'value': 'someoneelse'}]}]}
        client = FakeClient({'state': 'found', 'text': json.dumps(body)})
        self.assertEqual(gaming.xbox_lookup('quillon111111', client)['state'], 'not_found')

    def test_unconfigured_read_is_unsupported(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('NICKTRAIL_XBOX_KEY', None)
            out = gaming.read_gaming({'platform': 'Xbox', 'url': 'https://account.xbox.com/en-us/profile?gamertag=x', 'kind': 'profile'}, FakeClient({}))
            self.assertEqual(out['state'], 'unsupported')


if __name__ == '__main__':
    unittest.main()
