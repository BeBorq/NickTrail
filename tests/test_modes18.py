import unittest,tempfile,json
from pathlib import Path
from nicktrail.storage import Store
from nicktrail.search import discover
from nicktrail.scanmodes import apply,policy
class Modes18Tests(unittest.TestCase):
 def test_named_scope_and_budgets_override_unbounded_caller_options(self):
  packet=apply({'scan_mode':'QUICK','platforms':['Extended'],'options':{'queries':999999},'auto_branches':True})
  self.assertEqual(packet['options']['queries'],40);self.assertNotIn('Extended',packet['platforms']);self.assertFalse(packet['auto_branches']);self.assertFalse(packet['auto_resume'])
  self.assertIn('Extended',policy('DEEP')['platforms']);self.assertEqual(policy('DEEP')['continuations'],5)
 def test_historical_requires_dedicated_one_source_operation(self):
  with self.assertRaises(ValueError):apply({'scan_mode':'HISTORICAL'})
  with self.assertRaises(ValueError):apply({'scan_mode':'UNKNOWN'})
 def test_mode_persists_and_resume_keeps_saved_budget_scope(self):
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
   s=Store(Path(folder)/'m.db');p=s.project('Synthetic')
   class C:count=0
   id=discover(s,p,'fictional',platforms=['Extended'],options={'queries':999999},client=C(),stopped=lambda:True,scan_mode='QUICK')
   before=s.rows('select * from search_tasks where search=?',(id,));saved=json.loads(s.rows('select options from searches where id=?',(id,))[0]['options'])
   self.assertEqual(saved['_scan_mode'],'QUICK');self.assertEqual(saved['queries'],40);self.assertNotIn('Extended',{t['platform'] for t in before})
   discover(s,p,resume=id,options={'queries':999999},client=C(),stopped=lambda:True)
   saved=json.loads(s.rows('select options from searches where id=?',(id,))[0]['options']);self.assertEqual(saved['queries'],40);self.assertEqual(saved['_scan_mode'],'QUICK')
   self.assertEqual(len(before),len(s.rows('select * from search_tasks where search=?',(id,))));s.db.close()

 def test_cheap_exact_api_precedes_html_catalog_without_weak_search_jump(self):
  from nicktrail.stages import next_task
  tasks=[{'platform':'Free','mode':'probe','ordinal':0},{'platform':'RubyGems','mode':'exact','ordinal':99},{'platform':'GitHub','mode':'related','ordinal':1}]
  self.assertEqual(next_task(tasks)['platform'],'RubyGems')
  tasks=tasks[:1]+tasks[2:];self.assertEqual(next_task(tasks)['platform'],'Free')

 def test_completeness_distinguishes_scope_budget_and_policy_before_http(self):
  from unittest.mock import patch
  from nicktrail.search import results
  from nicktrail.diagnostics import completeness
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
   s=Store(Path(folder)/'coverage.db');p=s.project('Synthetic')
   class C:count=0
   id=discover(s,p,'fictional',platforms=['RubyGems'],client=C(),stopped=lambda:True)
   s.execute("update search_tasks set state='blocked',detail='HTTP 429',requests=0 where search=?",(id,))
   s.execute("update searches set status='completed' where id=?",(id,));item=next(r for r in results(s,p) if r['run']['id']==id)
   report=completeness(item,s,s.snapshot(p));self.assertEqual(report['outcome_report']['rate_limited_tasks'],1)
   self.assertEqual(report['definitions']['known_definitions_with_http_attempts'],0)
   self.assertEqual(report['definitions']['automatic_verification_attempts'],1)
   self.assertGreater(report['definitions']['skipped_due_selected_mode_or_scope'],0)
   self.assertEqual(len(report['aliases']['exact_completed']),1);s.db.close()
