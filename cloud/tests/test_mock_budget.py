from disk_test_support import DiskIndependentTestCase
import pathlib,tempfile,json
from unittest.mock import patch
import hygiene
from cloud.mock_budget import MockBudget,DEFAULT_BYTES,MAX_BYTES
from cloud.workflow import Workflow
class MockBudgetTests(DiskIndependentTestCase):
 def test_default_and_hard_max(self):
  self.assertEqual(MockBudget(hygiene.SCRATCH/'test').limit,300_000_000)
  self.assertEqual(MockBudget(hygiene.SCRATCH/'test',limit=MAX_BYTES).limit,MAX_BYTES)
  for n in [1,0,1_000_000_001,float('inf')]:
   with self.assertRaises(ValueError):MockBudget(hygiene.SCRATCH/'test',limit=n)
 def test_emergency_and_separate_admission(self):
  with tempfile.TemporaryDirectory(dir=hygiene.SCRATCH) as d:
   b=MockBudget(d)
   for free in [4_000_000_000,5_999_999_999]:
    with patch.object(hygiene,'disk_free_probe',return_value=free),self.assertRaisesRegex(hygiene.DiskEmergency,'below6GB'):b.check()
   with patch.object(hygiene,'disk_free_probe',return_value=7_000_000_000):
    b.guard(d)
    with self.assertRaises(hygiene.DiskEmergency):hygiene.require_space()
    src=pathlib.Path(d)/'source';src.write_text('tiny')
    with self.assertRaises(hygiene.DiskEmergency):hygiene.clone_file(src,pathlib.Path(d)/'target')
 def test_footprint_and_root_binding(self):
  with tempfile.TemporaryDirectory(dir=hygiene.SCRATCH) as d:
   b=MockBudget(d,limit=9_000_000);(pathlib.Path(d)/'tiny').write_bytes(b'x'*1_100_000)
   self.assertGreaterEqual(b.check(),1_100_000)
   with self.assertRaisesRegex(hygiene.DiskSafetyError,'footprint'):b.guard(d)
   with self.assertRaises(ValueError):b.guard(hygiene.SCRATCH)
 def test_explicit_mock_only_and_no_real_project(self):
  with tempfile.TemporaryDirectory(dir=hygiene.SCRATCH) as d:
   b=MockBudget(d);root=pathlib.Path(d)/'flow';spec={'mock':True,'cap':'3','limits':{'kie':1,'elevenlabs':1,'ffmpeg':1},'ads':[{'id':'tiny'}]}
   with patch.object(hygiene,'disk_free_probe',return_value=7_000_000_000):
    with self.assertRaises(hygiene.DiskEmergency):Workflow.submit(root,spec)
    with self.assertRaises(ValueError):Workflow.submit(root,dict(spec,mock=False),mock_budget=b)
    f=Workflow.submit(root,spec,mock_budget=b);self.assertTrue(f.state_path.exists())
    state=json.loads(f.state_path.read_text());state['mock']=False;f.state_path.write_text(json.dumps(state))
    with self.assertRaises(ValueError):Workflow(root,mock_budget=b)
 def test_symlink_refused(self):
  with tempfile.TemporaryDirectory(dir=hygiene.SCRATCH) as d:
   (pathlib.Path(d)/'link').symlink_to(hygiene.CLOUD)
   with self.assertRaises(ValueError):MockBudget(d).check()
