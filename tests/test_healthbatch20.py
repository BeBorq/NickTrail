import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.healthbatch import run
class Batch20Tests(unittest.TestCase):
 def test_batch_is_bounded_does_not_echo_controls_and_does_not_query_without_pairs(self):
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
   s=Store(Path(tmp)/'test.db')
   try:
    with patch('nicktrail.healthbatch.validate',return_value={'status':'EXACT_ONLY'}) as v:
     r=run(s,[],maximum=1,pause=lambda _:None);self.assertEqual(v.call_count,0)
     r=run(s,[{'service':'provider:GitHub','positive':'private-control-alias','negative':'private-missing-alias'}],maximum=1,pause=lambda _:None);self.assertEqual(v.call_count,1);self.assertEqual(r['selected'],1);self.assertNotIn('private-control-alias',str(r));self.assertNotIn('private-missing-alias',str(r))
    with self.assertRaises(ValueError):run(s,[],maximum=26)
   finally:s.db.close()
