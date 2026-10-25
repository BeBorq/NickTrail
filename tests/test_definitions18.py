import unittest, tempfile, json, os
from pathlib import Path
from unittest.mock import patch
from nicktrail.definition_import import convert
from nicktrail.extended import services


class Definition18Tests(unittest.TestCase):
    def test_maigret_routes_controls_provenance_and_unsupported_semantics(self):
        payload = {
            'sites': {
                'Good': {
                    'url': 'https://synthetic.example/{username}/',
                    'usernameClaimed': 'fictional',
                    'usernameUnclaimed': 'unusedfictional',
                    'regexCheck': '(a+)+$',
                    'tags': ['coding'],
                },
                'Disabled': {'url': 'https://disabled.example/{username}', 'disabled': True},
                'Post': {'url': 'https://post.example/{username}', 'requestMethod': 'POST'},
                'Inherited': {'engine': 'phpBB', 'urlMain': 'https://example.org'},
                'Local': {'url': 'http://127.0.0.1/{username}'},
            }
        }
        pack = convert('Maigret', payload, 'a' * 40, 'MIT License\nCopyright Soxoj')
        self.assertEqual(len(pack['services']), 1)
        self.assertEqual(len(pack['rejected']), 4)
        row = pack['services'][0]
        self.assertFalse(row['provenance']['upstream_regex_used'])
        self.assertEqual(row['controls']['positive'], 'fictional')
        self.assertEqual(row['validation']['live_status'], 'UNTESTED')

    def test_cc_by_sa_data_license_and_authors_preserved(self):
        payload = {
            'license': ['Copyright Micah Hoffman', 'Creative Commons Attribution-ShareAlike 4.0'],
            'authors': ['Fictional Contributor'],
            'sites': [
                {
                    'name': 'Example',
                    'uri_check': 'https://synthetic.example/{account}',
                    'known': ['fictional'],
                }
            ],
        }
        pack = convert('WhatsMyName', payload, 'b' * 40)
        self.assertEqual(pack['license'], 'CC-BY-SA-4.0')
        self.assertEqual(pack['authors'], payload['authors'])
        self.assertEqual(pack['services'][0]['provenance']['license'], 'CC-BY-SA-4.0')
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            path = Path(folder) / 'pack.json'
            path.write_text(json.dumps(pack), encoding='utf-8')
            try:
                with patch.dict(os.environ, {'NICKTRAIL_DEFINITION_PACKS': str(path)}):
                    services.cache_clear()
                    self.assertTrue(any(r['id'].startswith('WhatsMyName.') for r in services()))
            finally:
                services.cache_clear()

    def test_licenses_and_revision_required_and_canonical_duplicates_removed(self):
        with self.assertRaises(ValueError):
            convert('Maigret', {'sites': {}}, 'a' * 40, 'unlicensed')
        p = {'sites': {'Same': {'url': 'https://synthetic.example/{username}/'}}}
        self.assertEqual(
            convert(
                'Maigret',
                p,
                'a' * 40,
                'MIT License\nCopyright Soxoj',
                excluded_routes=['https://synthetic.example/{nick}'],
            )['services'],
            [],
        )

    def test_bundled_packs_have_unique_routes_and_no_live_claim(self):
        rows = services()
        self.assertEqual(len(rows), 883)
        from nicktrail.identity import normalize

        urls = [normalize(r['profile_url'].format(nick='fixture')) for r in rows]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertTrue(all(r['validation']['live_status'] == 'UNTESTED' for r in rows))
