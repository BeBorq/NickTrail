import json,unittest,tempfile,os
from pathlib import Path
from unittest.mock import patch
from nicktrail.ranking import evaluate
from nicktrail.context import SITES,plan
from nicktrail.catalog import queries,lookup
from nicktrail.storage import Store
from nicktrail.search import discover
from nicktrail.network import Limit
from nicktrail.forge import read

class ExpandedTests(unittest.TestCase):
 def test_exact_alias_with_most_distinct_links_first(self):
  nodes=[{'id':i,'kind':'profile','ownership':'unknown','state':'found','data':json.dumps({'alias':'same' if i in (1,5) else 'other'}),'url':'https://example.org/'+str(i)} for i in range(1,9)]
  edges=[{'source':5,'target':i,'current':1,'decision':'unknown','relation':'links','method':'parser'} for i in (6,7,8)]
  edges += [dict(edges[0]) for _ in range(10)]
  s={'nodes':nodes,'evidence':edges,'focus':[]}
  r=evaluate(s,query_terms=['same'])
  self.assertEqual(r['order'][0],5);self.assertEqual(r['nodes']['5']['link_count'],3)
  self.assertIsNone(r['nodes']['5']['score'])
  for e in edges:e['decision']='rejected'
  self.assertEqual(evaluate(s,query_terms=['same'])['nodes']['5']['link_count'],0)
 def test_unrelated_link_farm_does_not_outrank_exact_name(self):
  nodes=[{'id':i,'kind':'profile','ownership':'unknown','data':json.dumps({'alias':'exact' if i==1 else 'other'})} for i in range(1,9)]
  edges=[{'source':2,'target':i,'current':1,'decision':'unknown','relation':'links'} for i in range(3,9)]
  self.assertEqual(evaluate({'nodes':nodes,'evidence':edges,'focus':[]},query_terms=['exact'])['order'][0],1)
 def test_catalog_unique_and_no_birth_date(self):
  self.assertEqual(len(SITES),180);self.assertEqual(len(set(SITES)),180)
  q=queries(['fictional','old-fictional'],{'birth_date':'2000-01-01'})
  self.assertEqual(len(q),360);self.assertNotIn('2000-01-01',str(q));self.assertEqual(len(plan('fictional',{})),180)
 def test_catalog_filters_other_hosts(self):
  with patch.dict(os.environ,{'NICKTRAIL_BRAVE_KEY':'fake'}),patch('nicktrail.websearch.lookup',return_value={'state':'found','matches':[{'url':'https://github.com/a'},{'url':'https://github.com.evil.example/a'},{'url':'https://gist.github.com/a'}]}):
   self.assertEqual(len(lookup('site:github.com "fictional"',None)['matches']),2)
 def test_catalog_resumes_pending_tasks_and_stays_unverified(self):
  class Fixture:
   count=0
   def get(self,url,headers=None):
    if self.count>=2:raise Limit()
    self.count+=1
    return {'state':'found','text':json.dumps({'web':{'results':[{'url':'https://github.com/fictional'}]}})}
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as d,patch.dict(os.environ,{'NICKTRAIL_BRAVE_KEY':'fake'}):
   store=Store(str(Path(d)/'test.db'));p=store.project('Fixture')
   id=discover(store,p,'fictional',platforms=['Catalog'],client=Fixture())
   self.assertEqual(store.rows('select status from searches where id=?',(id,))[0]['status'],'limited')
   self.assertEqual(store.rows('select count(*) n from search_tasks where search=? and state="pending"',(id,))[0]['n'],178)
   target=store.rows('select * from nodes where url=?',('https://github.com/fictional',))[0]
   self.assertEqual(target['state'],'unverified')
   discover(store,p,resume=id,client=Fixture())
   self.assertEqual(store.rows('select count(*) n from search_tasks where search=? and state="pending"',(id,))[0]['n'],176)
   store.db.close()
 def test_forge_strict_profile_and_links(self):
  class Fixture:
   def get(self,url):return {'state':'found','text':json.dumps({'id':12,'login':'fictional','website':'example.org','description':'My profile https://github.com/fictional'})}
  r=read({'platform':'Codeberg','kind':'profile','url':'https://codeberg.org/fictional'},Fixture())
  self.assertEqual(r['data']['stable_id'],'12');self.assertEqual(len(r['evidence']),2)
  with self.assertRaises(ValueError):read({'platform':'Codeberg','kind':'profile','url':'https://codeberg.org/someone'},Fixture())

 def test_full_name_and_public_links_beat_unrelated_exact_nickname(self):
  nodes=[{'id':i,'kind':'profile','ownership':'unknown','data':json.dumps({'alias':'same' if i==1 else 'different','display':'Anna Fictional' if i==5 else ''})} for i in (1,5,6)]
  s={'nodes':nodes,'focus':[],'evidence':[{'source':5,'target':6,'current':1,'decision':'unknown','relation':'links'}]}
  r=evaluate(s,{'first_name':'Anna','last_name':'Fictional'},['same'])
  self.assertEqual(r['order'][0],5);self.assertEqual(r['nodes']['5']['priority'],4)
