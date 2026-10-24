import json,unittest,tempfile
from pathlib import Path
from nicktrail.freeprofiles import lookup,TEMPLATES
from nicktrail.search import discover
from nicktrail.storage import Store
from nicktrail.network import Limit
class Fixture:
 def __init__(self,text,url=None):self.text=text;self.url=url;self.count=0
 def get(self,url):
  self.count+=1
  return {'state':'found','text':self.text,'url':self.url or url}
class FreeTests(unittest.TestCase):
 def test_count(self):self.assertEqual(len(TEMPLATES),100)
 def test_http200_alone_does_not_invent_profile(self):
  r=lookup('Keybase:fictional',Fixture('<title>Welcome</title><p>fictional</p>'))
  self.assertEqual(r['state'],'partial');self.assertFalse(r['matches'])
 def test_soft404_and_redirect(self):
  self.assertEqual(lookup('Keybase:fictional',Fixture('<title>User not found</title>'))['state'],'not_found')
  self.assertEqual(lookup('Keybase:fictional',Fixture('<title>fictional</title>','https://keybase.io/login'))['state'],'partial')
 def test_captcha_is_not_absence(self):self.assertEqual(lookup('Keybase:fictional',Fixture('<p>Verify you are human</p>'))['state'],'blocked')
 def test_person_metadata_and_links(self):
  text='<script type="application/ld+json">'+json.dumps({'@type':'Person','url':'https://keybase.io/fictional','name':'Fictional','sameAs':['https://github.com/fictional']})+'</script>'
  r=lookup('Keybase:fictional',Fixture(text));self.assertEqual(r['state'],'found');self.assertEqual(len(r['matches'][0]['evidence']),1)
 def test_wrong_person_metadata_rejected(self):
  text='<script type="application/ld+json">'+json.dumps({'@type':'Person','url':'https://keybase.io/another'})+'</script>'
  self.assertEqual(lookup('Keybase:fictional',Fixture(text))['state'],'partial')
 def test_explicit_og_profile(self):
  text='<title>fictional profile</title><meta property="og:type" content="profile"><link rel="canonical" href="https://keybase.io/fictional">'
  self.assertEqual(lookup('Keybase:fictional',Fixture(text))['state'],'found')
 def test_no_key_queue_and_resume(self):
  class Budget(Fixture):
   def get(self,url):
    if self.count>=2:raise Limit()
    return super().get(url)
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
   s=Store(str(Path(d)/'fixture.db'));p=s.project('Fixture')
   id=discover(s,p,'fictional',platforms=['Free'],client=Budget('<title>Welcome</title>'))
   self.assertEqual(s.rows('select status from searches where id=?',(id,))[0]['status'],'limited')
   self.assertEqual(s.rows('select count(*) n from search_tasks where search=? and state="pending"',(id,))[0]['n'],98)
   discover(s,p,resume=id,client=Budget('<title>Welcome</title>'))
   self.assertEqual(s.rows('select count(*) n from search_tasks where search=? and state="pending"',(id,))[0]['n'],96)
   self.assertFalse(any(n['state']=='found' for n in s.snapshot(p)['nodes']));s.db.close()
