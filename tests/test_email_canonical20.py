import json
import os
import sqlite3
import tempfile
import unittest

from nicktrail.emailmigration import apply, plan
from nicktrail.graphsignals import analyze
from nicktrail.search import schema as search_schema
from nicktrail.storage import Store, now


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, 'audit.sqlite3')
        self.store = Store(self.path)
        self.project = self.store.project('fictional')

    def tearDown(self):
        self.store.db.close()
        self.dir.cleanup()

    def legacy_email(self, url, ownership='unknown'):
        """Insert an e-mail node exactly as releases before canonical keys did."""
        return self.store.execute("INSERT INTO nodes(project,url,platform,kind,ownership,created) VALUES(?,?,?,?,?,?)",
                                  (self.project, url, 'Deklaracja', 'email', ownership, now())).lastrowid

    def profile(self, url):
        node = self.store.add(self.project, url)
        self.store.execute("UPDATE nodes SET state='found' WHERE id=?", (node,))
        return node

    def contact(self, source, target, snippet):
        self.store.evidence(self.project, source, target, 'public_contact_occurrence', self.store.node(source)['url'], 'bio', snippet)

    def data(self, node):
        return json.loads(self.store.node(node)['data'])


class CanonicalStorageTest(Fixture):
    def test_provider_equivalent_forms_share_one_node_and_keep_published_forms(self):
        first = self.store.add(self.project, 'Jan.Kowalski+github@gmail.com', 'email', seed=False)
        second = self.store.add(self.project, 'jankowalski@googlemail.com', 'email', seed=False)
        self.assertEqual(first, second)
        self.assertEqual(self.store.node(first)['url'], 'jankowalski@gmail.com')
        self.assertEqual(self.data(first)['published_forms'], ['Jan.Kowalski+github@gmail.com', 'jankowalski@googlemail.com'])

    def test_other_domains_keep_dots_and_tags_distinct(self):
        a = self.store.add(self.project, 'jan.kowalski@firma.example', 'email')
        b = self.store.add(self.project, 'jankowalski@firma.example', 'email')
        c = self.store.add(self.project, 'jan+x@firma.example', 'email')
        self.assertEqual(len({a, b, c}), 3)

    def test_existing_legacy_node_is_reused_instead_of_split(self):
        legacy = self.legacy_email('Jan.Kowalski@gmail.com')
        self.assertEqual(self.store.add(self.project, 'jankowalski+x@gmail.com', 'email'), legacy)
        self.assertEqual(len(self.store.rows("SELECT id FROM nodes WHERE kind='email'")), 1)

    def test_confirmation_never_overrides_rejection(self):
        node = self.store.add(self.project, 'person@gmail.com', 'email')
        self.store.decide(node, 'not_mine')
        self.store.add(self.project, 'Person@gmail.com', 'email', confirmed=True)
        self.assertEqual(self.store.node(node)['ownership'], 'not_mine')
        other = self.store.add(self.project, 'other@gmail.com', 'email')
        self.store.add(self.project, 'o.ther@gmail.com', 'email', confirmed=True)
        self.assertEqual(self.store.node(other)['ownership'], 'mine')

    def test_existing_graph_signal_bridges_different_published_forms(self):
        mine = self.profile('https://github.com/fictional-one')
        self.store.decide(mine, 'mine')
        other = self.profile('https://gitlab.com/another-nick')
        self.contact(mine, self.store.add(self.project, 'Fictional.Person@gmail.com', 'email', seed=False), 'Fictional.Person@gmail.com')
        self.contact(other, self.store.add(self.project, 'fictionalperson+gl@gmail.com', 'email', seed=False), 'fictionalperson+gl@gmail.com')
        signals = analyze(self.store.snapshot(self.project))
        self.assertEqual(signals[other][0]['kind'], 'shared_public_email')
        self.assertFalse(signals[other][0]['identity_confirmed'])


class EmailMigrationTest(Fixture):
    def test_merge_moves_evidence_lists_and_records_backup(self):
        a = self.profile('https://github.com/fictional-one')
        self.store.decide(a, 'mine')
        b = self.profile('https://gitlab.com/another-nick')
        old = self.legacy_email('Fictional.Person@gmail.com')
        dup = self.legacy_email('fictionalperson+gl@googlemail.com', ownership='mine')
        self.contact(a, old, 'Fictional.Person@gmail.com')
        self.contact(b, dup, 'fictionalperson+gl@googlemail.com')
        evidence_id = self.store.rows('SELECT id FROM evidence WHERE target=?', (dup,))[0]['id']
        self.store.decide(evidence_id, 'accepted', relation=True)
        scan = self.store.execute("INSERT INTO scans(project,started,status,queue,visited) VALUES(?,?,?,?,?)",
                                  (self.project, now(), 'completed', '[]', json.dumps([a, dup, old]))).lastrowid
        search_schema(self.store)
        search = self.store.execute("INSERT INTO searches(project,nickname,started,status,options) VALUES(?,?,?,?,?)",
                                    (self.project, 'x', now(), 'completed', '{}')).lastrowid
        self.store.execute("INSERT INTO search_tasks(search,platform,term,mode,nodes) VALUES(?,?,?,?,?)",
                           (search, 'GitHub', 'x', 'exact', json.dumps([dup])))

        proposal = plan(self.store)
        self.assertEqual(proposal['merges'], [{'project': self.project, 'survivor': old, 'duplicates': [dup]}])
        result = apply(self.store, self.path)
        self.assertTrue(result['applied'])
        self.assertTrue(os.path.exists(result['backup']))
        backup = sqlite3.connect(result['backup'])
        self.assertEqual(backup.execute("SELECT count(*) FROM nodes WHERE kind='email'").fetchone()[0], 2)
        backup.close()

        emails = self.store.rows("SELECT * FROM nodes WHERE kind='email'")
        self.assertEqual([e['id'] for e in emails], [old])
        self.assertEqual(emails[0]['url'], 'fictionalperson@gmail.com')
        self.assertEqual(emails[0]['ownership'], 'mine')
        self.assertEqual(json.loads(emails[0]['data'])['published_forms'],
                         ['Fictional.Person@gmail.com', 'fictionalperson+gl@googlemail.com'])
        moved = self.store.rows('SELECT target,decision FROM evidence WHERE id=?', (evidence_id,))[0]
        self.assertEqual((moved['target'], moved['decision']), (old, 'accepted'))
        self.assertEqual(json.loads(self.store.rows('SELECT visited FROM scans WHERE id=?', (scan,))[0]['visited']), [a, old])
        self.assertEqual(json.loads(self.store.rows('SELECT nodes FROM search_tasks')[0]['nodes']), [old])
        self.assertEqual(analyze(self.store.snapshot(self.project))[b][0]['kind'], 'shared_public_email')
        self.assertEqual(json.loads(self.store.rows('SELECT summary FROM schema_migrations')[0]['summary'])['merged_groups'], 1)
        self.assertFalse(apply(self.store, self.path)['applied'])

    def test_lone_legacy_node_is_renamed(self):
        node = self.legacy_email('Some.One@googlemail.com')
        result = apply(self.store, self.path, backup_dir=self.dir.name)
        self.assertEqual(result['summary']['renamed'], 1)
        self.assertEqual(self.store.node(node)['url'], 'someone@gmail.com')
        self.assertEqual(self.data(node)['published_forms'], ['Some.One@googlemail.com'])

    def test_conflicting_user_decisions_are_reported_not_merged(self):
        first = self.legacy_email('person@gmail.com', ownership='mine')
        second = self.legacy_email('per.son@gmail.com', ownership='not_mine')
        proposal = plan(self.store)
        self.assertEqual(proposal['merges'], [])
        self.assertEqual(proposal['conflicts'][0]['nodes'], [first, second])
        self.assertFalse(apply(self.store, self.path)['applied'])
        self.assertEqual(len(self.store.rows("SELECT id FROM nodes WHERE kind='email'")), 2)

    def test_colliding_rows_roll_back_only_that_group(self):
        a = self.profile('https://github.com/fictional-one')
        first = self.legacy_email('collide@gmail.com')
        second = self.legacy_email('col.lide@gmail.com')
        for target in (first, second):
            self.store.execute("INSERT INTO evidence(project,source,target,relation,source_url,location,snippet,fetched,method) VALUES(?,?,?,?,?,?,?,?,?)",
                               (self.project, a, target, 'public_contact_occurrence', 'https://github.com/fictional-one', 'bio', 'same', now(), 'parser'))
        lone = self.legacy_email('Lone.Person@googlemail.com')
        result = apply(self.store, self.path)
        self.assertEqual(len(result['blocked']), 1)
        self.assertIn('evidence', result['blocked'][0]['reason'])
        self.assertEqual({r['target'] for r in self.store.rows('SELECT target FROM evidence')}, {first, second})
        self.assertEqual(self.store.node(second)['url'], 'col.lide@gmail.com')
        self.assertEqual(self.store.node(lone)['url'], 'loneperson@gmail.com')


if __name__ == '__main__':
    unittest.main()
