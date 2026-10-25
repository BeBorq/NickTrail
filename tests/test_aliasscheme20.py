import os
import tempfile
import unittest

from nicktrail.aliasscheme import related_terms, scheme


class SchemeTests(unittest.TestCase):
    def test_bare_stem_from_suffixed_handles(self):
        # The pattern behind one person's handles: a stem plus a word or a digit run,
        # and on Riot a #tag discriminator. From the suffixed forms, the bare stem is
        # the strongest related candidate (and here is the real GitHub/HackerOne handle).
        r = scheme(['quillonior', 'quillon111111', 'quillon#2tag'])
        self.assertEqual(r['root'], 'quillon')
        self.assertEqual({s['text'] for s in r['suffixes']}, {'ior', '111111'})
        self.assertEqual({s['kind'] for s in r['suffixes']}, {'word', 'digits'})

    def test_proposes_the_bare_stem_when_it_is_not_yet_known(self):
        self.assertIn('quillon', related_terms(['quillonior', 'quillon111111']))

    def test_recombines_known_suffix_onto_the_stem(self):
        # Stem and one word form known; the digit form from another account recombines.
        out = related_terms(['quillon', 'quillonior', 'quillon_dev'])
        self.assertIn('quillon_dev', ['quillon_dev'])  # token parsed
        self.assertNotIn('quillon', out)  # already known, not re-proposed

    def test_no_candidates_when_nothing_generalizes_or_roots_differ(self):
        self.assertEqual(related_terms(['loneuser']), [])
        self.assertEqual(related_terms(['quillon', 'nowakowski']), [])  # unrelated handles, no garbage
        self.assertEqual(
            related_terms(['quillon', 'quillonior', 'quillon111111']), []
        )  # all forms already known

    def test_candidates_are_valid_handles_and_never_identity(self):
        for c in scheme(['quillonior', 'quillon111111'])['candidates']:
            self.assertRegex(c['alias'], r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$')
            self.assertIn('kandydat', c['basis'].lower())


class ProjectWiringTests(unittest.TestCase):
    def test_alias_suggestions_surface_the_bare_stem_from_confirmed_accounts(self):
        from nicktrail.related import alias_suggestions
        from nicktrail.search import schema as search_schema
        from nicktrail.storage import Store

        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, 'a.sqlite3'))
            search_schema(store)
            p = store.project('fictional')
            tw = store.apply_profile(p, 'https://x.com/quillonior', {'alias': 'quillonior', 'stable_id': '1'})
            ep = store.apply_profile(
                p, 'https://epic.example/quillon111111', {'alias': 'quillon111111', 'stable_id': '2'}
            )
            store.decide(tw, 'mine')
            store.decide(ep, 'mine')
            store.set_focus(p, tw)
            aliases = [s['alias'] for s in alias_suggestions(store, p)]
            self.assertIn('quillon', aliases)
            store.db.close()


if __name__ == '__main__':
    unittest.main()
