import time
import unittest
from types import SimpleNamespace
from nicktrail.rendered import render
from nicktrail.evaluation import benchmark
from unittest.mock import patch
from pathlib import Path
import tempfile
import json
from nicktrail.storage import Store
from nicktrail.engine import scan

class RenderTests(unittest.TestCase):
    def test_isolated_context_routes_requests_through_client(self):
        saved={}
        class Route:
            request=SimpleNamespace(method='GET',resource_type='document',url='https://example.org/me')
            def fulfill(self,**kwargs):saved['fulfilled']=kwargs
            def abort(self):saved['aborted']=True
        class Page:
            url='https://example.org/me'
            def goto(self,url,**kwargs):saved['route'](Route())
            def wait_for_load_state(self,*args,**kwargs):pass
            def content(self):return '<main>Rendered fictional profile content.</main>'
        class Context:
            def route(self,pattern,handler):saved['route']=handler
            def route_web_socket(self,pattern,handler):saved['websocket_blocked']=True
            def add_init_script(self,script):pass
            def new_page(self):return Page()
        class Browser:
            def new_context(self,**kwargs):saved['context']=kwargs;return Context()
            def close(self):saved['closed']=True
        class Chromium:
            def launch(self,**kwargs):saved['launch']=kwargs;return Browser()
        class Runtime:
            chromium=Chromium()
            def __enter__(self):return self
            def __exit__(self,*args):pass
        class Client:
            deadline=time.monotonic()+20
            def get(self,url):saved['url']=url;return {'state':'found','text':'Fictional','url':url}
        result=render('https://example.org/me',Client(),Runtime)
        self.assertEqual(result['state'],'found')
        self.assertEqual(saved['context']['service_workers'],'block')
        self.assertTrue(saved['websocket_blocked']);self.assertTrue(saved['closed'])
        self.assertFalse(saved['context']['accept_downloads'])
        self.assertIn('proxy',saved['launch'])
        saved['route'](SimpleNamespace(request=SimpleNamespace(method='POST',resource_type='xhr'),abort=lambda:saved.update(post_blocked=True)))
        self.assertTrue(saved['post_blocked'])
    def test_synthetic_benchmark_is_repeatable_and_not_calibration(self):
        report=benchmark()
        self.assertEqual(report['cases'],40)
        self.assertEqual(report['hit_at_1'],1)
        self.assertEqual(report,benchmark())
        self.assertIn('not a real-world',report['dataset'])
    def test_rendering_preserves_known_id_and_older_api_evidence(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            store=Store(Path(folder)/'test.sqlite3')
            try:
                project=store.project('Fictional');source=store.apply_profile(project,'https://github.com/fictional',{'stable_id':'123','alias':'fictional'})
                target=store.add(project,'https://example.org/me')
                store.evidence(project,source,target,'links','https://github.com/fictional','blog','https://example.org/me')
                with patch('nicktrail.rendered.read',return_value={'state':'found','data':{'title':'Rendered public page'},'evidence':[]}):
                    scan(store,project,targets=[source],rendered=True,client=SimpleNamespace(count=0))
                self.assertEqual(json.loads(store.node(source)['data'])['stable_id'],'123')
                self.assertEqual(store.snapshot(project)['evidence'][0]['current'],1)
            finally:store.db.close()
