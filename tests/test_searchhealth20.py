import tempfile,unittest
from pathlib import Path
from nicktrail.storage import Store
from nicktrail.serviceaudit import report
from nicktrail.healthbatch import run
class SearchHealth20Tests(unittest.TestCase):
 def test_name_search_does_not_offer_inapplicable_exact_health_test(self):
  with tempfile.TemporaryDirectory() as directory:
   s=Store(Path(directory)/'case.sqlite3')
   try:
    rows=report(s,limit=2000)['rows'];row=next(r for r in rows if r['health_key']=='provider:StackOverflow')
    self.assertEqual(row['validation_action'],'search_controls_required');self.assertFalse(row['exact_username'])
    r=run(s,[{'service':'provider:StackOverflow','positive':'fiction','negative':'missingfiction'}],maximum=1)
    self.assertEqual(r['selected'],0);self.assertEqual(r['skipped'][0]['reason'],'search_controls_required')
    r=run(s,[{'service':'Free:UnknownFictionalPlatform','positive':'fiction','negative':'missingfiction'}],maximum=1)
    self.assertEqual(r['selected'],0);self.assertIn('CONTROL_SERVICE_NOT_IN_CATALOG',r['skipped'][0]['reason']);self.assertNotIn('missingfiction',str(r))
   finally:s.db.close()
