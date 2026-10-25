import json
import unittest
from nicktrail.ranking import evaluate, focus_results


def node(id, alias='fictional', ownership='unknown'):
    return {
        'id': id,
        'state': 'found',
        'kind': 'profile',
        'ownership': ownership,
        'data': json.dumps({'alias': alias}),
        'url': 'https://example.org/' + str(id),
    }


def snapshot(nodes, edges=None):
    return {'nodes': nodes, 'evidence': edges or [], 'focus': [{'node': 1}], 'scans': []}


def edge(source, target, current=1, decision='unknown', relation='links'):
    return {
        'source': source,
        'target': target,
        'current': current,
        'decision': decision,
        'relation': relation,
    }


class RankingTests(unittest.TestCase):
    def test_alias_alone_is_weak_and_missing_data_unscored(self):
        r = evaluate(snapshot([node(1), node(2), node(3, 'other')]))
        self.assertEqual(r['nodes']['2']['score'], 8)
        self.assertIsNone(r['nodes']['3']['score'])
        self.assertTrue(r['nodes']['1']['selected'])

    def test_current_links_outweigh_nickname_and_rejected_edges_do_not(self):
        s = snapshot([node(1), node(2), node(3, 'other')], [edge(1, 3), edge(3, 1)])
        r = evaluate(s)
        self.assertGreater(r['nodes']['3']['score'], r['nodes']['2']['score'])
        s['evidence'][0]['current'] = 0
        self.assertNotIn('link', evaluate(s)['nodes']['3']['weights'])
        self.assertNotIn('reciprocal', evaluate(s)['nodes']['3']['weights'])
        self.assertIn('graph_inbound', evaluate(s)['nodes']['3']['weights'])
        s['evidence'][0].update(current=1, decision='rejected')
        self.assertNotIn('link', evaluate(s)['nodes']['3']['weights'])
        self.assertNotIn('reciprocal', evaluate(s)['nodes']['3']['weights'])
        self.assertIn('graph_inbound', evaluate(s)['nodes']['3']['weights'])

    def test_feedback_recomputes_without_duplicate_training_or_self_boost(self):
        s = snapshot([node(1), node(2), node(3, ownership='mine')])
        positive = evaluate(s)
        self.assertGreater(positive['nodes']['2']['score'], 8)
        self.assertEqual(positive['nodes']['3']['score'], 8)
        self.assertEqual(positive, evaluate(s))
        s['nodes'][2]['ownership'] = 'not_mine'
        negative = evaluate(s)
        self.assertLess(negative['nodes']['2']['score'], 8)
        self.assertTrue(negative['nodes']['3']['rejected'])
        s['nodes'][2]['ownership'] = 'unknown'
        self.assertEqual(evaluate(s)['nodes']['2']['score'], 8)

    def test_focus_view_only_current_edges_and_matching_scans(self):
        s = snapshot([node(1), node(2)], [edge(1, 2), edge(1, 3, current=0)])
        s['scans'] = [
            {'options': json.dumps({'_focus_root': 1})},
            {'options': json.dumps({'_focus_root': 9})},
        ]
        r = focus_results(s)
        self.assertEqual(len(r['links']), 1)
        self.assertEqual(len(r['scans']), 1)

    def test_no_reference_does_not_reuse_another_person(self):
        s = snapshot([node(1, ownership='not_mine'), node(2)])
        self.assertIsNone(evaluate(s)['reference'])
        self.assertIsNone(evaluate(s)['nodes']['2']['score'])

    def test_partial_name_is_weaker_and_manual_link_is_separate(self):
        s = snapshot([node(1), node(2), node(3)])
        s['nodes'][1]['data'] = json.dumps({'display': 'Anna Other'})
        s['nodes'][2]['data'] = json.dumps({'display': 'Anna Fictional'})
        r = evaluate(s, {'first_name': 'Anna', 'last_name': 'Fictional'})
        self.assertLess(r['nodes']['2']['score'], r['nodes']['3']['score'])
        s['evidence'] = [edge(1, 2) | {'method': 'manual_observation'}]
        r = evaluate(s)
        self.assertIn('manual', r['nodes']['2']['weights'])
        self.assertNotIn('link', r['nodes']['2']['weights'])

    def test_accepted_two_step_path_ignores_rejected_intermediate(self):
        s = snapshot(
            [node(1), node(2, 'other'), node(3, 'third')],
            [edge(1, 2, decision='accepted'), edge(2, 3, decision='accepted')],
        )
        s['nodes'][1]['state'] = 'found'
        self.assertIn('accepted_path', evaluate(s)['nodes']['3']['weights'])
        s['nodes'][1]['ownership'] = 'not_mine'
        self.assertIsNone(evaluate(s)['nodes']['3']['score'])

    def test_query_alias_is_global_priority_without_inflating_identity_score(self):
        s = snapshot(
            [
                node(1, 'unrelated'),
                node(2, 'fictionala'),
                node(13, 'Fictionalq'),
                node(24, 'FICTIONALQ'),
                node(30, 'Fictional'),
            ]
        )
        s['focus'] = []
        r = evaluate(s, query_terms=['Fictional', 'Fictionalq'])
        self.assertEqual(set(r['order'][:3]), {13, 24, 30})
        self.assertEqual(r['nodes']['13']['query_match'], 3)
        self.assertIsNone(r['nodes']['13']['score'])
        s['nodes'][2]['ownership'] = 'not_mine'
        self.assertEqual(evaluate(s, query_terms=['Fictional', 'Fictionalq'])['order'][-1], 13)
