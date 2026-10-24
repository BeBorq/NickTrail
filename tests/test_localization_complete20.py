"""Every Polish text the panel shows must have an English copy."""
import re
import unittest
from pathlib import Path

from nicktrail.localization import localize_response, render_panel, translate_message

PANEL = Path(__file__).parents[1] / 'nicktrail/panel.html'
POLISH = re.compile('[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]')


class EnglishPanelCompleteTests(unittest.TestCase):
    def setUp(self):
        self.page = render_panel(PANEL.read_text(encoding='utf-8'), 'en')

    def test_no_polish_in_html_text_or_attributes(self):
        body = re.sub(r'<script\b[\s\S]*?</script>|<style\b[\s\S]*?</style>', '', self.page)
        texts = [t.strip() for t in re.split(r'<[^>]+>', body) if POLISH.search(t)]
        attrs = [a for a in re.findall(r'(?:placeholder|title|aria-label)="([^"]*)"', body) if POLISH.search(a)]
        self.assertEqual(texts, [])
        self.assertEqual(attrs, [])

    def test_no_polish_in_script_string_literals(self):
        scripts = ''.join(re.findall(r'<script\b[^>]*>([\s\S]*?)</script>', self.page))
        literals = sorted({m for m in re.findall(r"'((?:[^'\\]|\\.)*)'", scripts) if POLISH.search(m)})
        self.assertEqual(literals, [])

    def test_new_connection_controls_are_translated(self):
        for english in ('Not part of this group', 'Different people', 'Your account', 'Shared contact'):
            self.assertIn(english, self.page)

    def test_server_messages_and_group_conflict_reason(self):
        why = 'Nie połączono: konto #3 i konto #7 oznaczono jako różne osoby, a połączenie objęłoby oba'
        self.assertEqual(translate_message(why, 'en'),
                         'Not joined: account #3 and account #7 were marked as different people, and this join would include both')
        result = localize_response('/api/separate', {'result': 'Zapisano: to różne osoby. Te konta nie zostaną połączone w jedną grupę.'}, 'en')
        self.assertTrue(result['result'].startswith('Saved: different people'))
        self.assertEqual(localize_response('/api/add', {'result': 42}, 'en'), {'result': 42})


if __name__ == '__main__':
    unittest.main()


class EnglishServerMessagesRc18(unittest.TestCase):
    """rc18: composed server messages, toasts, CLI errors and reports have no Polish in English mode."""
    POLISH = __import__('re').compile(r'[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]')

    def test_composed_messages(self):
        from nicktrail.localization import translate_message as t
        for message in (
                'Serwis odmówił 3 razy z rzędu (HTTP 429; RATE_LIMITED); pominięto, żeby nie blokować reszty wyszukiwania. Sprawdź ręcznie.',
                'fictional / nick lub alias: brak trafień — Nick nie spełnia reguł serwisu | fictional / podobne nazwy: znaleziono',
                'Do 10 wyników wyszukiwarki serwisu dla nazwy „fictional”. Podobieństwo nie jest dowodem wspólnego właściciela; strona 2; do 3 stron.',
                'Shinden: 1 adres(y) z archiwum internetu; do sprawdzenia ręcznie',
                'ROBOTS_RESTRICTED: automatyczny odczyt zabroniony (zapamiętana odmowa)',
                'Błąd programu (TypeError). Szczegóły w pliku .errors.log obok bazy.',
                'Uruchomiono · Twoje deklaracje w wyszukiwaniu: fictional, Polska'):
            self.assertIsNone(self.POLISH.search(t(message, 'en').replace('Polska', '')), message)

    def test_platform_identifiers_are_never_rewritten(self):
        import json
        from pathlib import Path
        from nicktrail.localization import _fragments, translate_message
        root = Path(__file__).resolve().parents[1] / 'nicktrail'
        literals = json.loads((root / 'translations.json').read_text(encoding='utf-8'))['literals']
        from nicktrail.localization import localize_response
        pattern, table = _fragments()
        for identifier in ('Strona', 'Deklaracja', 'Moje konta'):
            self.assertNotIn("'" + identifier + "'", literals)
            self.assertNotIn(identifier, table)
        state = {'manual_queue': [{'platform': 'Strona', 'source_platform': 'Moje konta', 'term': 'Deklaracja', 'reason': 'Nie znaleziono'}]}
        row = localize_response('/api/state', state, 'en')['manual_queue'][0]
        self.assertEqual((row['platform'], row['source_platform'], row['term']), ('Strona', 'Moje konta', 'Deklaracja'))
        self.assertEqual(row['reason'], 'Not found')

    def test_english_report_wording(self):
        from nicktrail.exporting import export
        from nicktrail.storage import Store
        store = Store(':memory:')
        project = store.project('Fixture')
        store.add(project, 'https://github.com/fictional')
        for fmt in ('markdown', 'html'):
            text = export(store, project, fmt, language='en')
            self.assertIsNone(self.POLISH.search(text), fmt)
        self.assertIn('## Elementy', export(store, project, 'markdown', language='pl'))
        store.db.close()

    def test_english_ai_packet_prompt(self):
        from nicktrail.aipacket import PROMPT_EN
        self.assertIsNone(self.POLISH.search(PROMPT_EN))
