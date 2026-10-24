import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.exposure import check
from nicktrail.exposureproviders import HIBP

class Exposure20Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=Path.cwd());self.addCleanup(self.tmp.cleanup)
  self.s=Store(Path(self.tmp.name)/'private.db');self.addCleanup(self.s.db.close);self.p=self.s.project('Fictional')
 def client(self,response):
  class C:
   calls=0
   def get(c,*args,**kwargs):c.calls+=1;return response
  return C()
 def test_consent_cache_metadata_and_no_identity(self):
  c=self.client({'state':'found','text':json.dumps([{'Name':'Fictional','DataClasses':['Usernames'],'Password':'secret','Username':'not-an-alias','Records':['secret']}])})
  with patch.dict('os.environ',{'NICKTRAIL_HIBP_KEY':'test'}):
   with self.assertRaises(ValueError):check(self.s,self.p,'self@example.org',False,c)
   a=check(self.s,self.p,'self@example.org',True,c);b=check(self.s,self.p,'self@example.org',True,c)
  self.assertEqual(c.calls,1);self.assertFalse(a['cached']);self.assertTrue(b['cached']);self.assertFalse(self.s.snapshot(self.p)['nodes'])
  cached=self.s.rows('SELECT * FROM exposure_provider_cache');self.assertNotIn('self@example.org',json.dumps(cached));self.assertNotIn('secret',json.dumps(cached));self.assertNotIn('not-an-alias',json.dumps(cached))
  self.assertEqual(len(self.s.rows('SELECT * FROM exposure_consents')),2)
  from nicktrail.exposure import history
  rows=history(self.s,self.p);self.assertEqual(rows[0]['provider_checked'],rows[1]['provider_checked']);self.assertEqual(rows[0]['cached'],1);self.assertEqual(rows[1]['cached'],0)
 def test_capabilities_are_local_and_key_scoped(self):
  c=self.client({'state':'found','text':json.dumps({'SubscriptionName':'Fictional','Rpm':10,'Secret':'discard'})})
  with patch.dict('os.environ',{'NICKTRAIL_HIBP_KEY':'first'}):
   p=HIBP(self.s,c);self.assertEqual(p.capabilities()['state'],'CONFIGURED');self.assertEqual(c.calls,0);self.assertEqual(p.health()['state'],'CONTROL_RESPONSE_TESTED');self.assertEqual(p.capabilities()['state'],'CONFIGURED')
  with patch.dict('os.environ',{'NICKTRAIL_HIBP_KEY':'second'}):self.assertEqual(p.capabilities()['state'],'CONFIGURED')
  self.assertEqual(c.calls,1)
 def test_error_is_never_absence(self):
  for code,state in [(401,'AUTH_FAILED'),(402,'SUBSCRIPTION_REQUIRED'),(403,'ACCESS_DENIED'),(429,'RATE_LIMITED'),(500,'PARTIAL')]:
   c=self.client({'state':'blocked','detail':'HTTP '+str(code)})
   with patch.dict('os.environ',{'NICKTRAIL_HIBP_KEY':str(code)}):self.assertEqual(check(self.s,self.p,'self@example.org',True,c)['state'],state)
 def test_public_catalog_needs_no_key_or_identifier_and_has_no_raw_records(self):
  c=self.client({'state':'found','text':'[{"Name":"Fictional","DataClasses":["Usernames"],"Description":"<p>Public incident</p><script>discard</script>","PwnCount":12}]'})
  with patch.dict('os.environ',{'NICKTRAIL_HIBP_KEY':''}):
   p=HIBP(self.s,c);r=p.list_incidents();self.assertEqual(r['state'],'CONTROL_RESPONSE_TESTED');self.assertEqual(p.capabilities()['EMAIL_BREACH_LOOKUP'],'API_KEY_REQUIRED')
   with self.assertRaises(ValueError):p.check_identifier('self@example.org')
  self.assertEqual(r['incidents'][0]['Description'],'Public incident');self.assertEqual(c.calls,1)
 def test_cache_expiry_rechecks_identifier(self):
  c=self.client({'state':'not_found'})
  with patch.dict('os.environ',{'NICKTRAIL_HIBP_KEY':'test'}):
   check(self.s,self.p,'self@example.org',True,c);self.s.execute('UPDATE exposure_provider_cache SET expires=0');check(self.s,self.p,'self@example.org',True,c)
  self.assertEqual(c.calls,2)
 def test_project_deletion_removes_its_private_cache_and_consent(self):
  c=self.client({'state':'not_found'})
  with patch.dict('os.environ',{'NICKTRAIL_HIBP_KEY':'test'}):check(self.s,self.p,'self@example.org',True,c)
  self.s.execute('DELETE FROM projects WHERE id=?',(self.p,))
  self.assertFalse(self.s.rows('SELECT * FROM exposure_consents'));self.assertFalse(self.s.rows("SELECT * FROM exposure_provider_cache WHERE scope='account'"));self.assertFalse(self.s.rows('SELECT * FROM exposure_cache_projects'))
 def test_network_failure_and_existing_cooldown_are_not_absence(self):
  class C:
   def get(self,*args,**kwargs):raise OSError('fictional connection failure')
  with patch.dict('os.environ',{'NICKTRAIL_HIBP_KEY':'failure'}):self.assertEqual(check(self.s,self.p,'self@example.org',True,C())['state'],'PARTIAL')
  c=self.client({'state':'blocked','detail':'Przerwa zalecona przez API'})
  with patch.dict('os.environ',{'NICKTRAIL_HIBP_KEY':'cooldown'}):self.assertEqual(check(self.s,self.p,'self@example.org',True,c)['state'],'RATE_LIMITED')
 def test_malformed_provider_payload_is_partial_cached_and_never_retained_raw(self):
  c=self.client({'state':'found','text':'{"secret_records":"must-not-persist"}'})
  with patch.dict('os.environ',{'NICKTRAIL_HIBP_KEY':'fixture'}):
   self.assertEqual(check(self.s,self.p,'self@example.org',True,c)['state'],'PARTIAL');self.assertEqual(check(self.s,self.p,'self@example.org',True,c)['state'],'PARTIAL')
  self.assertEqual(c.calls,1);self.assertNotIn('must-not-persist',json.dumps(self.s.rows('SELECT * FROM exposure_provider_cache')))
