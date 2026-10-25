import json
import unittest
from nicktrail.adapters import extract, read
from nicktrail.publicprofile import ProfileHTML
from nicktrail.identity import identify


class Fixture:
    def __init__(self, text):
        self.text = text

    def get(self, url):
        return {'state': 'found', 'text': self.text, 'url': url}


class ProfileLinkTests(unittest.TestCase):
    def test_description_html_markdown_and_bare_domains(self):
        items = extract(
            '<p>Strona: <a href="https://example.org/me?a=1&amp;b=2">Moja strona</a></p><script>https://evil.example/track</script>',
            'https://hackerone.com/fictional',
        )
        self.assertEqual([i['url'] for i in items], ['https://example.org/me?a=1&b=2'])
        urls = {
            i['url']
            for i in extract(
                'Profil: hackerone.com/fictional, [GitHub](https://github.com/fictional). kontakt me@example.org/test',
                'https://example.net',
            )
            if 'url' in i
        }
        self.assertIn('https://hackerone.com/fictional', urls)
        self.assertIn('https://github.com/fictional', urls)
        self.assertNotIn('https://example.org/test', urls)

    def test_no_duplicate_links_or_script_navigation_links(self):
        page = ProfileHTML()
        page.feed(
            '<nav><a href="https://nav.example/link">nav</a></nav><main><a href="https://example.org/me">me</a><p>https://example.org/me</p></main><footer><a href="https://footer.example/link">f</a></footer>'
        )
        items = extract('\n'.join(page.parts), 'https://hackerone.com/fictional', links=page.links)
        self.assertEqual([i['url'] for i in items], ['https://example.org/me'])

    def test_hackerone_json_uses_bio_and_website_not_photo(self):
        body = {
            'id': 123,
            'username': 'fictional',
            'bio': 'GitHub: github.com/fictional',
            'website': 'https://x.com/fictional',
            'name': 'Test',
            'profile_picture_urls': {'small': 'https://photos.example/photo'},
        }
        result = read(identify('https://hackerone.com/fictional'), Fixture(json.dumps(body)))
        self.assertEqual(result['state'], 'found')
        self.assertEqual(
            {e['url'] for e in result['evidence']},
            {'https://github.com/fictional', 'https://x.com/fictional'},
        )
        self.assertEqual(result['data']['stable_id'], '123')
        body['username'] = 'different'
        with self.assertRaises(ValueError):
            read(identify('https://hackerone.com/fictional'), Fixture(json.dumps(body)))

    def test_jsonld_sameas_only_for_requested_person(self):
        data = {
            '@graph': [
                {
                    '@type': 'Person',
                    'url': 'https://example.org/me',
                    'sameAs': ['https://github.com/fictional'],
                },
                {'@type': 'Organization', 'url': 'https://example.org/me', 'sameAs': ['https://x.com/site']},
                {'@type': 'Person', 'url': 'https://example.org/other', 'sameAs': ['https://x.com/other']},
            ]
        }
        page = ProfileHTML()
        page.feed(
            '<script type="application/ld+json">'
            + json.dumps(data)
            + '</script><script>"https://x.com/tracker"</script>'
        )
        self.assertEqual(page.same_as('https://example.org/me'), ['https://github.com/fictional'])

    def test_javascript_shell_never_looks_like_no_links_found(self):
        result = read(
            identify('https://hackerone.com/fictional'),
            Fixture(
                '<html><body>It looks like your JavaScript is disabled. Enable JavaScript to use HackerOne.</body></html>'
            ),
        )
        self.assertEqual(result['state'], 'blocked')

    def test_generic_public_service_reads_description_and_sameas(self):
        html = '<main><p>This is the public biography of a fictional account with enough visible text to inspect.</p><a href="https://github.com/fictional">GitHub</a></main>'
        result = read(identify('https://linktr.ee/fictional'), Fixture(html))
        self.assertEqual(result['state'], 'found')
        self.assertEqual(result['evidence'][0]['url'], 'https://github.com/fictional')

    def test_balanced_parentheses_and_unknown_json(self):
        result = extract('Link: https://example.org/article_(test).', 'https://hackerone.com/fictional')
        self.assertEqual(result[0]['url'], 'https://example.org/article_(test)')
        result = read(
            identify('https://linktr.ee/fictional'), Fixture('{"tracking":"https://tracking.example/id"}')
        )
        self.assertEqual(result['state'], 'unsupported')
