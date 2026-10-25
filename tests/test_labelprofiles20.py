import unittest
from nicktrail.adapters import extract


class LabelProfiles20Tests(unittest.TestCase):
    def read(self, text, context='own'):
        return extract(text, 'https://fiction.example/about', 'bio', context)

    def test_plain_declared_handles_have_method_and_original_snippet(self):
        rows = self.read('GitHub: fictional-dev\nTwitter/X: @fictional_user\nSteam: fictional_player')
        self.assertEqual(
            {r['url'] for r in rows},
            {
                'https://github.com/fictional-dev',
                'https://x.com/fictional_user',
                'https://steamcommunity.com/id/fictional_player',
            },
        )
        self.assertTrue(
            all('.label.' in r['location'] and r['snippet'] and r['relation'] == 'links' for r in rows)
        )

    def test_prose_third_parties_quotes_emails_files_and_invalid_paths_do_not_become_accounts(self):
        for text in (
            'Thanks to GitHub: friend',
            'His GitHub: friend',
            '"GitHub: friend"',
            'GitHub: friend (my colleague)',
            'GitHub: friend@example.com',
            'GitHub: script.py',
            'GitHub: friend/repo',
            'GitHub: --friend',
            'X: home',
            'GitHub: login',
            'Steam: an ordinary sentence',
        ):
            self.assertEqual([r for r in self.read(text) if '.label.' in r['location']], [], text)

    def test_nonown_context_is_mention_and_html_scripts_are_excluded(self):
        self.assertEqual(self.read('GitHub: fictional', context='quoted')[0]['relation'], 'mentions')
        self.assertEqual(self.read('<script>GitHub: fictional</script>'), [])
        self.assertEqual(self.read('<p>GitHub: fictional</p>')[0]['url'], 'https://github.com/fictional')

    def test_separate_clauses_and_numeric_steam_id(self):
        rows = self.read('my GitHub: fictional | X: @fictional\nSteam: 76561198000000001')
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]['url'], 'https://steamcommunity.com/profiles/76561198000000001')
