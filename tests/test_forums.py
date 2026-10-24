import json,unittest
from nicktrail.forums import lookup,read
from nicktrail.identity import identify
from nicktrail.providers import lookup as provider_lookup
class Fixture:
 def __init__(self,body,state='found'):self.body=body;self.state=state;self.calls=[]
 def get(self,url):self.calls.append(url);return {'state':self.state,'text':json.dumps(self.body),'detail':'fixture'}
class ForumTests(unittest.TestCase):
 def test_public_profile_and_bio_website_not_hidden_email(self):
  client=Fixture({'user':{'id':42,'username':'fictional','name':'Fictional Person','bio_raw':'My profile https://github.com/fictional','website':'personal.example','avatar_template':'/avatars/{size}.png','email':'not-a-public-field@example.org'}})
  result=lookup('PythonForum','fictional',client);self.assertEqual(result['state'],'found');self.assertEqual(client.calls,['https://discuss.python.org/u/fictional.json'])
  self.assertEqual({e.get('url') for e in result['evidence']},{'https://github.com/fictional','https://personal.example'})
  self.assertFalse(any('email' in e for e in result['evidence']));self.assertEqual(result['data']['avatar_url'],'https://discuss.python.org/avatars/64.png')
 def test_wrong_account_or_soft_error_is_not_found_profile(self):
  for body in ({'user':{'id':42,'username':'other'}},{'errors':['not found']},{'user':{'id':True,'username':'fictional'}}):
   self.assertEqual(lookup('PythonForum','fictional',Fixture(body))['state'],'partial')
 def test_access_blocks_are_preserved(self):
  result=lookup('BlenderForum','fictional',Fixture({},'blocked'));self.assertEqual(result['state'],'blocked');self.assertEqual(result['matches'],[])
 def test_identity_recognizes_profile_scope_only(self):
  n=identify('https://blenderartists.org/users/fictional');self.assertEqual(n['kind'],'profile');self.assertEqual(n['url'],'https://blenderartists.org/u/fictional')
  self.assertEqual(identify('https://discuss.python.org/t/topic')['kind'],'page')
 def test_provider_dispatches_without_paid_key(self):
  result=provider_lookup('PythonForum','fictional',Fixture({'user':{'id':42,'username':'fictional'}}));self.assertEqual(result['state'],'found')
 def test_redirect_cannot_relabel_another_forum_and_ids_keep_instance_scope(self):
  class Redirected(Fixture):
   def get(self,url):return super().get(url)|{'url':'https://other.example/u/fictional.json'}
  self.assertEqual(lookup('PythonForum','fictional',Redirected({'user':{'id':42,'username':'fictional'}}))['state'],'partial')
  first=lookup('PythonForum','fictional',Fixture({'user':{'id':42,'username':'fictional'}}))
  second=lookup('BlenderForum','fictional',Fixture({'user':{'id':42,'username':'fictional'}}))
  self.assertNotEqual(first['data']['id_scope'],second['data']['id_scope']);self.assertEqual(first['data']['public_engine'],'discourse')
