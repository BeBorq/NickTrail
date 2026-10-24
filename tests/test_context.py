import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote
from nicktrail.context import criteria, terms, plan, compare, SITES
from nicktrail.storage import Store
from nicktrail.search import discover, results
from nicktrail.websearch import lookup


class Fixture:
    def __init__(self): self.count=0;self.calls=[]
    def get(self,url,headers=None):
        self.count+=1;self.calls.append((unquote(url),headers))
        if 'brave.com' in url:
            body={'web':{'results':[{'url':'https://example.com/fictional','title':'Fictional','description':'Test'},{'url':'javascript:alert(1)'},{'url':'https://example.com/other'}]}}
        else:body={'items':[{'id':123,'login':'different-nickname','name':'Żaneta Fikcyjna'}]}
        return {'state':'found','text':json.dumps(body)}


class ContextTests(unittest.TestCase):
    def test_unicode_and_birth_date_validation(self):
        self.assertEqual(terms({'first_name':'Żaneta','last_name':'Fikcyjna','location':'Łódź'}),['Żaneta Fikcyjna','Żaneta Fikcyjna Łódź'])
        for bad in ({'birth_date':'2023-02-29'},{'birth_date':'2999-01-01'},{'keywords':'a\nb'},{'known_urls':['file:///secret']},{'unknown':'x'}):
            with self.assertRaises(ValueError):criteria(bad)
        self.assertEqual(criteria({'birth_date':'2000-02-29'})['birth_date'],'2000-02-29')

    def test_no_birth_date_in_remote_plan(self):
        queries=plan('fictional',{'first_name':'Żaneta','birth_date':'2000-02-29'})
        self.assertGreaterEqual(len(SITES),50)
        self.assertEqual(len(queries),len(set(SITES)))
        self.assertNotIn('2000',json.dumps(queries))
        self.assertTrue(all(q['url'].startswith('https://www.google.com/search?') for q in queries))

    def test_birth_date_never_uses_age_or_creation_date(self):
        c={'birth_date':'2000-02-29','first_name':'Żaneta'}
        self.assertEqual(compare({'created_at':'2000-02-29','age':26},c),[])
        self.assertEqual(compare({'display':'Żaneta','declared_birth_date':'2000-02-29'},c),['first_name','birth_date'])
        self.assertEqual(compare({'display':'Joanna','declared_location':'Yorktown'},{'first_name':'Ann','location':'York'}),[])

    def test_context_search_and_resume_preserve_criteria(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            store=Store(Path(folder)/'test.sqlite3')
            try:
                project=store.project('Fictional');client=Fixture()
                run=discover(store,project,'fictional',platforms=['GitHub'],client=client,criteria={'first_name':'Żaneta','last_name':'Fikcyjna','known_urls':['https://example.org/me'],'birth_date':'2000-02-29'},stopped=lambda:True)
                self.assertEqual(client.count,0)
                discover(store,project,resume=run,client=client)
                calls=str(client.calls)
                self.assertIn('Żaneta Fikcyjna type:user',calls)
                self.assertNotIn('2000-02-29',calls)
                self.assertTrue(any(n['url']=='https://example.org/me' and n['ownership']=='unknown' for n in store.snapshot(project)['nodes']))
                self.assertEqual(results(store,project)[0]['run']['status'],'completed')
            finally:store.db.close()

    def test_brave_key_and_unverified_leads(self):
        with patch.dict('os.environ',{},clear=True):self.assertEqual(lookup('fictional',Fixture())['state'],'unsupported')
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder,patch.dict('os.environ',{'NICKTRAIL_BRAVE_KEY':'fixture-secret'}):
            store=Store(Path(folder)/'test.sqlite3')
            try:
                project=store.project('Fictional');client=Fixture()
                discover(store,project,'fictional',platforms=['Web'],client=client)
                nodes=[n for n in store.snapshot(project)['nodes'] if n['kind']!='alias']
                self.assertEqual(len(nodes),2)
                self.assertTrue(all(n['state']=='unverified' and n['ownership']=='unknown' for n in nodes))
                self.assertFalse(store.snapshot(project)['evidence'])
                self.assertEqual(client.calls[0][1],{'X-Subscription-Token':'fixture-secret'})
            finally:store.db.close()

    def test_name_only_does_not_make_fake_exact_nickname(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            store=Store(Path(folder)/'test.sqlite3')
            try:
                project=store.project('Fictional');client=Fixture()
                discover(store,project,None,platforms=['GitHub','DEV'],client=client,criteria={'first_name':'Żaneta'})
                result=results(store,project)[0]
                self.assertEqual(len(client.calls),1)
                self.assertTrue(all(t['mode']=='context' for t in result['tasks']))
                self.assertEqual(next(s for s in result['sources'] if s['platform']=='DEV')['state'],'unsupported')
                self.assertTrue(any('first_name' in v for v in result['context_matches'].values()))
            finally:store.db.close()

    def test_index_refresh_preserves_verified_state_and_display(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder,patch.dict('os.environ',{'NICKTRAIL_BRAVE_KEY':'fixture-secret'}):
            store=Store(Path(folder)/'test.sqlite3')
            try:
                project=store.project('Fictional')
                node=store.apply_profile(project,'https://example.com/fictional',{'display':'Public source name'})
                discover(store,project,'fictional',platforms=['Web'],client=Fixture())
                self.assertEqual(store.node(node)['state'],'found')
                self.assertEqual(json.loads(store.node(node)['data'])['display'],'Public source name')
            finally:store.db.close()


if __name__=='__main__':unittest.main()
