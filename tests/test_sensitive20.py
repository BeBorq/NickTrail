import json
import os
import tempfile
import unittest

from nicktrail import sensitive
from nicktrail.exporting import export
from nicktrail.providers import REGISTRY
from nicktrail.storage import Store


class FakeClient:
    """Serves one fixed response for a profile probe."""
    def __init__(self, response):
        self.response = response
    def get(self, url):
        return self.response


class SensitiveTests(unittest.TestCase):
    def test_registered_but_not_in_defaults(self):
        self.assertIn('Sensitive', REGISTRY)
        from nicktrail import search
        self.assertNotIn('Sensitive', search.ACTIVE)

    def test_lookup_tags_matches_sensitive(self):
        # A profile page that clearly names the handle -> a match, tagged sensitive.
        html = '<html><head><meta property="og:type" content="profile">' \
               '<meta property="profile:username" content="quillon">' \
               '<link rel="canonical" href="https://www.pornhub.com/users/quillon"></head><body>quillon</body></html>'
        client = FakeClient({'state': 'found', 'url': 'https://www.pornhub.com/users/quillon', 'text': html})
        out = sensitive.lookup('Pornhub:quillon', client)
        for m in out.get('matches', []):
            self.assertTrue(m['data']['sensitive'])
            self.assertEqual(m['data']['sensitive_category'], 'adult')

    def test_blocked_site_is_not_a_match(self):
        client = FakeClient({'state': 'blocked', 'detail': 'HTTP 403'})
        out = sensitive.lookup('Xvideos:quillon', client)
        self.assertEqual(out.get('matches', []), [])
        self.assertEqual(out['state'], 'blocked')

    def test_export_hides_sensitive_unless_opted_in(self):
        d = tempfile.TemporaryDirectory()
        s = Store(os.path.join(d.name, 's.sqlite3')); p = s.project('t')
        plain = s.apply_profile(p, 'https://github.com/quillonior', {'alias': 'quillonior'})
        sens = s.add(p, 'https://www.pornhub.com/users/quillon', seed=False)
        s.execute("UPDATE nodes SET state='found',data=? WHERE id=?", (json.dumps({'alias': 'quillon', 'sensitive': True}), sens))
        default = export(s, p, 'json')
        self.assertIn('github.com/quillonior', default)
        self.assertNotIn('pornhub', default)
        opted = export(s, p, 'json', include_sensitive=True)
        self.assertIn('pornhub', opted)
        s.db.close(); d.cleanup()


if __name__ == '__main__':
    unittest.main()
