import json,unittest
from nicktrail.publicengines import lookup
class Flarum20Tests(unittest.TestCase):
 def client(self,body,url=None):
  class C:
   def get(c,endpoint):return {'state':'found','text':json.dumps(body),'url':url or endpoint}
  return C()
 def user(self,alias='fictional',slug='1-fictional'):
  return {'type':'users','id':'1','attributes':{'username':alias,'slug':slug,'displayName':'Fictional','bio':'https://example.org/about'}}
 def test_same_id_on_two_instances_has_distinct_scope(self):
  for host in ('forum-a.example','forum-b.example'):
   r=lookup('flarum',host,'fictional',self.client({'data':[self.user()]}));self.assertEqual(r['state'],'found');self.assertEqual(r['matches'][0]['data']['id_scope'],host);self.assertEqual(r['matches'][0]['url'],'https://'+host+'/u/1-fictional')
 def test_empty_or_fuzzy_directory_never_proves_absence(self):
  for rows in ([],[self.user('fictional-other')],[self.user(),self.user()]):
   r=lookup('flarum','forum.example','fictional',self.client({'data':rows}));self.assertEqual(r['state'],'partial');self.assertFalse(r['matches'])
 def test_foreign_or_downgrade_response_and_unsafe_slug_rejected(self):
  for url in ('https://other.example/api/users','http://forum.example/api/users'):
   self.assertEqual(lookup('flarum','forum.example','fictional',self.client({'data':[self.user()]},url))['state'],'partial')
  self.assertEqual(lookup('flarum','forum.example','fictional',self.client({'data':[self.user(slug='../admin')]}))['state'],'partial')
