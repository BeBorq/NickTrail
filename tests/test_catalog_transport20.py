import unittest
from unittest.mock import patch
from nicktrail.network import Client


class CatalogTransport20Tests(unittest.TestCase):
    def test_larger_response_is_limited_to_explicit_hibp_catalog_and_bytes_counted(self):
        payload = b' ' * (1048576 + 1)

        class Response:
            status = 200

            def __init__(self):
                self.offset = 0

            def getheader(self, k, default=''):
                return 'application/json' if k == 'Content-Type' else default

            def read1(self, n):
                chunk = payload[self.offset : self.offset + n]
                self.offset += len(chunk)
                return chunk

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
            regular = Client(delay=0)
            self.assertEqual(regular.get('https://haveibeenpwned.com/api/v3/breaches')['state'], 'error')
            c = Client(delay=0, exposure_catalog=True)
            self.assertEqual(c.get('https://haveibeenpwned.com/api/v3/breaches')['state'], 'found')
            self.assertEqual(sum(e.get('bytes', 0) for e in c.events), len(payload))
            self.assertEqual(c.get('https://other.example/api/v3/breaches')['state'], 'error')
