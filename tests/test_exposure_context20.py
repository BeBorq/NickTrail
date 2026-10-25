import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.exposure import schema, check
from nicktrail.aipacket import build
from nicktrail.exposurecontext import context


class ExposureContext20Tests(unittest.TestCase):
    def test_exposure_is_opt_in_export_context_never_identity_support(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            s = Store(Path(tmp) / 'test.db')
            p = s.project('Fictional')
            try:
                a = s.apply_profile(p, 'https://github.com/fictional-a', {'alias': 'fictional-a'})
                b = s.apply_profile(p, 'https://dev.to/fictional-b', {'alias': 'fictional-b'})
                schema(s)
                incident = [
                    {
                        'Name': 'Fictional',
                        'Domain': 'chess.com',
                        'DataClasses': ['Usernames'],
                        'IsVerified': True,
                    }
                ]
                for _ in range(2):
                    s.execute(
                        'INSERT INTO exposure_checks(project,account,checked,state,detail,incidents) VALUES(?,?,?,?,?,?)',
                        (
                            p,
                            'private@private-mail.example',
                            '2026-01-01',
                            'exposed',
                            '',
                            json.dumps(incident),
                        ),
                    )
                self.assertEqual(len(context(s, p)), 1)
                self.assertFalse(build(s, p, [a, b])['packet']['exposure_context'])
            finally:
                s.db.close()

    def test_shared_cache_survives_only_while_another_consented_project_references_it(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            s = Store(Path(tmp) / 'test.db')
            a = s.project('A')
            b = s.project('B')

            class C:
                def get(self, *args, **kwargs):
                    return {'state': 'not_found'}

            try:
                with patch.dict('os.environ', {'NICKTRAIL_HIBP_KEY': 'fixture'}):
                    check(s, a, 'self@example.org', True, C())
                    check(s, b, 'self@example.org', True, C())
                s.execute('DELETE FROM projects WHERE id=?', (a,))
                self.assertEqual(
                    len(s.rows("SELECT * FROM exposure_provider_cache WHERE scope='account'")), 1
                )
                s.execute('DELETE FROM projects WHERE id=?', (b,))
                self.assertFalse(s.rows("SELECT * FROM exposure_provider_cache WHERE scope='account'"))
            finally:
                s.db.close()
