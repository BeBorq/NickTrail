"""rc15: the user's own declarations are used by new searches (and only confirmed ones)."""

import unittest

from nicktrail.declarations import apply, describe
from nicktrail.storage import Store


class Declarations(unittest.TestCase):
    def setUp(self):
        self.s = Store(':memory:')
        self.p = self.s.project('Fictional')

    def tearDown(self):
        self.s.db.close()

    def test_confirmed_nicks_become_aliases_and_fill_empty_criteria(self):
        for value, kind in (
            ('fictional', 'alias'),
            ('fictional-two', 'alias'),
            ('Ada Fictional', 'display'),
            ('Polska', 'country'),
            ('ada@example.org', 'email'),
        ):
            self.s.add(self.p, value, kind, True)
        self.s.add(self.p, 'unconfirmed-nick', 'alias', False)
        nickname, aliases, criteria, used = apply(self.s, self.p, 'fictional', [], None)
        self.assertEqual(nickname, 'fictional')
        self.assertEqual(aliases, ['fictional-two'])
        self.assertEqual(criteria['keywords'], 'Ada Fictional')
        self.assertEqual(criteria['location'], 'Polska')
        self.assertNotIn('ada@example.org', str(criteria))  # the e-mail never becomes a query
        self.assertEqual(describe(used), 'fictional-two, Ada Fictional, Polska')

    def test_empty_nickname_uses_the_first_declared_nick(self):
        self.s.add(self.p, 'fictional', 'alias', True)
        nickname, aliases, criteria, used = apply(self.s, self.p, '', [], None)
        self.assertEqual(nickname, 'fictional')
        self.assertEqual(used['nickname'], 'fictional')

    def test_explicit_criteria_are_never_overwritten(self):
        self.s.add(self.p, 'Ada Fictional', 'display', True)
        self.s.add(self.p, 'Polska', 'country', True)
        _, _, criteria, used = apply(self.s, self.p, 'nick', [], {'first_name': 'Jan', 'location': 'Kraków'})
        self.assertEqual(criteria['location'], 'Kraków')
        self.assertEqual(criteria['keywords'], '')
        self.assertEqual(used, {})

    def test_alias_limit_is_respected(self):
        for i in range(6):
            self.s.add(self.p, 'nick%d' % i, 'alias', True)
        _, aliases, _, _ = apply(self.s, self.p, 'main', ['a', 'b', 'c'], None)
        self.assertEqual(len(aliases), 4)

    def test_user_added_marks_only_what_the_user_entered(self):
        from nicktrail.imports import import_accounts

        import_accounts(self.s, self.p, ['https://github.com/fictional'], mine=True)
        self.s.apply_profile(self.p, 'https://gitlab.com/someone-else', {'alias': 'someone-else'})
        rows = {r['url']: r['user_added'] for r in self.s.rows('SELECT url,user_added FROM nodes')}
        self.assertEqual(rows['https://github.com/fictional'], 1)
        self.assertEqual(rows['https://gitlab.com/someone-else'], 0)

    def test_new_search_reads_the_users_own_accounts_first(self):
        from nicktrail.search import discover

        own = self.s.add(self.p, 'https://github.com/fictional')
        self.s.decide(own, 'mine')
        other = self.s.add(self.p, 'https://gitlab.com/someone')

        class C:
            count = 0

        discover(self.s, self.p, 'fictional', platforms=['GitHub'], client=C(), stopped=lambda: True)
        enrich = self.s.rows("SELECT platform,term FROM search_tasks WHERE mode='enrich'")
        self.assertEqual([(r['platform'], r['term']) for r in enrich], [('Moje konta', str(own))])


if __name__ == '__main__':
    unittest.main()
