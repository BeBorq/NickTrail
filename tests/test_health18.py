import tempfile, unittest, json
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.health import validate, latest
from nicktrail.capabilities import matrix


class Health18Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / 'h.db')
        self.addCleanup(self.s.db.close)

    def test_paired_controls_cached_and_mock_never_claimed_live(self):
        class Client:
            count = 0

        c = Client()

        def lookup(platform, term, client):
            client.count += 1
            return (
                {
                    'state': 'found',
                    'matches': [
                        {'url': 'https://rubygems.org/profiles/positive', 'data': {'alias': 'positive'}}
                    ],
                }
                if term == 'positive'
                else {'state': 'not_found', 'matches': []}
            )

        with patch('nicktrail.providers.lookup', side_effect=lookup) as call:
            result = validate(self.s, 'provider:RubyGems', 'positive', 'negative', c)
            self.assertTrue(result['positive_passed'])
            self.assertTrue(result['negative_passed'])
            self.assertEqual(result['confidence'], 'control_response_tested')
            again = validate(self.s, 'provider:RubyGems', 'positive', 'negative', c)
            self.assertTrue(again['cached'])
            self.assertEqual(call.call_count, 2)
        row = next(r for r in matrix(self.s)['rows'] if r['group'] == 'provider' and r['id'] == 'RubyGems')
        self.assertEqual(row['health']['status'], 'EXACT_ONLY')

    def test_negative_false_positive_marks_detector_broken(self):
        class Client:
            count = 0

        with patch(
            'nicktrail.providers.lookup',
            return_value={'state': 'found', 'matches': [{'data': {'alias': 'positive'}}]},
        ):
            r = validate(self.s, 'provider:RubyGems', 'positive', 'negative', Client())
        self.assertEqual(r['status'], 'BROKEN')
        self.assertFalse(r['negative_passed'])

    def test_rate_limit_is_not_absence(self):
        class Client:
            count = 0

        with patch(
            'nicktrail.providers.lookup',
            return_value={'state': 'blocked', 'detail': 'HTTP 429', 'matches': []},
        ):
            r = validate(self.s, 'provider:RubyGems', 'positive', 'negative', Client())
        self.assertEqual(r['status'], 'RATE_LIMITED')
        self.assertIsNone(r['last_success'])

    def test_reject_unknown_services_and_identical_controls_before_network(self):
        with self.assertRaises(ValueError):
            validate(self.s, 'provider:Missing', 'one', 'two')
        with self.assertRaises(ValueError):
            validate(self.s, 'provider:RubyGems', 'same', 'same')
