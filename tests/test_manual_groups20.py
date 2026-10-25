import unittest
from nicktrail.diagnostics import MANUAL_GROUPS, manual_group, reason


class ManualGroupTests(unittest.TestCase):
    def test_every_reason_code_maps_to_a_group(self):
        # Each status `reason()` can emit must land in a named group (never crash the panel).
        codes = {'INDEX_ONLY', 'NO_PUBLIC_SEARCH'}
        for _, _, needles in (('x', 'x', ('LOCAL_BUDGET_EXHAUSTED',)),):
            pass
        for state in ('blocked', 'error', 'partial', 'unsupported', 'unverified', 'not_found'):
            codes.add(reason(state, ''))
        for detail in (
            'HTTP 403',
            'robots.txt',
            'captcha',
            'HTTP 401',
            'HTTP 429 backoff',
            'javascript required',
            'limit domeny',
        ):
            codes.add(reason('blocked', detail))
        for c in codes:
            g = manual_group(c)
            self.assertIn('group', g)
            self.assertIsInstance(g['group_order'], int)

    def test_blocks_are_ordered_captcha_access_robots_limit(self):
        order = [
            manual_group(c)['group_order']
            for c in ('CAPTCHA', 'BLOCKED_BY_PLATFORM', 'ROBOTS_RESTRICTED', 'RATE_LIMITED')
        ]
        self.assertEqual(order, sorted(order))
        self.assertEqual(manual_group('CAPTCHA')['group'], 'captcha')
        self.assertEqual(manual_group('LOGIN_REQUIRED')['group'], 'access')
        self.assertEqual(manual_group('NETWORK_ERROR')['group'], 'other')

    def test_labels_are_unique_and_present(self):
        labels = [label for _, label, _ in MANUAL_GROUPS]
        self.assertEqual(len(labels), len(set(labels)))


if __name__ == '__main__':
    unittest.main()
