
from disk_test_support import DiskIndependentTestCase
import unittest
from cloud.simulation import scenario
class ScaleTests(DiskIndependentTestCase):
 def test_500_has_125_bases_375_hooks_and_cap_1500(self):
  a=scenario(5415,500);self.assertEqual(len(a['ads']),125);self.assertEqual(sum(len(b['hooks']) for b in a['ads']),375);self.assertEqual(a['cap'],'1500');self.assertEqual(len(a['faults']),1500);self.assertEqual(a,scenario(5415,500));self.assertNotEqual(a,scenario(20261119,500))
 def test_invalid_size_refused(self):
  for n in [0,99,501]:
   with self.assertRaises(ValueError):scenario(1,n)
