import unittest
from unittest.mock import patch
from nicktrail.network import Client


class CooldownTests(unittest.TestCase):
    def test_api_backoff_survives_new_client_without_network(self):
        with (
            patch.dict('nicktrail.network.PROCESS_COOLDOWNS', {}, clear=True),
            patch('nicktrail.network.public_addresses') as dns,
        ):
            a = Client()
            a.defer_host('api.example.org', 60)
            b = Client()
            self.assertEqual(b.get('https://api.example.org/other')['state'], 'blocked')
            self.assertEqual(b.count, 0)
            dns.assert_not_called()

    def test_query_api_key_cannot_follow_cross_host_redirect(self):
        class Response:
            status = 302

            def getheader(self, key, default=''):
                return 'https://other.example/key' if key == 'Location' else default

        class Conn:
            def __init__(self, *a, **kw):
                pass

            def request(self, *a, **kw):
                pass

            def getresponse(self):
                return Response()

            def close(self):
                pass

        with (
            patch.dict('nicktrail.network.PROCESS_COOLDOWNS', {}, clear=True),
            patch('nicktrail.network.public_addresses', return_value=['93.184.216.34']),
            patch('nicktrail.network.PinnedTLS', Conn),
        ):
            r = Client(delay=0).get('https://index.example/search?api_key=fictional')
            self.assertEqual(r['state'], 'blocked')
            self.assertIn('tokenem', r['detail'])

    def test_429_without_retry_header_does_not_retry_or_repeat_in_new_client(self):
        class Response:
            status = 429

            def getheader(self, key, default=''):
                return default

        class Conn:
            def __init__(self, *a, **kw):
                pass

            def request(self, *a, **kw):
                pass

            def getresponse(self):
                return Response()

            def close(self):
                pass

        with (
            patch.dict('nicktrail.network.PROCESS_COOLDOWNS', {}, clear=True),
            patch('nicktrail.network.public_addresses', return_value=['93.184.216.34']) as dns,
            patch('nicktrail.network.PinnedTLS', Conn),
        ):
            a = Client(delay=0)
            result = a.get('https://api.example.org/check')
            self.assertEqual(a.count, 1)
            self.assertIn('429', result['detail'])
            b = Client(delay=0)
            self.assertEqual(b.get('https://api.example.org/next')['state'], 'blocked')
            self.assertEqual(b.count, 0)
            self.assertEqual(dns.call_count, 1)
