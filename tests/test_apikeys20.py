import json
import os
import tempfile
import unittest
from unittest import mock

from nicktrail import apikeys


class ApiKeyTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        names = [env for env in apikeys.FIELDS]
        self.env = mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': self.dir.name, 'APPDATA': self.dir.name}, clear=False)
        self.env.start()
        for name in names:
            os.environ.pop(name, None)
        apikeys._loaded.clear()

    def tearDown(self):
        self.env.stop(); apikeys._loaded.clear(); self.dir.cleanup()

    def test_save_applies_key_and_never_returns_it(self):
        secret = 'BSA-fictional-0123456789abcd'
        out = apikeys.save({'NICKTRAIL_BRAVE_KEY': secret})
        self.assertEqual(os.environ['NICKTRAIL_BRAVE_KEY'], secret)
        self.assertNotIn(secret, json.dumps(out))
        brave = next(s for s in out['services'] if s['id'] == 'brave')
        self.assertEqual(brave['fields'][0]['preview'], '••••abcd')
        self.assertTrue(brave['ready'])
        self.assertTrue(all(link['url'].startswith('https://') or not link['url'] for s in out['services'] for link in s['links']))

    def test_file_is_outside_the_project_and_reloads(self):
        apikeys.save({'NICKTRAIL_STEAM_KEY': 'STEAMFICTIONAL1234'})
        self.assertTrue(str(apikeys.path()).startswith(self.dir.name))
        os.environ.pop('NICKTRAIL_STEAM_KEY'); apikeys._loaded.clear()
        apikeys.load()
        self.assertEqual(os.environ['NICKTRAIL_STEAM_KEY'], 'STEAMFICTIONAL1234')

    def test_environment_set_outside_wins_and_clearing_keeps_it(self):
        os.environ['NICKTRAIL_HIBP_KEY'] = 'from-shell-123456789'
        apikeys._write({'NICKTRAIL_HIBP_KEY': 'from-panel-987654321'})
        apikeys.load()
        self.assertEqual(os.environ['NICKTRAIL_HIBP_KEY'], 'from-shell-123456789')
        apikeys.save({'NICKTRAIL_HIBP_KEY': ''})
        self.assertEqual(os.environ['NICKTRAIL_HIBP_KEY'], 'from-shell-123456789')
        self.assertNotIn('NICKTRAIL_HIBP_KEY', apikeys._read())

    def test_validation(self):
        for env, value in [('NICKTRAIL_BRAVE_KEY', 'two words'), ('NICKTRAIL_BRAVE_KEY', 'x\ny'),
                           ('NICKTRAIL_SEARXNG_URL', 'http://example.org'), ('NICKTRAIL_MASTODON_INSTANCE', 'ftp://m.example'),
                           ('NICKTRAIL_UNKNOWN', 'x')]:
            with self.assertRaises(ValueError, msg=(env, value)):
                apikeys.save({env: value})
        # rc16: the network client only reaches public HTTPS hosts, so local addresses are refused up front.
        for local in ('http://127.0.0.1:8888/', 'https://127.0.0.1', 'https://localhost', 'https://10.0.0.5', 'https://[::1]'):
            with self.assertRaises(ValueError, msg=local):
                apikeys.validate('NICKTRAIL_SEARXNG_URL', local)
        self.assertEqual(apikeys.validate('NICKTRAIL_SEARXNG_URL', 'https://searx.example.org/'), 'https://searx.example.org')


if __name__ == '__main__':
    unittest.main()
