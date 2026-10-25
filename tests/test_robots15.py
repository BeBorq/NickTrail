import unittest
from unittest.mock import patch, MagicMock
from nicktrail.network import Client


class RobotsTests(unittest.TestCase):
    def test_denied_policy_blocks_profile_before_connection(self):
        c = Client()
        with (
            patch.object(
                c, 'get', return_value={'state': 'found', 'text': 'User-agent: *\nDisallow: /private'}
            ),
            patch('nicktrail.network.PinnedTLS') as tls,
        ):
            self.assertEqual(c.profile_get('https://profiles.example/private/user')['state'], 'blocked')
            tls.assert_not_called()

    def test_unavailable_robots_fails_closed_and_404_permits(self):
        c = Client()
        with patch.object(c, 'get', return_value={'state': 'error'}):
            self.assertIn('ROBOTS_RESTRICTED', c.profile_policy('https://profiles.example/user'))
        with patch.object(c, 'get', return_value={'state': 'not_found'}):
            self.assertIsNone(c.profile_policy('https://profiles.example/user'))

    def test_slow_rate_remains_manual(self):
        c = Client(delay=1)
        with patch.object(
            c, 'get', return_value={'state': 'found', 'text': 'User-agent: *\nCrawl-delay: 10'}
        ):
            self.assertIn('wolniejsze', c.profile_policy('https://profiles.example/user'))

    def test_redirect_target_policy_checked_before_target_request(self):
        c = Client(delay=0)
        conn = MagicMock()
        response = conn.getresponse.return_value
        response.status = 302
        response.getheader.return_value = 'https://other.example/private'
        with (
            patch.object(c, 'profile_policy', side_effect=[None, 'ROBOTS_RESTRICTED']),
            patch('nicktrail.network.public_addresses', return_value=['93.184.216.34']),
            patch('nicktrail.network.PinnedTLS', return_value=conn) as tls,
        ):
            self.assertEqual(c.profile_get('https://profiles.example/user')['state'], 'blocked')
            self.assertEqual(tls.call_count, 1)
