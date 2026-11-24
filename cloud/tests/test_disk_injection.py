import collections,pathlib,tempfile,unittest
from unittest.mock import patch
from disk_test_support import DiskIndependentTestCase,HOST_DISK_PROBE
import hygiene as h
from runner import Manifest,run_stage
from cloud.storage import LocalStorage
class InjectionTests(DiskIndependentTestCase):
 def test_one_real_probe_remains_default(self):
  self.assertTrue(callable(HOST_DISK_PROBE))
  usage=collections.namedtuple('usage','total used free')(100_000_000_000,96_000_000_000,4_000_000_000)
  with patch.object(h,'disk_free_probe',side_effect=HOST_DISK_PROBE),patch.object(h.shutil,'disk_usage',return_value=usage) as raw:
   with self.assertRaises(h.DiskEmergency):h.require_space()
   self.assertTrue(raw.called)
 def test_production_guard_boundaries_and_configured_minimum(self):
  for free in [4_000_000_000,7_999_999_999,8_000_000_000,9_900_000_000]:
   with self.subTest(free=free),patch.object(h,'disk_free_probe',return_value=free),self.assertRaises(h.DiskSafetyError):h.require_space()
  for free in [10_000_000_000,50_000_000_000]:
   with patch.object(h,'disk_free_probe',return_value=free):self.assertEqual(h.require_space(),free)
  with patch.object(h,'disk_free_probe',return_value=11_000_000_000),patch.dict('os.environ',{'CLOUD_MIN_FREE_GB':'12'}),self.assertRaises(h.DiskSafetyError):h.require_space()
  with self.assertRaises(ValueError):h.require_space(min_free_gb=7.9)
 def test_real_copy_runner_and_storage_default_guards_matrix(self):
  with tempfile.TemporaryDirectory(dir=h.SCRATCH) as td:
   p=pathlib.Path(td);source=p/'source';source.write_bytes(b'')
   for free in [4_000_000_000,9_900_000_000,10_000_000_000,50_000_000_000]:
    root=p/str(free);root.mkdir();store=LocalStorage(root/'objects')
    def stage(*args):args[3].mkdir();return {'status':'done'}
    with patch.object(h,'disk_free_probe',return_value=free) as probe,patch('runner.stage._run_stage',side_effect=stage) as actual:
     if free<10_000_000_000:
      for call in [lambda:h.clone_file(source,root/'copy'),lambda:store.put(source),lambda:run_stage(h.CLOUD.parent,p,Manifest('ad','status',['plan.json']),root/'run')]:
       with self.assertRaises(h.DiskSafetyError):call()
      actual.assert_not_called();self.assertFalse((root/'copy').exists())
     else:
      h.clone_file(source,root/'copy');ref=store.put(source);store.get(ref,root/'download')
      run_stage(h.CLOUD.parent,p,Manifest('ad','status',['plan.json']),root/'run');actual.assert_called_once()
     self.assertGreater(probe.call_count,0)
 def test_exact_floor_still_reserves_copy_headroom(self):
  with patch.object(h,'disk_free_probe',return_value=10_000_000_000):
   self.assertEqual(h.require_space(),10_000_000_000)
   with self.assertRaises(h.DiskSafetyError):h.require_space(write_bytes=1)
