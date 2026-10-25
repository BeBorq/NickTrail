import unittest
from nicktrail.publicprofile import read


class Page:
    def __init__(self, text):
        self.text = text

    def get(self, url):
        return {'state': 'found', 'text': self.text, 'url': url, 'content_type': 'text/html'}


def node(url):
    return {'url': url, 'platform': 'Linktree', 'kind': 'profile', 'data': '{}'}


class HubPageTest(unittest.TestCase):
    def test_short_link_in_bio_page_naming_the_handle_is_read(self):
        html = '<html><head><title>fictional-hub | Links</title></head><body><h1>@fictional-hub</h1><a href="https://github.com/fictional-dev">Code</a><a href="https://dev.to/fictional-writes">Blog</a></body></html>'
        result = read(node('https://linktr.ee/fictional-hub'), Page(html))
        self.assertEqual(result['state'], 'found')
        self.assertEqual(
            {e['url'] for e in result['evidence'] if 'url' in e},
            {'https://github.com/fictional-dev', 'https://dev.to/fictional-writes'},
        )

    def test_generic_shell_with_company_footer_stays_blocked(self):
        html = '<html><head><title>Links</title></head><body><div>Loading</div><footer><a href="https://x.com/platform-company">X</a></footer></body></html>'
        self.assertEqual(read(node('https://linktr.ee/fictional-hub'), Page(html))['state'], 'blocked')

    def test_handle_without_offsite_links_or_a_challenge_stays_blocked(self):
        self.assertEqual(
            read(
                node('https://linktr.ee/fictional-hub'),
                Page('<title>@fictional-hub</title><a href="/login">Log in</a>'),
            )['state'],
            'blocked',
        )
        challenge = '<title>Just a moment...</title><p>@fictional-hub</p><p>Verify you are human</p><a href="https://github.com/x">x</a>'
        self.assertEqual(read(node('https://linktr.ee/fictional-hub'), Page(challenge))['state'], 'blocked')

    def test_handle_must_match_as_a_token(self):
        html = '<title>fictional-hubby</title><a href="https://github.com/other">GitHub</a>'
        self.assertEqual(read(node('https://linktr.ee/fictional-hub'), Page(html))['state'], 'blocked')


class BlueskyDomainHandleTest(unittest.TestCase):
    def test_custom_domain_handle_becomes_declared_site_but_provider_handles_do_not(self):
        from nicktrail.adapters import bluesky_domain_handle

        self.assertEqual(
            [e['url'] for e in bluesky_domain_handle('Person.Example')], ['https://person.example']
        )
        self.assertEqual(bluesky_domain_handle('person.example')[0]['location'], 'bluesky.domain_handle')
        for handle in (
            'someone.bsky.social',
            'handle.invalid',
            'x.blacksky.app',
            'not a domain',
            None,
            'localhost',
        ):
            self.assertEqual(bluesky_domain_handle(handle), [], handle)
