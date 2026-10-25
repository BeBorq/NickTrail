import tempfile, unittest, json
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.health import validate
from nicktrail.serviceaudit import report


class HealthRevision20Tests(unittest.TestCase):
    def test_changed_detector_cannot_reuse_healthy_claim_or_bypass_cooldown(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            s = Store(Path(tmp) / 'test.db')

            class C:
                count = 0

            def lookup(platform, term, client):
                client.count += 1
                return (
                    {
                        'state': 'found',
                        'matches': [
                            {'url': 'https://rubygems.org/profiles/fictional', 'data': {'alias': 'fictional'}}
                        ],
                    }
                    if term == 'fictional'
                    else {'state': 'not_found'}
                )

            try:
                with (
                    patch('nicktrail.network.Client', return_value=C()),
                    patch('nicktrail.providers.lookup', side_effect=lookup),
                    patch('nicktrail.healthrevision.fingerprint', return_value='first'),
                ):
                    validate(s, 'provider:RubyGems', 'fictional', 'missing')
                with (
                    patch('nicktrail.healthrevision.fingerprint', return_value='changed'),
                    patch('nicktrail.providers.lookup') as request,
                ):
                    result = validate(s, 'provider:RubyGems', 'fictional', 'missing')
                    self.assertTrue(result['cached'])
                    self.assertFalse(result['definition_matches'])
                    request.assert_not_called()
                    row = next(
                        r for r in report(s, limit=2000)['rows'] if r['health_key'] == 'provider:RubyGems'
                    )
                    self.assertEqual(row['health_state'], 'PARTIAL')
                    self.assertEqual(row['validated_capabilities'], [])
                    self.assertEqual(row['validation_definition_state'], 'CHANGED')
            finally:
                s.db.close()
