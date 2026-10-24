import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from nicktrail.xprofile import parse,read,manual_link
from nicktrail.storage import Store
from nicktrail.engine import record

class XTests(unittest.TestCase):
    def test_expanded_profile_link_not_display_or_short_url(self):
        result=parse({'id':'123','username':'fictional','description':'Test','url':'https://t.co/example','entities':{'url':{'urls':[{'url':'https://t.co/example','display_url':'wrong.example','expanded_url':'https://hackerone.com/fictional'}]}}},'https://x.com/fictional')
        self.assertEqual([e['url'] for e in result['evidence']],['https://hackerone.com/fictional'])
        self.assertEqual(result['evidence'][0]['relation'],'links')

    def test_no_token_makes_no_requests(self):
        class Never:
            def get(self,*args,**kwargs):raise AssertionError('No request without key')
        with patch.dict('os.environ',{},clear=True):
            r=read({'url':'https://x.com/fictional','data':'{}'},Never())
        self.assertEqual(r['state'],'unsupported')
        self.assertIn('NICKTRAIL_X_BEARER_TOKEN',r['detail'])

    def test_known_id_lookup_uses_key_only_on_api(self):
        calls=[]
        class Client:
            def get(self,url,headers):
                calls.append((url,headers))
                return {'state':'found','text':json.dumps({'data':{'id':'123','username':'renamed'}})}
        with patch.dict('os.environ',{'NICKTRAIL_X_BEARER_TOKEN':'fixture'}):
            result=read({'url':'https://x.com/old','data':'{"stable_id":"123"}'},Client())
        self.assertTrue(calls[0][0].startswith('https://api.x.com/2/users/123?'))
        self.assertEqual(calls[0][1],{'Authorization':'Bearer fixture'})
        self.assertEqual(result['canonical_url'],'https://x.com/renamed')

    def test_malformed_and_unsafe_api_links(self):
        with self.assertRaises(ValueError):parse({'id':'1','username':'../bad'},'https://x.com/f')
        r=parse({'id':'1','username':'fictional','entities':{'url':{'urls':[{'expanded_url':'javascript:alert(1)'}]}}},'https://x.com/fictional')
        self.assertFalse(r['evidence'])

    def test_manual_observation_stays_distinct_and_unknown(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            store=Store(Path(folder)/'test.sqlite3')
            try:
                project=store.project('Fictional');source=store.add(project,'https://x.com/fictional')
                target=manual_link(store,source,'https://hackerone.com/fictional','Link w polu strony, zrzut użytkownika')
                edge=store.snapshot(project)['evidence'][0]
                self.assertEqual(edge['method'],'manual_observation')
                self.assertEqual(edge['decision'],'unknown')
                self.assertEqual(store.node(target)['ownership'],'unknown')
                store.evidence(project,target,source,'links','https://hackerone.com/fictional','website','https://x.com/fictional')
                self.assertTrue(all(e['assessment']!='reciprocal' for e in store.snapshot(project)['evidence']))
                record(store,store.node(source),[],complete=True)
                self.assertEqual(store.snapshot(project)['evidence'][0]['current'],1)
                with self.assertRaises(ValueError):manual_link(store,source,'javascript:x','Test')
            finally:store.db.close()
