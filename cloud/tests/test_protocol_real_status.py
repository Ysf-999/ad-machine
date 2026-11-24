
from disk_test_support import DiskIndependentTestCase
import pathlib,tempfile,unittest,json
from cloud.storage import S3Storage
from cloud.worker.protocol import execute
from test_storage import FakeS3
from hygiene import SCRATCH
class ActualStatusProtocolTests(DiskIndependentTestCase):
 def test_fake_s3_to_actual_seatbelt_runner_and_back(self):
  with tempfile.TemporaryDirectory(dir=SCRATCH) as td:
   p=pathlib.Path(td);src=p/'plan.json';src.write_text('{"ad":"protocol-status","beats":[],"locked":false}')
   s=S3Storage(FakeS3(),'offline',go=True,credit_cap='0',costs={'get':'0','put':'0'})
   j={'version':1,'id':'actual-status','manifest':{'tool':'ad','stage':'status','project_inputs':['plan.json'],'outputs':['plan.json']},'inputs':{'project/plan.json':s.put(src).to_dict()},'limits':{'timeout_seconds':30,'max_output_bytes':1000000},'options':{'project':'project'}}
   r=execute(j,s,p/'worker',runtime_root=SCRATCH.parents[1]);self.assertEqual(r['status'],'done');self.assertEqual(r['evidence_kind'],'existing-runner');self.assertIn('outputs/plan.json',r['files']);self.assertFalse(r['deliverable'])
