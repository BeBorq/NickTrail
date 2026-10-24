import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from nicktrail.identity import identify, normalize, email_key, team_email, classify
from nicktrail.network import Client, public_addresses, Limit
from nicktrail.storage import Store
from nicktrail.engine import scan
from nicktrail.demo import FixtureClient, create
from nicktrail.imports import posts, maigret
from nicktrail.exporting import export


class IdentityTests(unittest.TestCase):
    def test_profiles_and_repositories(self):
        self.assertEqual(identify('https://github.com/Alice')['kind'], 'profile')
        self.assertEqual(identify('https://github.com/Alice/project')['kind'], 'project')
        self.assertEqual(identify('https://instance.example/@alice')['platform'], 'Mastodon')
        self.assertNotEqual(identify('https://a.example/@alice')['url'], identify('https://b.example/@alice')['url'])
        self.assertEqual(identify('https://steamcommunity.com/profiles/123')['platform'], 'Steam')
        self.assertEqual(identify('https://www.roblox.com/users/123/profile')['kind'], 'profile')

    def test_normalization(self):
        self.assertEqual(normalize('https://GitHub.com/Alice/#bio'), 'https://github.com/alice')
        self.assertEqual(email_key('a.b+tag@EXAMPLE.com'), 'a.b+tag@example.com')
        self.assertTrue(team_email('support@example.com'))
        self.assertFalse(team_email('alice@example.com'))

    def test_semantics(self):
        u='https://github.com/example'
        self.assertEqual(classify('Mój GitHub to '+u,u), 'claims_ownership')
        self.assertEqual(classify('Polecam projekt '+u+'/repo',u+'/repo'), 'recommends')
        self.assertEqual(classify('Mój GitHub to '+u,u,'quote'), 'mentions')
        self.assertNotEqual(classify('Mój GitHub to '+u+'/repo',u+'/repo'),'claims_ownership')

    def test_ssrf(self):
        for ip in ('127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1','224.0.0.1','64:ff9b::a9fe:a9fe'):
            with self.subTest(ip=ip), self.assertRaises(ValueError):
                public_addresses('evil.example',lambda *a,**k:[(0,0,0,'',(ip,443))])
        with self.assertRaises(ValueError): normalize('http://user:pass@example.com')
        with self.assertRaises(ValueError): normalize('file:///tmp/file')
        with self.assertRaises(ValueError): normalize('https://example.com:8080')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path.cwd());self.path=Path(self.tmp.name)/'test.db';self.s=Store(self.path);self.p=self.s.project('Test')
    def tearDown(self): self.s.db.close();self.tmp.cleanup()

    def test_demo_and_preserved_decisions(self):
        p=create(self.s);snap=self.s.snapshot(p)
        repo=next(n for n in snap['nodes'] if n['kind']=='project')
        self.assertEqual(repo['ownership'],'unknown')
        self.assertTrue(any(e['relation']=='team_contact' for e in snap['evidence']))
        self.s.decide(repo['id'],'not_mine')
        evidence=snap['evidence'][0];self.s.decide(evidence['id'],'rejected',True)
        scan(self.s,p,client=FixtureClient())
        self.assertEqual(self.s.node(repo['id'])['ownership'],'not_mine')
        self.assertEqual(self.s.rows('SELECT decision FROM evidence WHERE id=?',(evidence['id'],))[0]['decision'],'rejected')
        self.assertEqual(len(self.s.snapshot(p)['evidence']),len(snap['evidence']))

    def test_identical_nicks_and_rejected_are_not_expanded(self):
        self.s.add(self.p,'https://github.com/same-nick')
        other=self.s.add(self.p,'https://dev.to/same-nick',confirmed=True)
        self.s.decide(other,'not_mine')
        client=FixtureClient();scan(self.s,self.p,client=client)
        self.assertEqual(client.count,0)

    def test_candidate_link_no_automatic_recursion(self):
        self.s.add(self.p,'https://github.com/fictional-nicktrail',confirmed=True)
        client=FixtureClient();scan(self.s,self.p,client=client)
        # Own (confirmed) GitHub account: the profile plus its declared social accounts.
        self.assertEqual(client.count,2)
        self.assertTrue(any(n['state']=='unverified' for n in self.s.snapshot(self.p)['nodes']))

    def test_depth_page_profile_limits(self):
        n=self.s.add(self.p,'https://github.com/fictional-nicktrail',confirmed=True,depth=3)
        c=FixtureClient();scan(self.s,self.p,{'depth':2},client=c);self.assertEqual(c.count,0)
        self.s.execute('UPDATE nodes SET depth=0 WHERE id=?',(n,))
        scan(self.s,self.p,{'profiles':0},client=c);self.assertEqual(c.count,0)
        self.s.add(self.p,'https://nicktrail.example/about',confirmed=True)
        c=FixtureClient();scan(self.s,self.p,{'profiles':0,'pages':0},client=c);self.assertEqual(c.count,0)

    def test_pause_resume(self):
        self.s.add(self.p,'https://github.com/fictional-nicktrail',confirmed=True)
        c=FixtureClient();id=scan(self.s,self.p,client=c,stopped=lambda:True)
        self.assertEqual(self.s.rows('SELECT status FROM scans WHERE id=?',(id,))[0]['status'],'paused')
        scan(self.s,self.p,resume=id,client=c);self.assertEqual(c.count,2)  # profile + declared social accounts

    def test_errors_retain_last_data_and_compare(self):
        id=self.s.add(self.p,'https://github.com/fictional-nicktrail',confirmed=True)
        first=scan(self.s,self.p,client=FixtureClient());data=self.s.node(id)['data']
        class ErrorClient:
            count=0
            def get(self,url): raise TimeoutError()
        second=scan(self.s,self.p,client=ErrorClient())
        self.assertEqual(self.s.node(id)['data'],data)
        self.assertEqual(self.s.node(id)['state'],'error')
        self.assertEqual(self.s.compare(first,second)[0]['change'],'unavailable')

    def test_imports_and_export(self):
        id=self.s.add(self.p,'https://github.com/fictional-nicktrail',confirmed=True)
        posts(self.s,id,[{'text':'Mój GitHub to https://github.com/other','context':'quote','author':'Postać fikcyjna'}])
        e=self.s.snapshot(self.p)['evidence'][0];self.assertEqual(e['relation'],'mentions')
        maigret(self.s,self.p,{'test':{'url_user':'https://dev.to/other','country':'invented'}})
        self.assertEqual(self.s.snapshot(self.p)['nodes'][-1]['ownership'],'unknown')
        self.s.add(self.p,'alice+tag@example.com','email')
        self.assertNotIn('alice+tag@example.com',export(self.s,self.p,omit_email=True))
        payload=json.loads(export(self.s,self.p,exclude=[id]));self.assertFalse(payload['evidence'])

    def test_deduplication_and_persistence(self):
        a=self.s.add(self.p,'https://github.com/Alice/',confirmed=True)
        b=self.s.add(self.p,'https://github.com/alice#bio');self.assertEqual(a,b)
        self.s.db.close();self.s=Store(self.path);self.assertEqual(self.s.node(a)['ownership'],'mine')

    def test_delete_cascade(self):
        p=create(self.s);self.s.execute('DELETE FROM projects WHERE id=?',(p,))
        for table in ('nodes','evidence','scans','observations'):
            self.assertFalse(self.s.rows('SELECT * FROM '+table))


class NetworkTests(unittest.TestCase):
    def setUp(self):
        isolation=patch.dict('nicktrail.network.PROCESS_COOLDOWNS',{},clear=True);isolation.start();self.addCleanup(isolation.stop)

    def test_query_budget(self):
        with self.assertRaises(Limit): Client(queries=0).get('https://example.com')

    def test_redirect_private_dns(self):
        class Response:
            status=302
            def getheader(self,key,default=''): return 'http://127.0.0.1/secret' if key=='Location' else default
        class Connection:
            def __init__(self,*a,**k): pass
            def request(self,*a,**k): pass
            def getresponse(self): return Response()
            def close(self): pass
        def resolve(host):
            if host=='127.0.0.1': raise ValueError('private')
            return ['93.184.216.34']
        with patch('nicktrail.network.PinnedTLS',Connection),patch('nicktrail.network.public_addresses',resolve):
            with self.assertRaises(ValueError): Client(delay=0).get('https://example.com')

    def test_blocked_and_not_found(self):
        for status,expected in ((403,'blocked'),(404,'not_found'),(500,'error'),(429,'blocked')):
            class Response:
                def getheader(self,key,default=''): return '100' if key=='Retry-After' else default
            Response.status=status
            class Connection:
                def __init__(self,*a,**k): pass
                def request(self,*a,**k): pass
                def getresponse(self): return Response()
                def close(self): pass
            with patch('nicktrail.network.PinnedTLS',Connection),patch('nicktrail.network.public_addresses',return_value=['93.184.216.34']):
                self.assertEqual(Client(delay=0).get('https://example.com')['state'],expected)


if __name__=='__main__': unittest.main()
