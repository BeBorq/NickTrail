import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.search import discover,results
class ExactBarrier20Tests(unittest.TestCase):
 def test_pending_cooling_exact_does_not_release_weak_search_budget(self):
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
   s=Store(Path(tmp)/'test.db');p=s.project('Fictional');calls=[]
   class C:count=0
   def lookup(platform,term,client):
    calls.append((platform,term));return {'state':'blocked','detail':'HTTP 429; RATE_LIMITED'}
   try:
    with patch('nicktrail.search.lookup',side_effect=lookup):discover(s,p,'fictional',platforms=['GitHub'],related=True,client=C())
    run=results(s,p)[0];self.assertEqual(run['run']['status'],'paused');self.assertEqual(len(calls),1)
    self.assertTrue(all(t['state']=='pending' for t in run['tasks']))
   finally:s.db.close()
