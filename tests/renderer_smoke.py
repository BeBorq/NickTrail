"""Opt-in actual headless renderer test. Every HTTP response is a local fixture."""

import importlib.util
import os
import time
import unittest
from nicktrail.rendered import read
from nicktrail.identity import identify


class RendererSmoke(unittest.TestCase):
    @unittest.skipUnless(
        importlib.util.find_spec('playwright') and os.environ.get('NICKTRAIL_BROWSER_EXECUTABLE'),
        'Optional Playwright and configured browser required',
    )
    def test_javascript_created_link(self):
        class Fixture:
            deadline = time.monotonic() + 25
            maximum = 10
            count = 0

            def get(self, url):
                if url != 'https://example.org/render-fixture':
                    raise ValueError('Unexpected resource; fixture never performs network calls')
                self.count += 1
                return {
                    'state': 'found',
                    'url': url,
                    'content_type': 'text/html',
                    'text': '''<!doctype html><html><body><main><p>This is an entirely fictional public profile page used only to test JavaScript rendering.</p><div id="bio"></div><script>setTimeout(()=>{let a=document.createElement('a');a.href='https://github.com/fictional-rendered';a.textContent='My public profile';document.getElementById('bio').append(a)},50)</script></main></body></html>''',
                }

        result = read(identify('https://example.org/render-fixture'), Fixture())
        self.assertEqual(result['state'], 'found', result)
        self.assertTrue(
            any(
                e.get('url') == 'https://github.com/fictional-rendered'
                and e['method'] == 'rendered_public_page'
                for e in result['evidence']
            )
        )


if __name__ == '__main__':
    unittest.main()
