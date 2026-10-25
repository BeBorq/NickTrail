import json, tempfile, unittest
from pathlib import Path
from nicktrail.storage import Store
from nicktrail.search import schema
from nicktrail.golden import evaluate, normalize


class Golden18Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / 'b.db')
        self.addCleanup(self.s.db.close)
        self.p = self.s.project('Synthetic')
        schema(self.s)

    def run_case(self, ids, state='found', detail=''):
        search = self.s.execute(
            'insert into searches(project,nickname,status,options) values(?,?,?,?)',
            (self.p, 'seed', 'completed', json.dumps({'_terms': ['seed']})),
        ).lastrowid
        self.s.execute(
            'insert into search_tasks(search,platform,term,mode,state,nodes,detail) values(?,?,?,?,?,?,?)',
            (search, 'GitHub', 'seed', 'exact', state, json.dumps(ids), detail),
        )
        return search

    def case(self):
        return {
            'schema_version': 2,
            'seeds': {
                'usernames': ['seed'],
                'aliases': ['other'],
                'full_name': 'Fictional Example',
                'location': 'Synthetic City',
                'public_email': 'test@synthetic.example',
            },
            'true_profiles': [
                {'platform': 'GitHub', 'url': 'https://github.com/seed', 'expected_username': 'seed'}
            ],
            'false_profiles': [{'url': 'https://github.com/distractor'}],
        }

    def test_run_scope_excludes_preexisting_true_profile(self):
        self.s.apply_profile(self.p, 'https://github.com/seed', {'alias': 'seed'})
        id = self.run_case([])
        r = evaluate(self.s, self.p, self.case(), search_id=id)
        self.assertEqual(r['found_known_true'], 0)
        self.assertEqual(r['metrics']['false_negative_rate'], 1)
        self.assertEqual(len(r['missing']), 1)

    def test_labels_held_out_and_unjudged_separate(self):
        bad = self.s.apply_profile(self.p, 'https://github.com/distractor', {'alias': 'seed'})
        self.s.decide(bad, 'not_mine')
        good = self.s.apply_profile(self.p, 'https://github.com/seed', {'alias': 'seed'})
        self.s.decide(good, 'mine')
        self.s.set_focus(self.p, good)
        unknown = self.s.apply_profile(self.p, 'https://github.com/unknown', {'alias': 'seed'})
        id = self.run_case([bad, good, unknown])
        r = evaluate(self.s, self.p, self.case(), search_id=id)
        self.assertEqual(r['metrics']['automatic_coverage'], 1)
        self.assertEqual(r['metrics']['false_positive_rate'], 1)
        self.assertEqual(r['metrics']['precision_at_1'], 0)
        self.assertEqual(r['metrics']['mrr'], 0.5)
        self.assertEqual(r['metrics']['unjudged_at_3'], 1)
        self.assertEqual(self.s.node(good)['ownership'], 'mine')
        self.assertEqual(self.s.node(bad)['ownership'], 'not_mine')
        self.assertNotIn('test@synthetic.example', json.dumps(r))

    def test_blocked_missing_profile_classified_without_node(self):
        id = self.run_case([], 'blocked', 'HTTP 429 Retry-After')
        r = evaluate(self.s, self.p, self.case(), search_id=id)
        self.assertEqual(r['metrics']['blocked_coverage'], 1)
        self.assertEqual(r['missing'][0]['code'], 'RATE_LIMITED')
        self.assertEqual(r['exact_audit']['sources_attempted'], 1)

    def test_cross_project_and_conflicting_labels_rejected(self):
        id = self.run_case([])
        with self.assertRaises(ValueError):
            evaluate(self.s, self.s.project('Other'), self.case(), search_id=id)
        case = self.case()
        case['false_profiles'] = case['true_profiles']
        with self.assertRaises(ValueError):
            normalize(case)

    def test_no_negatives_means_no_measured_false_positive_rate(self):
        case = self.case()
        case.pop('false_profiles')
        r = evaluate(self.s, self.p, case)
        self.assertIsNone(r['metrics']['false_positive_rate'])

    def test_api_validated_discourse_canonical_case_resolves_reference(self):
        node = self.s.apply_profile(
            self.p,
            'https://synthetic.example/u/Fictional',
            {
                'alias': 'Fictional',
                'public_engine': 'discourse',
                'id_scope': 'synthetic.example',
                'stable_id': '42',
            },
        )
        id = self.run_case([node])
        case = {
            'seeds': {'aliases': ['fictional']},
            'true_profiles': [
                {'url': 'https://synthetic.example/u/fictional', 'expected_username': 'fictional'}
            ],
        }
        result = evaluate(self.s, self.p, case, search_id=id)
        self.assertEqual(result['found_known_true'], 1)
        self.assertEqual(result['metrics']['exact_username_recall'], 1)

    def test_generic_case_sensitive_paths_do_not_get_merged_by_benchmark(self):
        node = self.s.apply_profile(self.p, 'https://synthetic.example/u/Fictional', {'alias': 'Fictional'})
        id = self.run_case([node])
        case = {'aliases': ['fictional'], 'true_profiles': ['https://synthetic.example/u/fictional']}
        self.assertEqual(evaluate(self.s, self.p, case, search_id=id)['found_known_true'], 0)
