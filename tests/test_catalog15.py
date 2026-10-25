import json, unittest
from unittest.mock import patch
from nicktrail.catalog_import import convert
from nicktrail.extended import lookup, services
from nicktrail.freeprofiles import probe
from nicktrail.publicprofile import ProfileHTML


class CatalogTests(unittest.TestCase):
    def test_pinned_license_and_safe_routes(self):
        rows = services()
        self.assertEqual(len([r for r in rows if r['id'].startswith('Sherlock.')]), 383)
        self.assertEqual(len([r for r in rows if r['id'].startswith('Maigret.')]), 500)
        self.assertTrue(all(s['validation']['live_status'] == 'UNTESTED' for s in rows))
        self.assertTrue(all(s['provenance']['license'] == 'MIT' for s in rows))

    def test_import_does_not_execute_upstream_regex_headers_or_posts(self):
        payload = {
            'Good': {'url': 'https://public.example/{}', 'regexCheck': '(a+)+$'},
            'Post': {'url': 'https://public.example/{}', 'request_method': 'POST'},
            'Local': {'url': 'http://127.0.0.1/{}'},
        }
        result = convert(payload, 'a' * 40, 'MIT License\nCopyright (c) 2019 Sherlock Project')
        self.assertEqual(len(result['services']), 1)
        self.assertFalse(result['services'][0]['provenance']['upstream_regex_used'])
        self.assertEqual(len(result['rejected']), 2)

    def test_http200_definition_does_not_verify_profile(self):
        class C:
            def get(self, url):
                return (
                    {'state': 'not_found'}
                    if url.endswith('robots.txt')
                    else {'state': 'found', 'text': '<title>Welcome</title>', 'url': url}
                )

        row = services()[0]
        result = lookup(row['id'] + ':fictional', C())
        self.assertEqual(result['state'], 'unverified')
        self.assertTrue(result['matches'][0]['data']['definition_only'])
        self.assertEqual(result['matches'][0]['evidence'], [])

    def test_robots_denial_never_requests_profile(self):
        calls = []

        class C:
            def get(self, url):
                calls.append(url)
                return {'state': 'found', 'text': 'User-agent: *\nDisallow: /'}

        result = lookup(services()[0]['id'] + ':fictional', C())
        self.assertEqual(result['state'], 'blocked')
        self.assertEqual(len(calls), 1)

    def test_person_relative_url_and_list_are_associated_but_other_owner_is_not(self):
        p = ProfileHTML()
        p.feed(
            '<script type="application/ld+json">'
            + json.dumps(
                {'@type': 'Person', 'url': ['/fictional'], 'sameAs': ['https://github.com/fictional']}
            )
            + '</script>'
        )
        self.assertEqual(p.same_as('https://personal.example/fictional'), ['https://github.com/fictional'])
        self.assertEqual(p.same_as('https://personal.example/other'), [])
