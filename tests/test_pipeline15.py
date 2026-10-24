import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store,now
from nicktrail.search import schema
from nicktrail.pipeline import run
class PipelineTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(self.tmp.cleanup);self.s=Store(str(Path(self.tmp.name)/'p.db'));self.addCleanup(self.s.db.close);self.p=self.s.project('Fixture');schema(self.s)
  from nicktrail.branches import schema as bs
  bs(self.s)
  self.node=self.s.apply_profile(self.p,'https://github.com/fictional',{'alias':'fictional'})
  self.search=self.s.execute('insert into searches(project,status,options,requests) values(?,?,?,0)',(self.p,'stage_ready',json.dumps({'_terms':['fictional']}))).lastrowid
  self.s.execute('insert into search_tasks(search,platform,term,mode,state,nodes) values(?,?,?,?,?,?)',(self.search,'GitHub','fictional','exact','found',json.dumps([self.node])))
 def test_resumes_same_tree_before_weak_tasks(self):
  events=[]
  def discover(*a,**kw):
   events.append('exact' if kw.get('stop_after_exact') else 'weak');return self.search
  def explore(*a,**kw):
   if kw.get('resume'):
    events.append('resume_tree');self.s.execute("update branch_runs set status='completed' where id=?",(kw['resume'],));return kw['resume']
   events.append('tree');return self.s.execute('insert into branch_runs(project,status,options) values(?,?,?)',(self.p,'paused','{}')).lastrowid
  with patch('nicktrail.search.discover',side_effect=discover),patch('nicktrail.branches.explore',side_effect=explore):
   run(self.s,self.p,resume=self.search,auto_resume=False)
   self.assertEqual(events,['exact','tree'])
   self.assertEqual(self.s.rows('select status from searches')[0]['status'],'stage_ready')
   run(self.s,self.p,resume=self.search,auto_resume=False)
  self.assertEqual(events,['exact','tree','exact','resume_tree','weak'])
  self.assertEqual(len(self.s.rows('select * from branch_runs')),1)
 def test_pending_exact_check_prevents_tree_and_weak_search(self):
  self.s.execute("update search_tasks set state='pending'")
  with patch('nicktrail.search.discover',return_value=self.search),patch('nicktrail.branches.explore') as tree:
   run(self.s,self.p,resume=self.search,auto_resume=False);tree.assert_not_called()
 def test_unverified_imported_definition_is_not_root(self):
  self.s.execute("update nodes set state='unverified'")
  with patch('nicktrail.search.discover',return_value=self.search),patch('nicktrail.branches.explore') as tree:
   run(self.s,self.p,resume=self.search,auto_resume=False);tree.assert_not_called()

 def test_interruption_after_branch_creation_reuses_origin_on_resume(self):
  from nicktrail.branches import explore as real_explore
  execute=self.s.execute;failed=[False]
  def interrupted(sql,args=()):
   if sql.startswith('UPDATE searches SET options='):
    plan=json.loads(args[0]).get('_pipeline',{})
    if plan.get('current') and not failed[0]:
     failed[0]=True;raise RuntimeError('simulated checkpoint interruption')
   return execute(sql,args)
  class NoHTTP:count=0
  # Pipeline passes the options positionally; use an explicit compatible wrapper.
  def safe_explore(store,project,roots=None,options=None,**kwargs):
   return real_explore(store,project,roots,{'queries':0},client=NoHTTP(),**kwargs)
  with patch('nicktrail.search.discover',return_value=self.search),patch('nicktrail.branches.explore',side_effect=safe_explore),patch.object(self.s,'execute',side_effect=interrupted):
   with self.assertRaises(RuntimeError):run(self.s,self.p,resume=self.search,auto_resume=False)
   self.assertEqual(len(self.s.rows('select * from branch_runs')),1)
   run(self.s,self.p,resume=self.search,auto_resume=False)
  self.assertEqual(len(self.s.rows('select * from branch_runs')),1)
  plan=json.loads(self.s.rows('select options from searches where id=?',(self.search,))[0]['options'])['_pipeline']
  self.assertEqual(plan['current'],self.s.rows('select id from branch_runs')[0]['id'])
