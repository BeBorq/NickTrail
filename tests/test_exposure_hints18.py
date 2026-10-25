import unittest
from nicktrail.exposure import service_hints


class ExposureHints18Tests(unittest.TestCase):
    def test_only_verified_nonfabricated_metadata_and_host_boundaries(self):
        definitions = [
            {'name': 'Forum', 'profile_url': 'https://users.example.org/u/{nick}'},
            {'name': 'Unrelated', 'profile_url': 'https://notexample.org/{nick}'},
        ]
        records = [
            {'Domain': 'example.org', 'IsVerified': True},
            {'Domain': 'example.org', 'IsVerified': True},
            {'Domain': 'unverified.org', 'IsVerified': False},
            {'Domain': 'spam.org', 'IsVerified': True, 'IsSpamList': True},
            {'Domain': 'fake.org', 'IsVerified': True, 'IsFabricated': True},
        ]
        result = service_hints(records, definitions)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['services'], ['Forum'])
        self.assertFalse(result[0]['identity_evidence'])
        self.assertEqual(result[0]['network_calls'], 0)

    def test_malformed_domains_are_never_links_or_queries(self):
        records = [
            {'Domain': d, 'IsVerified': True}
            for d in [
                'https://example.org/a',
                '127.0.0.1',
                'localhost',
                'example.org?secret=x',
                'bad..org',
                'x@example.org',
                '-bad.org',
            ]
        ]
        self.assertEqual(service_hints(records, []), [])

    def test_unknown_service_keeps_review_hint_without_fabricated_adapter(self):
        result = service_hints([{'Domain': 'unlisted.example', 'IsVerified': True}], [])
        self.assertEqual(result[0]['services'], [])
