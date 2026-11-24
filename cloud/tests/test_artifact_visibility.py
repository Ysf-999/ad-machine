from disk_test_support import DiskIndependentTestCase
import pathlib,json,tempfile,hashlib,unittest
from unittest.mock import patch
C=pathlib.Path(__file__).resolve().parents[1]
class ArtifactVisibilityTests(DiskIndependentTestCase):
 def test_fsync_close_commit_before_return(self):
  from cloud.worker.remote_receipts import artifact_receipt
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   root=pathlib.Path(td);called=[]
   def commit():
    p=root/'overnight-output/task18-unit/result.json';called.append(p.read_text())
   r=json.loads(artifact_receipt({'result':'ok'},root,'overnight-output/task18-unit/result.json',commit=commit));self.assertEqual(len(called),1);self.assertEqual(r['artifact']['sha256'],hashlib.sha256(called[0].encode()).hexdigest())
 def test_invisible_then_fresh_read_bounded_and_hash_verified(self):
  from cloud.worker.remote_receipts import download_artifact
  data=b'hello';a={'path':'overnight-output/task18-unit/result.json','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()};attempts=[]
  class V:
   def read_file(self,path):
    attempts.append(path)
    if len(attempts)<3:raise FileNotFoundError('not visible yet')
    yield data
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   p=pathlib.Path(td)/'result';r=download_artifact(V(),a,p,fresh=V,attempts=3,sleep=lambda s:None);self.assertEqual(p.read_bytes(),data);self.assertEqual(r['attempts'],3);self.assertEqual(len(r['visibility_exceptions']),2)
 def test_never_visible_fails_after_bound(self):
  from cloud.worker.remote_receipts import download_artifact
  n=[]
  class V:
   def read_file(self,path):n.append(path);raise FileNotFoundError('never visible')
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   with self.assertRaises(FileNotFoundError):download_artifact(V(),{'path':'x','bytes':1,'sha256':'0'*64},pathlib.Path(td)/'x',attempts=2,sleep=lambda s:None)
  self.assertEqual(len(n),2)
 def test_hash_failure_not_retried(self):
  from cloud.worker.remote_receipts import download_artifact
  class V:
   def read_file(self,path):yield b'bad'
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):download_artifact(V(),{'path':'x','bytes':3,'sha256':'0'*64},pathlib.Path(td)/'x')
 def test_second_diagnostic_failure_local_but_auth_still_global(self):
  from cloud.worker.remote_receipts import fail_run,RemoteRunFailed
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   root=pathlib.Path(td)
   for name in ['a','a-retry']:
    with self.assertRaises(RemoteRunFailed):fail_run(ValueError('diagnostic'),root,name,family='a',diagnostic=True)
   self.assertFalse((root/'GLOBAL_STOP.json').exists());self.assertTrue((root/'WORKSTREAM_STOP.json').exists())
   with self.assertRaises(RemoteRunFailed):fail_run(RuntimeError('HTTP401'),root,'auth',diagnostic=True)
   self.assertTrue((root/'GLOBAL_STOP.json').exists())

 def test_first_paid_failure_global_even_without_auth(self):
  from cloud.worker.remote_receipts import fail_run,RemoteRunFailed
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   root=pathlib.Path(td)
   with self.assertRaises(RemoteRunFailed):fail_run(RuntimeError('paid outcome failed'),root,'paid',critical=True)
   self.assertTrue((root/'GLOBAL_STOP.json').exists())
