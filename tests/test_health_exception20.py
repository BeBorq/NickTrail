import tempfile, unittest, http.client
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.health import validate


class HealthException20Tests(unittest.TestCase):
    def test_transport_exception_is_recorded_not_a_maintenance_crash(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            s = Store(Path(tmp) / 'test.db')

            class C:
                count = 0

            try:
                with patch(
                    'nicktrail.providers.lookup', side_effect=http.client.RemoteDisconnected()
                ) as lookup:
                    r = validate(s, 'provider:RubyGems', 'fictional', 'missing', C())
                self.assertEqual(lookup.call_count, 1)
                self.assertEqual(r['positive_state'], 'error')
                self.assertEqual(r['negative_state'], 'not_tested')
                self.assertEqual(len(s.rows('SELECT id FROM service_health_runs')), 1)
            finally:
                s.db.close()
