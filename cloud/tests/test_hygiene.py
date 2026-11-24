
from disk_test_support import DiskIndependentTestCase
import pathlib,tempfile,time,unittest
from unittest.mock import patch
import hygiene as h
class HygieneTests(DiskIndependentTestCase):
 def api(self,name):
  fn=getattr(h,name,None);self.assertTrue(callable(fn),'missing hygiene API: '+name);return fn
 def test_default_floor_and_emergency(self):
  fn=self.api('require_space')
  with patch.object(h,'free_bytes',return_value=11_000_000_000):self.assertGreater(fn(),10_000_000_000)
  for available,word in [(9_000_000_000,'10'),(7_000_000_000,'STOP')]:
   with patch.object(h,'free_bytes',return_value=available),self.assertRaisesRegex(RuntimeError,word):fn()
 def test_custom_floor_cannot_remove_emergency(self):
  fn=self.api('require_space')
  with patch.object(h,'free_bytes',return_value=11_000_000_000),self.assertRaisesRegex(RuntimeError,'12'):fn(min_free_gb=12)
  with self.assertRaises(ValueError):fn(min_free_gb=2)
 def test_clone_independence_and_low_disk_refusal(self):
  fn=self.api('clone_file')
  with tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).resolve().parents[1]/'.scratch') as td:
   p=pathlib.Path(td);src=p/'source';dst=p/'dest';src.write_bytes(b'original')
   fn(src,dst);self.assertNotEqual(src.stat().st_ino,dst.stat().st_ino);dst.write_bytes(b'changed');self.assertEqual(src.read_bytes(),b'original')
   with patch.object(h,'free_bytes',return_value=9_000_000_000),self.assertRaises(RuntimeError):fn(src,p/'refused')
 def test_cleanup_default_drops_media_success_and_failure(self):
  fn=self.api('finish_result')
  for success,keep in [(True,False),(False,False),(False,True)]:
   with tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).resolve().parents[1]/'.scratch') as td:
    p=pathlib.Path(td);(p/'MASTER.mp4').write_bytes(b'mock media');(p/'stage.log').write_text('log');(p/'result.json').write_text('{}');fn(p,success=success,keep=keep)
    self.assertFalse((p/'MASTER.mp4').exists());self.assertTrue((p/'stage.log').exists());self.assertTrue((p/'result.json').exists())
 def test_keep_success_and_outside_refusal(self):
  fn=self.api('finish_result')
  with tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).resolve().parents[1]/'.scratch') as td:
   p=pathlib.Path(td);(p/'MASTER.mp4').write_bytes(b'mock');fn(p,success=True,keep=True);self.assertTrue((p/'MASTER.mp4').exists())
  with self.assertRaises(ValueError):fn(pathlib.Path(__file__).resolve().parents[1],success=True)
 def test_clean_is_list_only_and_protects_caches_symlinks(self):
  fn=self.api('clean_scratch')
  with tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).resolve().parents[1]/'.scratch') as td:
   p=pathlib.Path(td);(p/'old').mkdir();(p/'old/data').write_text('x');(p/'venv-faster').mkdir();(p/'uv-cache').mkdir();(p/'models--local').mkdir();(p/'escape').symlink_to(p.parent,target_is_directory=True)
   r=fn(age_hours=0,root=p,now=time.time()+2);self.assertEqual([x['name'] for x in r['candidates']],['old']);self.assertTrue((p/'old').exists())
   r=fn(age_hours=0,root=p,now=time.time()+2,go=True);self.assertFalse((p/'old').exists());self.assertTrue((p/'venv-faster').exists());self.assertTrue((p/'escape').is_symlink())
 def test_report_sizes_do_not_follow_symlinks(self):
  fn=self.api('tree_size')
  with tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).resolve().parents[1]/'.scratch') as td:
   p=pathlib.Path(td);(p/'data').write_bytes(b'12345');(p/'link').symlink_to(p/'data');self.assertEqual(fn(p)['logical_bytes'],5)
if __name__=='__main__':unittest.main()

class EmergencyProcessTests(DiskIndependentTestCase):
 def test_active_owned_process_is_stopped_when_emergency_floor_crosses(self):
  import sys,time
  with patch.object(h,'free_bytes',side_effect=[11_000_000_000,7_000_000_000]):
   with self.assertRaises(h.DiskEmergency):h.guarded_run([sys.executable,'-c','import time;time.sleep(5)'],timeout=10,probe_seconds=.01)

class ScratchListingRaceTests(DiskIndependentTestCase):
 def test_parent_of_active_workflow_and_nested_cache_excluded(self):
  with tempfile.TemporaryDirectory(dir=h.SCRATCH) as td:
   p=pathlib.Path(td);(p/'active/flow').mkdir(parents=True);(p/'active/flow/.active-workflow.json').write_text('{}');(p/'research/deep/.models').mkdir(parents=True)
   out=h.clean_scratch(root=p,age_hours=0,now=time.time()+10)
   self.assertEqual(out['candidates'],[]);self.assertEqual(len(out['excluded']),2)
 def test_disappearing_child_skips_candidate_instead_of_crashing(self):
  with tempfile.TemporaryDirectory(dir=h.SCRATCH) as td:
   p=pathlib.Path(td);(p/'old').mkdir();ghost=p/'old/vanished'
   with patch.object(pathlib.Path,'rglob',lambda *args:iter([ghost])):
    out=h.clean_scratch(root=p,age_hours=0,now=time.time()+10)
   self.assertEqual(out['candidates'],[]);self.assertEqual(out['excluded'][0]['reason'],'changed while listing; try again')
