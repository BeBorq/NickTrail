import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.search import discover
from nicktrail.engine import scan
from nicktrail.servicecatalog import services
from nicktrail.providers import lookup,validate,describe
class ArchitectureTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory(dir=Path.cwd());self.s=Store(str(Path(self.tmp.name)/'test.db'));self.p=self.s.project('Fixture')
 def tearDown(self):self.s.db.close();self.tmp.cleanup()
 def test_resume_does_not_discard_rest_of_provider_page(self):
  class Client:count=0
  matches=[{'url':'https://github.com/fixture'+str(i),'data':{'alias':'fixture'+str(i),'stable_id':str(i+100)},'evidence':[]} for i in range(3)]
  def found(platform,term,client):client.count+=1;return {'state':'found','detail':'fixture','matches':copy.deepcopy(matches)}
  with patch('nicktrail.search.lookup',side_effect=found) as call:
   id=discover(self.s,self.p,'fixture',platforms=['StackOverflow'],options={'candidates':1},client=Client())
   self.assertEqual(self.s.rows('select offset from search_task_payloads')[0]['offset'],1)
   self.assertEqual(self.s.rows('select status from searches where id=?',(id,))[0]['status'],'limited')
   discover(self.s,self.p,resume=id,options={'candidates':3},client=Client())
   self.assertEqual(call.call_count,1)
  self.assertEqual(self.s.rows('select status from searches where id=?',(id,))[0]['status'],'completed')
  self.assertEqual(self.s.rows('select count(distinct node) n from candidate_hints where search=?',(id,))[0]['n'],3)
  self.assertEqual(self.s.rows('select * from search_task_payloads'),[])
 def test_structured_catalog_has_honest_validation_and_categories(self):
  rows=services();self.assertEqual(len(rows),100);self.assertGreater(len({s['category'] for s in rows}),8)
  self.assertTrue(all(s['validation']['coverage_claim']=='template_only_until_profile_evidence' for s in rows))
  self.assertEqual(sum(s['validation']['live_status']=='not_tested' for s in rows),97)
 def test_brave_absent_does_not_disable_free_provider(self):
  with patch.dict('os.environ',{},clear=True),patch('nicktrail.freeprofiles.lookup',return_value={'state':'partial','matches':[]}):
   self.assertEqual(lookup('Free','Keybase:fixture',None)['state'],'partial')
   self.assertEqual(lookup('Web','fixture',None)['state'],'unsupported')
   available={p['id']:p['available'] for p in describe()};self.assertTrue(available['Free']);self.assertFalse(available['Web'])
 def test_provider_contract_rejects_unsafe_or_malformed_matches(self):
  for result in ({'state':'certain'},{'state':'found','matches':'bad'},{'state':'found','matches':[{'url':'javascript:alert(1)','data':{}}]}):
   with self.assertRaises(ValueError):validate(result)
  with self.assertRaises(ValueError):lookup('unknown','fixture',None)
 def test_explicit_scan_notes_do_not_repeat_all_unrelated_candidates(self):
  for i in range(40):self.s.add(self.p,'https://example.org/unrelated'+str(i))
  id=self.s.add(self.p,'https://example.org/selected')
  class Client:
   count=0
   def get(self,url):self.count+=1;return {'state':'found','text':'<p>Fictional public profile biography with enough visible text to verify extraction without navigation links.</p>','url':url}
  scan_id=scan(self.s,self.p,targets=[id],client=Client())
  notes=json.loads(self.s.rows('select notes from scans where id=?',(scan_id,))[0]['notes'])
  self.assertLessEqual(len(notes),1)
