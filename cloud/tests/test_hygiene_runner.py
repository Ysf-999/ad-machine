
from disk_test_support import DiskIndependentTestCase
import json,pathlib,tempfile,unittest
from unittest.mock import patch
from runner import Manifest,run_stage
import hygiene
ROOT=pathlib.Path(__file__).resolve().parents[2]
class RunnerHygieneTests(DiskIndependentTestCase):
 def test_success_default_drops_outputs_and_keep_retains(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'cloud/.scratch') as td:
   p=pathlib.Path(td);src=p/'source';src.mkdir();(src/'plan.json').write_text('{"ad":"disk-test","beats":[],"locked":false}')
   run_stage(ROOT,src,Manifest('ad','status',['plan.json']),p/'clean')
   self.assertFalse((p/'clean/outputs').exists());self.assertTrue((p/'clean/plan.patch.json').exists())
   run_stage(ROOT,src,Manifest('ad','status',['plan.json']),p/'keep',keep=True)
   self.assertTrue((p/'keep/outputs/plan.json').exists())
 def test_low_disk_refuses_before_output_creation(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'cloud/.scratch') as td:
   p=pathlib.Path(td);src=p/'source';src.mkdir();(src/'plan.json').write_text('{"beats":[],"locked":false}')
   with patch.object(hygiene,'free_bytes',return_value=9_000_000_000),self.assertRaises(hygiene.DiskSafetyError):run_stage(ROOT,src,Manifest('ad','status',['plan.json']),p/'result')
   self.assertFalse((p/'result').exists())
if __name__=='__main__':unittest.main()
