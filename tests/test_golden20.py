import tempfile,unittest
from pathlib import Path
from nicktrail.storage import Store
from nicktrail.golden import evaluate,normalize
class Golden20Tests(unittest.TestCase):
 def test_seed_bridge_classes_and_exact_name_hard_negative(self):
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
   s=Store(Path(tmp)/'test.db')
   try:
    case={'aliases':['fictional'],'true_profiles':[{'url':'https://github.com/fictional','expected_username':'fictional','discovery_class':'SEED_DISCOVERABLE'},{'url':'https://dev.to/other-alias','discovery_class':'BRIDGE_DISCOVERABLE'}],'false_profiles':[{'url':'https://gitlab.com/fictional','hard_negative_category':'EXACT_USERNAME_DIFFERENT_OWNER'}]}
    s.apply_profile(s.project('Fictional'),'https://github.com/fictional',{'alias':'fictional'})
    s.apply_profile(1,'https://gitlab.com/fictional',{'alias':'fictional'})
    r=evaluate(s,1,case);self.assertEqual(r['metrics']['seed_discoverable_recall'],1);self.assertEqual(r['metrics']['bridge_discoverable_recall'],0)
    self.assertEqual(r['metrics']['search_false_positive_rate'],1);self.assertIsNone(r['metrics']['identity_false_positive_rate']);self.assertEqual(r['metrics']['strong_graph_negative_rate'],0)
    self.assertEqual(r['hard_negative_metrics']['EXACT_USERNAME_DIFFERENT_OWNER']['retrieved'],1)
    case['identity_reference_url']='https://github.com/fictional';r=evaluate(s,1,case)
    self.assertEqual(r['metrics']['identity_false_positive_rate'],0);self.assertEqual(r['identity_evaluation']['negative_abstention_rate'],1)
    case['false_profiles'][0]['hard_negative_category']='invented'
    with self.assertRaises(ValueError):normalize(case)
   finally:s.db.close()
 def test_identity_metric_detects_false_explicit_bridge_not_just_search_visibility(self):
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
   s=Store(Path(tmp)/'test.db');p=s.project('Fictional')
   try:
    a=s.apply_profile(p,'https://github.com/fictional-root',{'alias':'fictional-root'});b=s.apply_profile(p,'https://gitlab.com/fictional-other',{'alias':'fictional-other'});hub=s.add(p,'https://shared.example/about',seed=False)
    for source in (a,b):s.evidence(p,source,hub,'claims_ownership',s.node(source)['url'],'sameAs','Fictional contradictory ownership declaration')
    case={'aliases':['fictional-root'],'identity_reference_url':s.node(a)['url'],'true_profiles':[s.node(a)['url']],'false_profiles':[{'url':s.node(b)['url'],'hard_negative_category':'SIMILAR_BIO'}]}
    r=evaluate(s,p,case);self.assertEqual(r['identity_evaluation']['evaluated_known_negatives'],1);self.assertEqual(r['metrics']['identity_false_positive_rate'],0);self.assertEqual(r['identity_evaluation']['negative_abstention_rate'],1)
    # Deliberately contradictory reciprocal declarations prove this evaluator can
    # still expose a false identity suggestion rather than always abstaining.
    for source,target in ((a,b),(b,a)):s.evidence(p,source,target,'claims_ownership',s.node(source)['url'],'sameAs','Fictional contradictory reciprocal declaration')
    self.assertEqual(evaluate(s,p,case)['metrics']['identity_false_positive_rate'],1)
    s.decide(b,'not_mine');self.assertEqual(evaluate(s,p,case)['metrics']['identity_false_positive_rate'],1)
   finally:s.db.close()
