import copy,json,unittest
from nicktrail.graphsignals import analyze
from nicktrail.ranking import evaluate

def node(id,url,kind='profile',ownership='unknown',state='found'):
 return {'id':id,'url':url,'kind':kind,'platform':'GitHub' if 'github.com/' in url else 'X' if 'x.com/' in url else 'Strona','ownership':ownership,'state':state,'data':json.dumps({'alias':str(id)})}
def edge(id,source,target,relation='links',**extra):return {'id':id,'source':source,'target':target,'relation':relation,'current':1,'decision':'unknown','method':'parser','location':'bio','source_url':'https://fixture.example/'+str(source),'snippet':'Public fixture','fetched':'2026-01-01','context':'own'}|extra
def fixture():
 return {'nodes':[node(1,'https://github.com/reference'),node(2,'https://x.com/common',state='unsupported'),node(3,'https://github.com/old-name'),node(4,'https://github.com/exact')],'evidence':[edge(1,1,2)],'focus':[{'node':1}]}
class GraphTests(unittest.TestCase):
 def test_late_reverse_bridge_reorders_without_ownership_change(self):
  s=fixture();s['nodes'][3]['data']=json.dumps({'alias':'exact'})
  self.assertEqual(evaluate(s,query_terms=['exact'])['order'].index(4)<evaluate(s,query_terms=['exact'])['order'].index(3),True)
  s['evidence'].append(edge(2,3,2))
  r=evaluate(s,query_terms=['exact']);self.assertLess(r['order'].index(3),r['order'].index(4))
  path=r['nodes']['3']['graph_paths'][0];self.assertEqual(path['kind'],'shared_profile');self.assertEqual(path['path'],[1,2,3]);self.assertEqual(path['independent_sources'],2)
  self.assertEqual([e['id'] for e in path['edges']],[1,2]);self.assertFalse(path['identity_confirmed']);self.assertEqual(s['nodes'][2]['ownership'],'unknown')
 def test_manual_stale_rejected_quote_edges_do_not_connect(self):
  for changes in ({'method':'manual_observation','decision':'accepted'},{'current':0},{'decision':'rejected'},{'context':'quote'},{'relation':'mentions'},{'method':'import_rule'}):
   s=fixture();s['evidence'].append(edge(2,3,2,**changes));self.assertNotIn(3,analyze(s),changes)
 def test_rejected_or_failed_sources_remove_derived_path(self):
  for changes in ({'ownership':'not_mine'},{'state':'blocked'},{'state':'error'}):
   s=fixture();s['evidence'].append(edge(2,3,2));s['nodes'][2].update(changes);self.assertNotIn(3,analyze(s))
  s=fixture();s['evidence'].append(edge(2,3,2));s['nodes'][1]['ownership']='not_mine';self.assertNotIn(3,analyze(s))
 def test_public_email_and_role_contact_are_distinct(self):
  for address,expected in [('public-person@example.org',True),('support@example.org',False),('team@example.org',False)]:
   s=fixture();s['nodes'][1]=node(2,address,kind='email');s['evidence']=[edge(1,1,2,'public_contact_occurrence'),edge(2,3,2,'public_contact_occurrence')]
   paths=analyze(s);self.assertEqual(3 in paths,expected)
   if expected:self.assertEqual(paths[3][0]['kind'],'shared_public_email');self.assertIn('public_email',evaluate(s)['nodes']['3']['weights'])
 def test_generic_provider_home_and_popular_hub_do_not_bridge(self):
  s=fixture();s['nodes'][1]=node(2,'https://github.com',kind='page');s['evidence'].append(edge(2,3,2));self.assertNotIn(3,analyze(s))
  s=fixture();s['evidence'].append(edge(2,3,2))
  for i in range(10,20):s['nodes'].append(node(i,'https://github.com/fixture'+str(i)));s['evidence'].append(edge(i,i,2))
  self.assertNotIn(3,analyze(s))
 def test_shared_personal_site_and_depth_bound(self):
  s=fixture();s['nodes'][1]=node(2,'https://personal.example',kind='page');s['evidence'].append(edge(2,3,2));self.assertEqual(analyze(s)[3][0]['kind'],'shared_website')
  s['nodes'].extend([node(5,'https://github.com/five'),node(6,'https://github.com/six')]);s['evidence'] += [edge(3,3,5),edge(4,5,6)]
  self.assertIn(5,analyze(s));self.assertNotIn(6,analyze(s))
 def test_no_anchor_no_identity_cluster_and_mine_is_anchor(self):
  s=fixture();s['focus']=[];s['evidence'].append(edge(2,3,2));self.assertEqual(analyze(s),{})
  s['nodes'][0]['ownership']='mine';self.assertIn(3,analyze(s))
 def test_edge_duplicates_and_order_do_not_multiply_strength(self):
  s=fixture();s['evidence'].append(edge(2,3,2));before=analyze(s)[3][0]['strength']
  s['evidence']+=copy.deepcopy(s['evidence']);s['evidence'].reverse();self.assertEqual(analyze(s)[3][0]['strength'],before)

 def test_best_path_not_first_discovery_order_wins(self):
  s=fixture();s['nodes'].append(node(8,'person@example.org',kind='email'));s['evidence'] += [edge(2,3,2),edge(3,1,8,'public_contact_occurrence'),edge(4,3,8,'public_contact_occurrence')]
  self.assertEqual(analyze(s)[3][0]['kind'],'shared_public_email')
  s['evidence'].reverse();s['nodes'].reverse();self.assertEqual(analyze(s)[3][0]['kind'],'shared_public_email')

 def test_failed_anchor_does_not_keep_automatic_direct_score(self):
  s=fixture();s['nodes'][0]['state']='blocked'
  r=evaluate(s);self.assertNotIn('link',r['nodes']['2']['weights']);self.assertNotIn('reciprocal',r['nodes']['2']['weights'])

 def test_unrelated_incoming_link_is_not_a_strong_identity_path(self):
  s=fixture();s['evidence']=[edge(1,3,1)];s['nodes'][3]['data']=json.dumps({'alias':'exact'})
  r=evaluate(s,query_terms=['exact']);self.assertLess(r['order'].index(4),r['order'].index(3));self.assertIn('graph_inbound',r['nodes']['3']['weights'])

 def test_weak_incoming_reference_cannot_propagate_to_strangers(self):
  s=fixture();s['evidence']=[edge(1,3,1),edge(2,3,2)]
  self.assertIn(3,analyze(s));self.assertNotIn(2,analyze(s))

 def test_missing_exact_account_is_demoted_without_changing_ownership(self):
  s=fixture();s['focus']=[];s['evidence']=[];s['nodes'][0]['data']=json.dumps({'alias':'exact'});s['nodes'][0]['state']='not_found'
  r=evaluate(s,query_terms=['exact']);self.assertGreater(r['order'].index(1),r['order'].index(3));self.assertTrue(r['nodes']['1']['conflicts']);self.assertEqual(s['nodes'][0]['ownership'],'unknown')
 def test_shared_contact_is_orange_not_red_or_identity_confirmation(self):
  from nicktrail.presentation import labels
  s=fixture();s['nodes'][1]=node(2,'public-person@example.org',kind='email');s['evidence']=[edge(1,1,2,'public_contact_occurrence'),edge(2,3,2,'public_contact_occurrence')]
  self.assertEqual(labels(s)['3']['color'],'orange');self.assertEqual(s['nodes'][2]['ownership'],'unknown')

 def test_verified_graph_discoveries_surface_outside_initial_search_only(self):
  from nicktrail.ranking import promoted_candidates
  s=fixture();s['evidence'].append(edge(2,3,2));r=evaluate(s,query_terms=['exact'])
  self.assertIn(3,promoted_candidates(s,r,existing=[4]));self.assertNotIn(2,promoted_candidates(s,r,existing=[4]))
  s['nodes'][2]['ownership']='not_mine';r=evaluate(s);self.assertNotIn(3,promoted_candidates(s,r))

 def test_role_mailboxes_do_not_connect_people(self):
  for address in ('noreply@example.org','privacy@example.org','security@example.org','jobs@example.org'):
   s=fixture();s['nodes'][1]=node(2,address,kind='email');s['evidence']=[edge(1,1,2,'public_contact_occurrence'),edge(2,3,2,'public_contact_occurrence')]
   self.assertNotIn(3,analyze(s))
 def test_same_accepted_path_is_not_counted_as_two_graph_features(self):
  s=fixture();s['nodes'][1]=node(2,'https://github.com/intermediate');s['evidence']=[edge(1,1,2,decision='accepted'),edge(2,2,3,decision='accepted')]
  r=evaluate(s);self.assertIn('accepted_path',r['nodes']['3']['weights']);self.assertNotIn('graph_bridge',r['nodes']['3']['weights'])
  s['nodes'][1]['kind']='project';self.assertNotIn('accepted_path',evaluate(s)['nodes']['3']['weights'])
