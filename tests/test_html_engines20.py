import json, tempfile, unittest, os
from pathlib import Path
from unittest.mock import patch
from nicktrail.engineconfig import instances, HTML_ENGINES
from nicktrail.engines import lookup_platform, read
from nicktrail.publicengines import lookup


class HtmlEngine20Tests(unittest.TestCase):
    def test_direct_profile_query_extracts_alias_from_configured_parameter(self):
        definition = {
            'id': 'ExplicitForum',
            'engine': 'phpbb',
            'host': 'forum.example',
            'profile_url': 'https://forum.example/memberlist.php?mode=viewprofile&un={nick}',
        }
        url = 'https://forum.example/memberlist.php?mode=viewprofile&un=fictional'
        from nicktrail.identity import identify

        with (
            patch('nicktrail.identity.engine_instances', return_value={'ExplicitForum': definition}),
            patch.dict('nicktrail.identity.SERVICES', {'forum.example': 'ExplicitForum'}),
        ):
            self.assertEqual(identify(url)['kind'], 'profile')
        with (
            patch('nicktrail.engines.instances', return_value={'ExplicitForum': definition}),
            patch(
                'nicktrail.engines.lookup_platform', return_value={'state': 'not_found', 'matches': []}
            ) as lookup,
        ):
            read({'url': url, 'platform': 'ExplicitForum', 'data': '{}'}, None)
            self.assertEqual(lookup.call_args.args[1], 'fictional')
            r = read({'url': 'https://forum.example/admin', 'platform': 'ExplicitForum', 'data': '{}'}, None)
            self.assertEqual(r['state'], 'unsupported')
            self.assertEqual(lookup.call_count, 1)

    def test_explicit_profile_metadata_on_two_instances_for_each_html_family(self):
        class C:
            def get(self, url):
                return {
                    'state': 'found',
                    'url': url,
                    'text': '<meta property="og:type" content="profile"><meta property="profile:username" content="fictional"><link rel="canonical" href="'
                    + url
                    + '"><title>fictional</title>',
                }

            profile_get = get

        for family in sorted(HTML_ENGINES):
            for host in ('forum-a.example', 'forum-b.example'):
                r = lookup_platform(
                    'ExplicitForum',
                    'fictional',
                    C(),
                    instance={
                        'engine': family,
                        'host': host,
                        'profile_url': 'https://' + host + '/members/{nick}',
                    },
                )
                self.assertEqual(r['state'], 'found')
                self.assertEqual(r['matches'][0]['data']['id_scope'], host)
                self.assertNotIn('stable_id', r['matches'][0]['data'])
                self.assertEqual(
                    r['matches'][0]['data']['engine_verification'],
                    'explicit_public_profile_metadata_not_native_api',
                )

    def test_no_configured_route_means_no_network_and_not_absent(self):
        class C:
            def get(self, *a, **kw):
                raise AssertionError('No guessed network endpoint')

        with patch('nicktrail.engineconfig.instances', return_value={}):
            r = lookup('xenforo', 'forum.example', 'fictional', C())
            self.assertEqual(r['state'], 'unsupported')
            self.assertIn('MANUAL_ONLY', r['detail'])

    def test_configuration_refuses_foreign_or_secret_routes(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            path = Path(tmp) / 'instances.json'
            for route in (
                'https://other.example/u/{nick}',
                'https://forum.example/u/{nick}?api_key=secret',
                'http://forum.example/u/{nick}',
            ):
                path.write_text(
                    json.dumps(
                        [
                            {
                                'id': 'ExplicitForum',
                                'engine': 'xenforo',
                                'host': 'forum.example',
                                'live_status': 'UNTESTED',
                                'limitations': 'Fictional explicit route',
                                'profile_url': route,
                            }
                        ]
                    ),
                    encoding='utf-8',
                )
                instances.cache_clear()
                try:
                    with patch.dict(os.environ, {'NICKTRAIL_ENGINE_INSTANCES': str(path)}):
                        with self.assertRaises(ValueError):
                            instances()
                finally:
                    instances.cache_clear()
