import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.branches import explore,history
from nicktrail.presentation import labels
from nicktrail.avatars import fetch
from nicktrail.network import Limit

class Fixture:
    def __init__(self,limit=100):self.count=0;self.limit=limit;self.calls=[]
    def get(self,url):
        if self.count>=self.limit:raise Limit('Fixture budget')
        self.count+=1;self.calls.append(url)
        path=url.split('/')[-1]
        # Generic public pages, many child links plus a loop to root.
        links=''.join('<a href="https://fixture.example/child'+str(i)+'">child</a>' for i in range(20))
        text='<main><p>Fictional public biography with enough visible text to test links and bounded traversal.</p>'+links+'<a href="https://fixture.example/root">root</a></main>'
        return {'state':'found','text':text,'url':url}

class BranchTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(dir=Path.cwd());self.store=Store(Path(self.folder.name)/'test.sqlite3');self.project=self.store.project('Fixture')
        # Registered profile platform: public HTML allows same-site profile links, unlike generic about-only scope.
        self.root=self.store.add(self.project,'https://linktr.ee/root')
    def tearDown(self):self.store.db.close();self.folder.cleanup()
    def test_ten_total_children_cycles_and_unknown_ownership(self):
        run=explore(self.store,self.project,[self.root],client=Fixture())
        rows=history(self.store,self.project)[0]['nodes']
        self.assertEqual(sum(r['depth']>0 for r in rows),10)
        self.assertEqual(len(rows),11)
        self.assertTrue(all(self.store.node(r['node'])['ownership']=='unknown' for r in rows))
    def test_resume_pending_queue_without_repeating_completed_reads(self):
        client=Fixture(limit=2)
        run=explore(self.store,self.project,[self.root],client=client)
        self.assertEqual(history(self.store,self.project)[0]['run']['status'],'limited')
        done={r['node'] for r in history(self.store,self.project)[0]['nodes'] if r['state']=='found'}
        follow=Fixture();explore(self.store,self.project,resume=run,client=follow)
        self.assertEqual(history(self.store,self.project)[0]['run']['status'],'completed')
        self.assertTrue(all(self.store.node(i)['url'] not in follow.calls for i in done))
    def test_rejected_parent_stops_queued_children(self):
        run=explore(self.store,self.project,[self.root],client=Fixture(limit=1))
        self.store.decide(self.root,'not_mine');client=Fixture()
        explore(self.store,self.project,resume=run,client=client)
        self.assertEqual(client.count,0)
        self.assertTrue(any(r['state']=='skipped' for r in history(self.store,self.project)[0]['nodes']))
    def test_shared_child_is_read_once_across_roots(self):
        other=self.store.add(self.project,'https://linktr.ee/second')
        client=Fixture();explore(self.store,self.project,[self.root,other],client=client)
        self.assertEqual(client.count,12)
        self.assertEqual(len(history(self.store,self.project)[0]['nodes']),22)
    def test_cycles_do_not_expand_forever(self):
        class Cycle:
            count=0
            def get(self,url):
                self.count+=1
                target='https://linktr.ee/second' if url.endswith('/root') else 'https://linktr.ee/root'
                return {'state':'found','url':url,'text':'<main><p>Fictional public biography for a bounded traversal cycle test, containing an explicit profile link.</p><a href="'+target+'">Profile</a></main>'}
        client=Cycle();explore(self.store,self.project,[self.root],client=client)
        self.assertEqual(client.count,2)
        self.assertEqual(len(history(self.store,self.project)[0]['nodes']),2)
    def test_color_is_not_the_same_as_same_nickname(self):
        self.store.apply_profile(self.project,'https://linktr.ee/root',{'alias':'same'})
        child=self.store.apply_profile(self.project,'https://github.com/same',{'alias':'same'})
        snapshot=self.store.snapshot(self.project)
        self.assertEqual(labels(snapshot)[str(child)]['color'],'red')
        self.assertEqual(labels(snapshot,pending=[child])[str(child)]['color'],'gray')
        self.store.evidence(self.project,self.root,child,'links','https://linktr.ee/root','bio','https://github.com/same')
        self.assertEqual(labels(self.store.snapshot(self.project))[str(child)]['color'],'orange')
        self.store.evidence(self.project,child,self.root,'links','https://github.com/same','bio','https://linktr.ee/root')
        self.assertEqual(labels(self.store.snapshot(self.project))[str(child)]['color'],'green')
    def test_avatar_refuses_svg_and_invalid_raster(self):
        self.store.apply_profile(self.project,'https://linktr.ee/root',{'avatar_url':'https://images.example/avatar.svg'})
        with patch('nicktrail.avatars.Client') as client:
            client.return_value.get.return_value={'state':'found','bytes':b'<svg/>','content_type':'image/svg+xml'}
            self.assertIsNone(fetch(self.store,self.root))
            client.return_value.get.return_value={'state':'found','bytes':b'\x89PNG\r\n\x1a\nfixture','content_type':'image/png'}
            self.assertIsNotNone(fetch(self.store,self.root))
