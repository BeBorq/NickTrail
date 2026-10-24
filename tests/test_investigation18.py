import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.engine import record
from nicktrail.investigation import prepare
class Investigation18Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(self.tmp.cleanup);self.s=Store(Path(self.tmp.name)/'p.db');self.addCleanup(self.s.db.close);self.p=self.s.project('Synthetic')
  self.a=self.s.apply_profile(self.p,'https://github.com/fictional-root',{'alias':'fictional-root'});self.s.decide(self.a,'mine')
  self.b=self.s.apply_profile(self.p,'https://dev.to/fictional-b',{'alias':'fictional-b'})
  record(self.s,self.s.node(self.a),[{'url':self.s.node(self.b)['url'],'relation':'links','location':'bio','snippet':'Public profile link'}])
 def test_plan_is_bounded_and_readonly_with_existing_evidence(self):
  prepared=prepare(self.s,self.p);actions=prepared['plan']['actions'];self.assertTrue(actions);self.assertLessEqual(len(actions),8);self.assertEqual(actions[0]['node'],self.b)
  self.assertTrue(actions[0]['evidence_ids']);self.assertFalse(prepared['plan']['policy']['execute_automatically']);self.assertEqual(self.s.node(self.b)['ownership'],'unknown')
 def test_feedback_removes_reviewed_candidate_and_changes_plan(self):
  before=prepare(self.s,self.p);self.s.decide(self.b,'not_mine');after=prepare(self.s,self.p)
  self.assertNotEqual(before['fingerprint'],after['fingerprint']);self.assertFalse(any(a['node']==self.b for a in after['plan']['actions']))
 def test_first_name_only_pollution_does_not_fill_active_review(self):
  for i in range(50):self.s.apply_profile(self.p,'https://github.com/unrelated'+str(i),{'alias':'unrelated'+str(i),'display':'Common Firstname'})
  prepared=prepare(self.s,self.p);self.assertLessEqual(len(prepared['plan']['actions']),1)
