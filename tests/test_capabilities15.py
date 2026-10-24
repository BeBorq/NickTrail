import unittest
from nicktrail.capabilities import matrix,presets
class CapabilitiesTests(unittest.TestCase):
 def test_imported_definitions_have_no_live_validation_claim(self):
  data=matrix();imported=[r for r in data['rows'] if r['group']=='Extended']
  self.assertEqual(len(imported),883);self.assertTrue(all(r['status']=='DEFINITION_UNVALIDATED' and r['live_test']=='not_tested' for r in imported));self.assertEqual(data['counts']['strict_templates'],100)
 def test_default_and_exact_presets_exclude_unvalidated_or_weak_sources(self):
  data=presets();self.assertNotIn('Extended',data['STANDARD']['platforms']);self.assertNotIn('ForgeFSFE',data['STANDARD']['platforms']);self.assertNotIn('StackOverflow',data['EXACT_ONLY']['platforms']);self.assertFalse(data['EXACT_ONLY']['related']);self.assertIn('Extended',data['EXTENDED']['platforms'])
