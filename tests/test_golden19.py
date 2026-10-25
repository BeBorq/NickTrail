import tempfile, json, unittest
from pathlib import Path
from nicktrail.storage import Store
from nicktrail.search import schema
from nicktrail.golden import evaluate, normalize, save_snapshot, snapshot_history, compare_snapshots


class Golden19Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / 'fixture.db')
        self.addCleanup(self.s.db.close)
        self.p = self.s.project('Synthetic')
        schema(self.s)
        self.case = {
            'case_id': 'fictional',
            'aliases': ['fictional'],
            'true_profiles': [
                {'url': 'https://github.com/fictional', 'expected_username': 'fictional'},
                {
                    'url': 'https://www.facebook.com/profile.php?id=123456789012345',
                    'discovery_class': 'KNOWN_TRUE_BUT_NOT_DERIVABLE',
                    'derivability_reason': 'Numeric ID without a known bridge',
                },
            ],
            'false_profiles': [{'url': 'https://github.com/wrong'}],
        }

    def run_case(self, ids):
        return (
            self.s.execute(
                'insert into searches(project,nickname,status,options,started,finished,requests) values(?,?,?,?,?,?,?)',
                (
                    self.p,
                    'fictional',
                    'completed',
                    json.dumps({'_terms': ['fictional']}),
                    '2026-01-01T12:00:00',
                    '2026-01-01T12:00:10',
                    5,
                ),
            ).lastrowid
            if not ids
            else self._run_nodes(ids)
        )

    def _run_nodes(self, ids):
        id = self.run_case([])
        self.s.execute(
            'insert into search_tasks(search,platform,term,mode,state,nodes,requests) values(?,?,?,?,?,?,?)',
            (id, 'GitHub', 'fictional', 'exact', 'found', json.dumps(ids), 5),
        )
        return id

    def test_nonderivable_ref_does_not_reduce_seed_recall_and_cost_is_explicit(self):
        node = self.s.apply_profile(self.p, 'https://github.com/fictional', {'alias': 'fictional'})
        id = self.run_case([node])
        r = evaluate(self.s, self.p, self.case, id)
        self.assertEqual(r['metrics']['seed_discoverable_recall'], 1)
        self.assertEqual(r['metrics']['total_known_profile_coverage'], 0.5)
        self.assertEqual(r['metrics']['exact_username_recall'], 1)
        self.assertEqual(r['metrics']['non_derivable_known_profiles'], 1)
        self.assertEqual(r['metrics']['requests_per_known_useful_profile'], 5)
        self.assertEqual(r['metrics']['scan_seconds'], 10)
        self.assertIsNone(r['metrics']['false_positive_rate'])
        self.assertEqual(r['metrics']['known_negative_reference_visibility_rate'], 0)

    def test_visible_unread_false_lead_is_counted_in_precision_and_fpr(self):
        node = self.s.add(self.p, 'https://github.com/wrong')
        self.s.execute(
            'update nodes set data=? where id=?',
            (json.dumps({'alias': 'fictional', 'indexed_only': True}), node),
        )
        id = self.run_case([node])
        r = evaluate(self.s, self.p, self.case, id)
        self.assertEqual(r['metrics']['visible_candidate_count'], 1)
        self.assertEqual(r['metrics']['false_positive_rate'], 1)
        self.assertEqual(r['metrics']['precision_at_1'], 0)
        self.assertEqual(r['found_known_true'], 0)
        self.assertEqual(r['metrics']['known_negative_references_retrieved'], 1)
        self.assertEqual(r['metrics']['false_positive_rate_among_retrieved_known_negatives'], 1)

    def test_snapshots_immutable_labels_held_out_and_scope_change_disclosed(self):
        node = self.s.apply_profile(self.p, 'https://github.com/fictional', {'alias': 'fictional'})
        id = self.run_case([node])
        first = save_snapshot(self.s, self.p, self.case, id)
        self.s.decide(node, 'not_mine')
        second = save_snapshot(self.s, self.p, self.case, id)
        self.assertEqual(first['metrics'], second['metrics'])
        comparison = compare_snapshots(self.s, self.p, first['snapshot_id'], second['snapshot_id'])
        self.assertTrue(comparison['same_reference_definition'])
        self.assertTrue(comparison['same_scan_scope'])
        self.s.execute('update nodes set state=? where id=?', ('blocked', node))
        self.assertEqual(snapshot_history(self.s, self.p)[-1]['metrics']['seed_discoverable_recall'], 1)
        with self.assertRaises(ValueError):
            compare_snapshots(self.s, self.s.project('Other'), first['snapshot_id'], second['snapshot_id'])

    def test_unknown_classes_and_unsupported_nonderivability_claim_rejected(self):
        self.case['true_profiles'][1]['discovery_class'] = 'made_up'
        with self.assertRaises(ValueError):
            normalize(self.case)
        self.case['true_profiles'][1]['discovery_class'] = 'MANUAL_ONLY'
        self.case['true_profiles'][1].pop('derivability_reason')
        with self.assertRaises(ValueError):
            normalize(self.case)

    def test_fuzzy_and_name_pollution_use_actual_task_origins_not_generic_hint_labels(self):
        fuzzy = self.s.apply_profile(self.p, 'https://github.com/fuzzy-person', {'alias': 'fuzzy-person'})
        name = self.s.apply_profile(
            self.p,
            'https://github.com/named-person',
            {'alias': 'named-person', 'display': 'Fictional Person'},
        )
        id = self.run_case([])
        for node, mode, term in [(fuzzy, 'related', 'fictional'), (name, 'context', 'Fictional Person')]:
            self.s.execute(
                'insert into search_tasks(search,platform,term,mode,state,nodes) values(?,?,?,?,?,?)',
                (id, 'GitHub', term, mode, 'found', json.dumps([node])),
            )
            self.s.execute(
                'insert into candidate_hints(project,node,search,term,basis) values(?,?,?,?,?)',
                (self.p, node, id, term, 'service_search'),
            )
        case = json.loads(json.dumps(self.case))
        case['seeds'] = {'aliases': ['fictional'], 'full_name': 'Fictional Person'}
        case.pop('aliases')
        r = evaluate(self.s, self.p, case, id)
        self.assertEqual(r['pollution']['fuzzy_only'], 1)
        self.assertEqual(r['pollution']['name_only'], 1)

    def test_project_snapshot_with_alias_email_and_discord_nodes_does_not_treat_them_as_urls(self):
        self.s.add(self.p, 'fictional', 'alias')
        self.s.add(self.p, 'public@fictional.example', 'email')
        node = self.s.apply_profile(self.p, 'https://github.com/fictional', {'alias': 'fictional'})
        result = evaluate(self.s, self.p, self.case)
        self.assertEqual(result['found_known_true'], 1)
        self.assertEqual(result['scope'], 'project_snapshot')
