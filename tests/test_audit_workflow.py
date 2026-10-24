import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from nicktrail.storage import Store
from nicktrail.exposure import check,history
from nicktrail.planning import suggestions,words_queries
from nicktrail.search import discover,results
from nicktrail.workflow import search_and_verify

class PageFixture:
    def __init__(self):self.count=0;self.calls=[]
    def get(self,url,headers=None):
        self.count+=1;self.calls.append((url,headers));page=int(parse_qs(urlsplit(url).query).get('page',['1'])[0])
        if '/search/users?' in url:body={'total_count':23,'items':[{'id':page*10+i,'login':'fictional'+str(page*10+i)} for i in range(10 if page<3 else 3)]}
        elif '/user/' in url:
            id=int(urlsplit(url).path.split('/')[-1]);body={'id':id,'login':'fictional'+str(id),'blog':'https://example.org/me'}
        else:body={'id':1,'login':'fictional'}
        return {'state':'found','text':json.dumps(body)}

class AuditWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(dir=Path.cwd());self.store=Store(Path(self.folder.name)/'test.sqlite3');self.project=self.store.project('Fictional')
    def tearDown(self):self.store.db.close();self.folder.cleanup()
    def test_breach_metadata_whitelist_and_explicit_consent(self):
        class Client:
            def get(self,url,headers):
                self.url=url;self.headers=headers
                return {'state':'found','text':json.dumps([{'Name':'Fictional','Title':'Fictional incident','BreachDate':'2020-01-01','DataClasses':['Email addresses','Passwords'],'Password':'must not persist'}])}
        client=Client()
        with patch.dict('os.environ',{'NICKTRAIL_HIBP_KEY':'fixture-key'}):
            with self.assertRaises(ValueError):check(self.store,self.project,'self@example.org',False,client)
            result=check(self.store,self.project,'self@example.org',True,client)
        self.assertEqual(result['state'],'exposed');self.assertNotIn('must not persist',json.dumps(history(self.store,self.project)))
        self.assertIn('self%40example.org',client.url)
        self.assertEqual(client.headers,{'hibp-api-key':'fixture-key'})
        self.assertFalse(self.store.snapshot(self.project)['nodes'])
    def test_no_known_breach_does_not_mean_no_exposure(self):
        class Client:
            def get(self,*args,**kwargs):return {'state':'not_found','detail':'HTTP 404'}
        with patch.dict('os.environ',{'NICKTRAIL_HIBP_KEY':'fixture'}):
            result=check(self.store,self.project,'self@example.org',True,Client())
        self.assertEqual(result['state'],'no_known_exposure');self.assertIn('nie dowodzi',result['detail'])
    def test_plan_uses_confirmed_sources_without_promoting_target(self):
        source=self.store.apply_profile(self.project,'https://github.com/fictional',{'stable_id':'1','alias':'fictional','display':'Fictional Person'})
        target=self.store.add(self.project,'https://example.org/me',seed=False)
        self.store.evidence(self.project,source,target,'links','https://github.com/fictional','blog','https://example.org/me')
        self.assertFalse(suggestions(self.store,self.project))
        self.store.decide(source,'mine');plan=suggestions(self.store,self.project)
        self.assertEqual({v['kind'] for v in plan},{'alias','words','url'})
        self.assertEqual(self.store.node(target)['ownership'],'unknown')
    def test_independent_words_and_optional_location(self):
        q=words_queries({'first_name':'Fictional','last_name':'Person','location':'Test City','keywords':'photo, old-alias'})
        self.assertIn('Fictional Person',q);self.assertIn('Fictional Person Test City',q);self.assertIn('photo',q);self.assertIn('old-alias',q)
    def test_pagination_is_saved_and_limited_to_three_pages(self):
        client=PageFixture()
        run=discover(self.store,self.project,'fictional',platforms=['GitHub'],client=client,related=True,options={'candidates':50})
        tasks=results(self.store,self.project)[0]['tasks']
        self.assertEqual(sum('/search/users?' in url for url,_ in client.calls),3)
        self.assertTrue(any(t['mode']=='related|3' for t in tasks))
        self.assertEqual(results(self.store,self.project)[0]['run']['status'],'completed')
    def test_two_stage_reserves_budget_and_excludes_rejected(self):
        rejected=self.store.apply_profile(self.project,'https://github.com/fictional',{'stable_id':'1','alias':'fictional'})
        self.store.decide(rejected,'not_mine')
        with patch('nicktrail.workflow.scan',return_value=99) as scan:
            run=search_and_verify(self.store,self.project,'fictional',platforms=['GitHub'],options={'queries':12,'seconds':30},verify_top=3,client=PageFixture())
        self.assertTrue(scan.called)
        self.assertNotIn(rejected,scan.call_args.kwargs['targets'])
        self.assertEqual(scan.call_args.args[2]['queries'],3)
        row=self.store.rows('SELECT options FROM searches WHERE id=?',(run,))[0]
        self.assertIn('_verification',json.loads(row['options']))
    def test_real_two_stage_flow_records_reads_without_ownership_promotion(self):
        run=search_and_verify(self.store,self.project,'fictional',platforms=['GitHub'],options={'queries':12,'seconds':30},verify_top=3,client=PageFixture())
        row=self.store.rows('SELECT options FROM searches WHERE id=?',(run,))[0]
        verification=json.loads(row['options'])['_verification']
        self.assertIsNotNone(verification['scan'])
        observations=self.store.rows('SELECT * FROM observations WHERE scan=?',(verification['scan'],))
        self.assertEqual(len(observations),3)
        self.assertTrue(all(o['state']=='found' for o in observations))
        self.assertTrue(all(self.store.node(o['node'])['ownership']=='unknown' for o in observations))
    def test_pagination_resume_continues_saved_page_queue(self):
        client=PageFixture()
        run=discover(self.store,self.project,'fictional',platforms=['GitHub'],client=client,related=True,stopped=lambda:client.count>=2)
        self.assertEqual(results(self.store,self.project)[0]['run']['status'],'paused')
        next_client=PageFixture();discover(self.store,self.project,resume=run,client=next_client)
        self.assertEqual([parse_qs(urlsplit(url).query).get('page') for url,_ in next_client.calls],[['2'],['3']])
        self.assertEqual(len(next_client.calls),2)
