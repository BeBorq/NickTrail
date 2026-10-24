import tempfile,unittest,json
from pathlib import Path
from nicktrail.publicprofile import ProfileHTML
from nicktrail.personal import paths,relevant,crawl
from nicktrail.storage import Store
class PersonalTests(unittest.TestCase):
 def test_identity_semantics_survive_footer_but_general_nav_does_not(self):
  p=ProfileHTML();p.feed('<footer><a rel="me" href="https://github.com/oldname">code</a><a href="https://tracker.example">tracker</a><a href="mailto:person%40example.org?subject=x">mail</a></footer>')
  evidence=p.identity_evidence('https://personal.example')
  self.assertEqual({e.get('url',e.get('email')) for e in evidence},{'https://github.com/oldname','person@example.org'});self.assertEqual(p.links,[])
 def test_relevant_paths_and_sitemap_are_bounded(self):
  self.assertTrue(relevant('https://site.example/en/about','https://site.example'))
  for u in ('https://evil.example/about','https://site.example/blog/post','https://site.example/about?next=x'):
   self.assertFalse(relevant(u,'https://site.example'))
  xml='<urlset><url><loc>https://site.example/about</loc></url><url><loc>https://site.example/blog/post</loc></url></urlset>'
  self.assertEqual(paths(xml,'https://site.example'),['https://site.example/about'])
  self.assertEqual(paths('<!DOCTYPE x>'+xml,'https://site.example'),[])
  self.assertEqual(paths('<sitemapindex><loc>https://site.example/about</loc></sitemapindex>','https://site.example'),[])
 def test_crawl_respects_robots_and_retains_real_page_provenance(self):
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
   s=Store(str(Path(tmp)/'t.db'));p=s.project('fixture');id=s.add(p,'https://site.example');s.execute("update nodes set state='found' where id=?",(id,))
   class Client:
    def __init__(self):self.calls=[];self.count=0
    def get(self,url):
     self.calls.append(url);self.count+=1
     text='User-agent: *\nDisallow: /contact' if url.endswith('robots.txt') else '<urlset><url><loc>https://site.example/about</loc></url><url><loc>https://site.example/contact</loc></url></urlset>' if url.endswith('sitemap.xml') else '<p>Public personal biography sufficiently long to contain identity links and public profile details.</p><a rel="me" href="https://github.com/oldname">Code</a>'
     return {'state':'found','text':text,'url':url}
   c=Client();report=crawl(s,p,[id],c);self.assertEqual(len(report),1);self.assertNotIn('https://site.example/contact',c.calls)
   edges=s.rows("select source_url from evidence where location='html.rel-me'");self.assertEqual(edges[0]['source_url'],'https://site.example/about');s.db.close()
