import json,unittest
from nicktrail.native17 import lookup_platform,read,SITES
from nicktrail.identity import identify
from nicktrail.providers import REGISTRY

class Native17Tests(unittest.TestCase):
 def fixtures(self):return {
  'RubyGems':{'handle':'synthetic','id':123,'email':'fixture@synthetic.example'},
  'HuggingFace':{'user':'synthetic','_id':'a'*24,'type':'user','details':'https://github.com/synthetic','fullname':'Synthetic'},
  'CratesIO':{'user':{'login':'synthetic','id':456,'name':'Synthetic','url':'https://github.com/synthetic'}},
  'Speedrun':{'data':{'id':'abcd1234','names':{'international':'synthetic'},'twitter':{'uri':'https://x.com/synthetic'}}}}
 def client(self,body=None,state='found'):
  class Client:
   def get(self,url):return {'state':state,'text':json.dumps(body),'url':url}
  return Client()
 def test_exact_public_profiles_extract_declared_links_and_stable_ids(self):
  for site,body in self.fixtures().items():
   with self.subTest(site=site):
    result=lookup_platform(site,'synthetic',self.client(body));self.assertEqual(result['state'],'found');match=result['matches'][0]
    self.assertEqual(identify(match['url'])['platform'],site);self.assertEqual(identify(match['url'])['kind'],'profile')
    self.assertTrue(match['data']['stable_id']);self.assertTrue(match['evidence']);self.assertNotIn('ownership',match['data'])
    self.assertIn(site,REGISTRY)
 def test_mismatched_alias_never_found(self):
  for site,body in self.fixtures().items():
   self.assertEqual(lookup_platform(site,'different',self.client(body))['state'],'partial')
 def test_missing_stable_id_and_malformed_objects_not_found(self):
  for site in SITES:
   self.assertEqual(lookup_platform(site,'synthetic',self.client({}))['state'],'partial')
   self.assertEqual(lookup_platform(site,'synthetic',self.client([]))['state'],'partial')
 def test_network_absence_and_block_are_not_success(self):
  for site in SITES:
   for state in ('not_found','blocked','error'):
    result=lookup_platform(site,'synthetic',self.client(state=state));self.assertEqual(result['state'],state);self.assertFalse(result['matches'])
 def test_org_is_not_person_and_avatar_is_not_link_evidence(self):
  body={'user':'synthetic','_id':'a'*24,'type':'org','avatarUrl':'https://github.com/other'}
  self.assertEqual(lookup_platform('HuggingFace','synthetic',self.client(body))['state'],'partial')
  body['type']='user';self.assertFalse(lookup_platform('HuggingFace','synthetic',self.client(body))['matches'][0]['evidence'])
 def test_no_inferred_github_link_from_crates_login(self):
  body={'user':{'login':'synthetic','id':1}}
  self.assertFalse(lookup_platform('CratesIO','synthetic',self.client(body))['matches'][0]['evidence'])
 def test_read_refuses_nonprofile_without_http(self):
  class NoHTTP:
   def get(self,url):raise AssertionError('must not request')
  self.assertEqual(read({'platform':'HuggingFace','kind':'page','url':'https://huggingface.co/docs'},NoHTTP())['state'],'unsupported')

 def test_api_redirect_to_unrelated_host_is_not_accepted(self):
  class Client:
   def get(self,url):return {'state':'found','url':'https://unrelated.example/profile','text':json.dumps({'handle':'synthetic','id':1})}
  result=lookup_platform('RubyGems','synthetic',Client())
  self.assertEqual(result['state'],'partial');self.assertIn('REDIRECT_MISMATCH',result['detail'])
