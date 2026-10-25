import json, unittest
from unittest.mock import patch
from nicktrail.apierrors import public_error, codeforces_error
from nicktrail.network import Client


class ApiErrors20Tests(unittest.TestCase):
    def classify(
        self,
        body,
        url='https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=fiction.bsky.social',
        status=400,
        ctype='application/json',
    ):
        return public_error(url, status, ctype, json.dumps(body).encode())

    def test_resolver_missing_is_narrow_and_not_global_absence(self):
        body = {'error': 'InvalidRequest', 'message': 'Profile not found', 'secret': 'never retain'}
        r = self.classify(body)
        self.assertEqual(r['state'], 'not_found')
        self.assertIn('not proof', r['detail'])
        self.assertNotIn('secret', json.dumps(r))
        for url in (
            'https://other.example/xrpc/app.bsky.actor.getProfile',
            'http://public.api.bsky.app/xrpc/app.bsky.actor.getProfile',
            'https://public.api.bsky.app/xrpc/other',
            'https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=invalid',
            'https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=a.example&actor=b.example',
        ):
            self.assertIsNone(self.classify(body, url))
        for body in (
            {'error': 'InvalidRequest', 'message': 'Invalid actor'},
            {'error': 'AccountTakedown', 'message': 'Suspended'},
            {'error': 'AccountDeactivated'},
        ):
            self.assertNotEqual((self.classify(body) or {}).get('state'), 'not_found')

    def test_codeforces_requires_exact_single_handle(self):
        b = {'status': 'FAILED', 'comment': 'handles: User with handle fictional not found'}
        self.assertEqual(codeforces_error(b, ['fictional'])['state'], 'not_found')
        for handles in ([], ['other'], ['fictional', 'other'], ['fictional;other']):
            self.assertIsNone(codeforces_error(b, handles))
        for comment in ('Call limit exceeded', 'Invalid parameter handles', 'Service unavailable'):
            self.assertNotEqual(
                (codeforces_error({'status': 'FAILED', 'comment': comment}, ['fictional']) or {}).get(
                    'state'
                ),
                'not_found',
            )

    def test_malformed_oversized_and_auth_errors_are_not_absence(self):
        url = 'https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile'
        for payload in (b'{', b'[]', b' ' * 16385):
            self.assertIsNone(public_error(url, 400, 'application/json', payload))
        for status in (200, 401, 403, 429, 500):
            self.assertIsNone(
                self.classify({'error': 'InvalidRequest', 'message': 'Profile not found'}, status=status)
            )

    def test_transport_reads_chunked_json_counts_bytes_and_caches_only_sanitized_result(self):
        payload = b'{"error":"InvalidRequest","message":"Profile not found","secret":"private"}'

        class Response:
            status = 400

            def __init__(self):
                self.offset = 0

            def getheader(self, k, default=''):
                return 'application/json' if k == 'Content-Type' else default

            def read1(self, n):
                chunk = payload[self.offset : self.offset + min(n, 7)]
                self.offset += len(chunk)
                return chunk

        class Conn:
            sent = 0

            def __init__(self, *a, **kw):
                pass

            def request(self, *a, **kw):
                Conn.sent += 1

            def getresponse(self):
                return Response()

            def close(self):
                pass

        with (
            patch.dict('nicktrail.network.PROCESS_COOLDOWNS', {}, clear=True),
            patch('nicktrail.network.public_addresses', return_value=['93.184.216.34']),
            patch('nicktrail.network.PinnedTLS', Conn),
        ):
            c = Client(delay=0)
            url = 'https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=fiction.bsky.social'
            self.assertEqual(c.get(url)['state'], 'not_found')
            self.assertEqual(c.get(url)['state'], 'not_found')
            self.assertEqual(Conn.sent, 1)
            self.assertEqual(sum(e.get('bytes', 0) for e in c.events), len(payload))
            self.assertNotIn('private', str(c.cache))
