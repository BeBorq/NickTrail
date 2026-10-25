"""Every source the panel offers must pass the search validation (rc12 'Nieznane źródło' bug)."""

import re
import unittest
from pathlib import Path

from nicktrail.providers import describe
from nicktrail.search import ACTIVE, LIMITED, OPTIN


class SourceValidation(unittest.TestCase):
    def test_every_offered_source_is_accepted(self):
        accepted = set(ACTIVE) | set(LIMITED) | set(OPTIN)
        offered = [p['id'] for p in describe()]
        self.assertEqual([p for p in offered if p not in accepted], [])
        self.assertIn('Xbox', accepted)
        self.assertIn('Sensitive', accepted)

    def test_web_validation_knows_opt_in_sources(self):
        source = (Path(__file__).resolve().parents[1] / 'nicktrail' / 'web.py').read_text(encoding='utf-8')
        compact = re.sub(r'\s+', '', source)
        start = compact.index('unknown=[pforpindata')
        self.assertIn('OPTIN', compact[start : compact.index('ifunknown:', start)])

    def test_searchflow_names_the_unknown_source(self):
        from nicktrail import searchflow

        text = Path(searchflow.__file__).read_text(encoding='utf-8')
        self.assertTrue(re.search(r"Nieznane źródło: '\s*\+", text))


if __name__ == '__main__':
    unittest.main()


class OnePlaceForLinks(unittest.TestCase):
    def test_links_are_entered_only_in_my_accounts_section(self):
        html = (Path(__file__).resolve().parents[1] / 'nicktrail' / 'panel.html').read_text(encoding='utf-8')
        self.assertNotIn('id="known_urls"', html)
        self.assertNotIn('<option value="url">', html)
        section = html[html.index('<section id="importPanel">') :]
        section = section[: section.index('</section>')]
        for control in ('id="accountList"', 'id="type"', 'id="value"', 'id="seeds"'):
            self.assertIn(control, section)

    def test_english_panel_translates_the_merged_section(self):
        from nicktrail.localization import render_panel

        html = render_panel(
            (Path(__file__).resolve().parents[1] / 'nicktrail' / 'panel.html').read_text(encoding='utf-8'),
            'en',
        )
        for polish in (
            'Moje konta i znane adresy',
            'Jedyne miejsce na linki',
            'Twoje konta i wpisy',
            'niepotwierdzone',
        ):
            self.assertNotIn(polish, html)
