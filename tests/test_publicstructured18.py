import json,unittest
from nicktrail.publicprofile import read
class PublicStructured18Tests(unittest.TestCase):
 url='https://fictional.example/about'
 def read(self,person,visible=''):
  html='<script type="application/ld+json">'+json.dumps(person)+'</script>'+visible
  class Client:
   def profile_get(self,url):return {'state':'found','text':html}
  return read({'url':self.url,'platform':'Strona'},Client())
 def test_matched_person_description_links_and_fields_without_js(self):
  person={'@type':'Person','url':self.url,'name':'Fictional Person','description':'Public projects at https://codeberg.org/fictional','image':{'url':'https://images.example/avatar.png'},'birthDate':'1990-02-03'}
  result=self.read(person)
  self.assertEqual(result['state'],'found');self.assertEqual(result['data']['declared_birth_date'],'1990-02-03');self.assertIn('avatar_url',result['data'])
  self.assertTrue(any('codeberg.org/fictional' in str(e) for e in result['evidence']))
 def test_unrelated_person_organization_and_challenge_are_not_profile(self):
  for person in ({'@type':'Person','url':'https://other.example/person','description':'https://codeberg.org/other'}, {'@type':'Organization','url':self.url,'description':'https://codeberg.org/company'}):
   self.assertEqual(self.read(person)['state'],'blocked')
  self.assertEqual(self.read({'@type':'Person','url':self.url},'Verify you are human')['state'],'blocked')
 def test_profilepage_association_and_invalid_birth_date(self):
  result=self.read({'@type':'ProfilePage','url':self.url,'mainEntity':{'@type':'Person','name':'Fictional','birthDate':'1990-02-31','description':'https://github.com/fictional'}})
  self.assertEqual(result['state'],'found');self.assertNotIn('declared_birth_date',result['data']);self.assertTrue(result['evidence'])
