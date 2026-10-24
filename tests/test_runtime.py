import tempfile,json,unittest
from pathlib import Path
from nicktrail.storage import Store
from nicktrail.runtime import exclusive_runtime,recover
from nicktrail.search import schema,results
from nicktrail.branches import schema as branches_schema
class RuntimeTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory(dir=Path.cwd());self.path=Path(self.tmp.name)/'test.db';self.s=Store(self.path);self.p=self.s.project('Fixture')
 def tearDown(self):self.s.db.close();self.tmp.cleanup()
 def test_exclusive_lock_released_and_contenders_do_not_recover_jobs(self):
  with exclusive_runtime(self.path):
   with self.assertRaises(ValueError):
    with exclusive_runtime(self.path):self.fail('second lease acquired')
  with exclusive_runtime(self.path):pass
 def test_orphan_recovery_preserves_queue_decisions_and_evidence(self):
  schema(self.s);branches_schema(self.s);node=self.s.add(self.p,'https://github.com/fixture',confirmed=True)
  self.s.execute('insert into searches(project,status,options) values(?,?,?)',(self.p,'running','{}'))
  run=self.s.execute('insert into branch_runs(project,status,options) values(?,?,?)',(self.p,'running','{}')).lastrowid
  self.s.execute("insert into branch_nodes(run,root,node,depth,state) values(?,?,?,0,'searching')",(run,node,node))
  with exclusive_runtime(self.path):counts=recover(self.s)
  self.assertEqual(counts['searches'],1);self.assertEqual(counts['branch_runs'],1)
  self.assertEqual(self.s.rows('select status from branch_runs')[0]['status'],'paused');self.assertEqual(self.s.rows('select state from branch_nodes')[0]['state'],'pending')
  self.assertEqual(self.s.node(node)['ownership'],'mine')
  with exclusive_runtime(self.path):self.assertEqual(sum(recover(self.s).values()),0)
 def test_panel_history_window_does_not_delete_database_history(self):
  schema(self.s)
  for i in range(30):
   self.s.execute('insert into scans(project,status,options) values(?,?,?)',(self.p,'completed','{}'))
   self.s.execute('insert into searches(project,nickname,status,options) values(?,?,?,?)',(self.p,'fixture','completed','{}'))
  self.assertEqual(len(self.s.snapshot(self.p,scan_limit=5)['scans']),5);self.assertEqual(len(self.s.snapshot(self.p)['scans']),30)
  self.assertEqual(len(results(self.s,self.p,limit=10)),10);self.assertEqual(len(results(self.s,self.p)),30)

 def test_focused_history_is_not_lost_by_global_panel_window(self):
  from nicktrail.ranking import focus_results
  n=self.s.add(self.p,'https://github.com/fixture');self.s.set_focus(self.p,n)
  old=self.s.execute('insert into scans(project,status,options,visited) values(?,?,?,?)',(self.p,'completed',json.dumps({'_targets':[n]}),json.dumps([n]))).lastrowid
  for i in range(30):self.s.execute('insert into scans(project,status,options) values(?,?,?)',(self.p,'completed','{}'))
  view=focus_results(self.s.snapshot(self.p,scan_limit=5),self.s);self.assertEqual(view['scans'][0]['id'],old)
