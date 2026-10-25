import unittest
from nicktrail.identity import identify


class Canonical18Tests(unittest.TestCase):
    def test_github_profile_view_query_is_not_new_identity(self):
        self.assertEqual(
            identify('https://github.com/Fictional?tab=overview&from=2020-01-01')['url'],
            'https://github.com/fictional',
        )
        self.assertEqual(identify('https://github.com/Fictional/project')['kind'], 'project')

    def test_x_application_routes_are_not_accounts(self):
        for path in (
            'home?lang=pl',
            'settings',
            'i/flow/login',
            'search?q=fictional',
            'messages',
            'intent/tweet',
        ):
            self.assertEqual(identify('https://x.com/' + path)['kind'], 'page')
        self.assertEqual(identify('https://x.com/Fictional?lang=pl')['url'], 'https://x.com/fictional')

    def test_facebook_numeric_id_retained_tracking_removed(self):
        self.assertEqual(
            identify('https://www.facebook.com/profile.php?id=123456789&sk=about')['url'],
            'https://www.facebook.com/profile.php?id=123456789',
        )
        for path in ('profile.php', 'groups/123', 'login', 'marketplace'):
            self.assertEqual(identify('https://www.facebook.com/' + path)['kind'], 'page')

    def test_benchmark_rejects_x_home_as_ground_truth_profile(self):
        from nicktrail.golden import normalize

        with self.assertRaises(ValueError):
            normalize({'true_profiles': ['https://x.com/home?lang=pl']})
