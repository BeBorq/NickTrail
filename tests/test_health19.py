import json, tempfile, unittest, time
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.health import validate, latest, schema
from nicktrail.serviceaudit import report


class Health19Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / 'fixture.db')
        self.addCleanup(self.s.db.close)

    def fake(self, platform, term, client):
        client.count += 1
        client.events += [
            {'kind': 'request_sent', 'host': 'fixture.example'},
            {'kind': 'response', 'host': 'fixture.example', 'status': 200 if term == 'positive' else 404},
        ]
        return (
            {
                'state': 'found',
                'matches': [{'url': 'https://rubygems.org/profiles/positive', 'data': {'alias': 'positive'}}],
            }
            if term == 'positive'
            else {'state': 'not_found', 'matches': []}
        )

    def client(self):
        class Client:
            count = 0
            events_truncated = 0

        c = Client()
        c.events = []
        return c

    def test_fixture_never_counts_as_healthy_and_inventory_filters_conserve_counts(self):
        with patch('nicktrail.providers.lookup', side_effect=self.fake):
            validate(self.s, 'provider:RubyGems', 'positive', 'negative', self.client())
        r = report(self.s, limit=2000)
        self.assertEqual(sum(r['health_counts'].values()), r['total_definitions'])
        self.assertEqual(r['health_counts']['HEALTHY'], 0)
        self.assertEqual(r['definition_sources']['Sherlock'], 383)
        self.assertEqual(r['definition_sources']['Maigret'], 500)
        filtered = report(self.s, {'source': 'Maigret', 'tier': 'A'}, limit=2000)
        self.assertTrue(
            all(row['definition_source'] == 'Maigret' and row['tier'] == 'A' for row in filtered['rows'])
        )
        self.assertEqual(r['network_calls'], 0)

    def test_fixture_cache_does_not_mask_first_live_check_and_history_is_preserved(self):
        with patch('nicktrail.providers.lookup', side_effect=self.fake):
            validate(self.s, 'provider:RubyGems', 'positive', 'negative', self.client())
        with (
            patch('nicktrail.network.Client', return_value=self.client()),
            patch('nicktrail.providers.lookup', side_effect=self.fake) as lookup,
        ):
            r = validate(self.s, 'provider:RubyGems', 'positive', 'negative')
            self.assertEqual(lookup.call_count, 2)
            self.assertFalse(r['cached'])
        self.assertEqual(report(self.s, {'state': 'HEALTHY'})['matched'], 1)
        self.assertEqual(len(self.s.rows('select * from service_health_runs')), 2)
        telemetry = json.loads(r['telemetry'])
        self.assertEqual(telemetry['responses_received'], 2)
        self.assertEqual(telemetry['http_status_counts'], {'200': 1, '404': 1})
        self.assertEqual(telemetry['case_coverage'], 'not_exercised')

    def test_rate_limit_stops_negative_control_and_persists_long_cooldown(self):
        c = self.client()

        def limited(*args):
            c.count += 1
            c.events.append({'kind': 'rate_limit', 'retry_after_seconds': 172800})
            return {'state': 'blocked', 'detail': 'HTTP 429'}

        with patch('nicktrail.providers.lookup', side_effect=limited) as call:
            r = validate(self.s, 'provider:RubyGems', 'positive', 'negative', c)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(r['negative_state'], 'not_tested')
            self.assertGreater(r['retry_at'], time.time() + 86400)
        self.assertEqual(r['status'], 'RATE_LIMITED')

    def test_schema_migrates_previous_health_table(self):
        self.s.execute(
            'CREATE TABLE service_health(service TEXT PRIMARY KEY,checked_at REAL,last_success REAL,status TEXT,positive_state TEXT,negative_state TEXT,reason TEXT,confidence TEXT,requests INTEGER,control_hash TEXT,positive_passed INTEGER,negative_passed INTEGER)'
        )
        schema(self.s)
        self.assertIn('telemetry', {r['name'] for r in self.s.rows('PRAGMA table_info(service_health)')})

    def test_keybase_exact_capability_and_invalid_control_fail_before_network(self):
        from nicktrail.providers import REGISTRY
        from nicktrail.identityapis import lookup_platform

        self.assertTrue(REGISTRY['Keybase'].supports_exact)
        for alias in ('a', 'a' * 17, '_wrong', 'wrong__name'):
            with patch('nicktrail.providers.lookup') as lookup:
                with self.assertRaises(ValueError):
                    validate(self.s, 'provider:Keybase', 'fictional', alias)
                lookup.assert_not_called()
            c = self.client()
            c.get = lambda *args: self.fail('Invalid username reached network')
            self.assertEqual(lookup_platform('Keybase', alias, c)['state'], 'unsupported')
