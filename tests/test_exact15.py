import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.search import discover,results
from nicktrail.stages import phase
from nicktrail.pools import classify
from nicktrail.ranking import evaluate
class ExactFirstTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(self.tmp.cleanup);self.s=Store(str(Path(self.tmp.name)/'t.db'));self.addCleanup(self.s.db.close);self.p=self.s.project('Fictional')
 def test_exact_probes_and_all_aliases_precede_related_and_name_search(self):
  class C:count=0
  calls=[]
  def found(platform,term,client):
   calls.append((platform,term));client.count+=1;alias=term.split(':')[-1]
   return {'state':'found','matches':[{'url':'https://profiles.example/'+platform+'/'+term.replace(':','-'),'data':{'alias':alias},'evidence':[]}]}
  with patch('nicktrail.frontier.ordered_services',return_value=[{'id':'Keybase'},{'id':'HackerOne'}]),patch('nicktrail.search.lookup',side_effect=found),patch('nicktrail.searchflow.search_related',return_value={'state':'not_found','matches':[]}):
   id=discover(self.s,self.p,'seed',aliases=['other'],platforms=['GitHub','Free','StackOverflow'],related=True,criteria={'first_name':'Adalbert'},options={'candidates':1},client=C())
  tasks=self.s.rows('select * from search_tasks where search=?',(id,))
  self.assertTrue(all(t['state']!='pending' for t in tasks if phase(t['platform'],t['mode'])=='A_EXACT'))
  self.assertEqual(calls[:6],[('GitHub','seed'),('GitHub','other'),('Free','Keybase:seed'),('Free','Keybase:other'),('Free','HackerOne:seed'),('Free','HackerOne:other')])
  self.assertEqual(len([n for n in self.s.rows('select * from nodes') if n['state']=='found' and n['kind']=='page']),7)
 def test_candidate_pools_keep_all_exact_hits_and_quarantine_first_names(self):
  nodes=[]
  for i in range(10):
   id=self.s.apply_profile(self.p,'https://github.com/u'+str(i),{'alias':'seed' if i<5 else 'other'+str(i),'display':'Adalbert Other'});nodes.append(id)
  snap=self.s.snapshot(self.p);rank=evaluate(snap,{'first_name':'Adalbert'},['seed']);pools=classify(snap,rank,['seed'],{'first_name':'Adalbert'})
  self.assertTrue(all(pools[str(i)]['primary_visible'] for i in nodes[:5]))
  self.assertTrue(all(pools[str(i)]['pool']=='QUARANTINED_DISCOVERY_POOL' for i in nodes[5:]))
  self.assertTrue(all(pools[str(i)]['identity_evidence']=='INSUFFICIENT' for i in nodes))
 def test_exact_bluesky_filters_similar_handles(self):
  class C:count=0
  matches=[{'url':'https://bsky.app/profile/'+a,'data':{'alias':a},'evidence':[]} for a in ('seed.bsky.social','seed-extra.bsky.social')]
  with patch('nicktrail.search.lookup',return_value={'state':'found','matches':[m|{'enriched':True} for m in matches]}):id=discover(self.s,self.p,'seed',platforms=['Bluesky'],client=C())
  self.assertEqual(len(self.s.rows('select * from candidate_hints')),1)
 def test_found_profile_explanation_and_unknown_url(self):
  from nicktrail.diagnostics import explain
  id=self.s.apply_profile(self.p,'https://github.com/seed',{'alias':'seed'})
  self.assertEqual(explain(self.s,self.p,'https://github.com/seed')['code'],'PROFILE_FOUND_BUT_HIDDEN')
  self.assertEqual(explain(self.s,self.p,'https://github.com/seed',{})['code'],'PROFILE_FOUND')
  self.assertEqual(explain(self.s,self.p,'https://github.com/missed')['code'],'EXACT_CHECK_NOT_SCHEDULED')
 def test_private_golden_reports_missing_without_network(self):
  from nicktrail.golden import evaluate as golden
  self.s.apply_profile(self.p,'https://github.com/seed',{'alias':'seed'})
  result=golden(self.s,self.p,{'aliases':['seed'],'true_profiles':[{'url':'https://github.com/seed','expected_username':'seed'},{'url':'https://github.com/missed','expected_username':'missed'}]})
  self.assertEqual(result['found_known_true'],1);self.assertEqual(result['metrics']['automatic_coverage'],.5);self.assertEqual(len(result['missing']),1)

 def test_golden_labels_are_project_local_and_do_not_change_ownership(self):
  from nicktrail.golden import evaluate as golden
  known=self.s.apply_profile(self.p,'https://github.com/fictional-private',{'alias':'fictional-private'})
  other=self.s.project('Unrelated project')
  payload={'aliases':['fictional-private'],'true_profiles':['https://github.com/fictional-private']}
  self.assertEqual(golden(self.s,self.p,payload)['found_known_true'],1)
  self.assertEqual(golden(self.s,other,payload)['found_known_true'],0)
  self.assertEqual(self.s.node(known)['ownership'],'unknown')
