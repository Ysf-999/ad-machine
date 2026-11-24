import json,pathlib,tempfile,subprocess,unittest
try:
 from cloud.worker.remote_receipts import receipt_json,receive,RemoteRunFailed
except ImportError:receipt_json=receive=RemoteRunFailed=None
C=pathlib.Path(__file__).resolve().parents[1]
class RemoteReceiptTests(unittest.TestCase):
 def setUp(self):self.assertIsNotNone(receipt_json)
 def test_oversize_rejected_before_function_return(self):
  self.assertEqual(json.loads(receipt_json({'ok':True})),{'ok':True})
  with self.assertRaises(ValueError):receipt_json({'large':'x'*65536})
 def test_nonfinite_and_nonjson_receipts_rejected(self):
  for payload in [{'x':float('nan')},{'x':object()}]:
   with self.assertRaises((ValueError,TypeError)):receipt_json(payload)
 def check_exception(self,error):
  class Call:
   def get(self):raise error
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   p=pathlib.Path(td)
   with self.assertRaises(RemoteRunFailed):receive(Call(),p,'unit')
   stop=json.loads((p/'RUN_STOP.json').read_text());self.assertIn(type(error).__name__,stop['reason']);self.assertIn(str(error),(p/'unit-exception.txt').read_text())
 def test_autherror_class_stops_and_raises(self):self.check_exception(type('AuthError',(Exception,),{})('denied'))
 def test_http401_stops_and_raises(self):self.check_exception(RuntimeError("HTTP 401"))
 def test_deserializationerror_stops_and_raises(self):self.check_exception(type('DeserializationError',(Exception,),{})('cannot decode'))
 def test_timeout_stops_and_raises(self):self.check_exception(TimeoutError('elapsed'))
 def test_nonzero_exit_exception_stops_and_raises(self):self.check_exception(subprocess.CalledProcessError(7,['unit']))
 def test_nonzero_returned_exit_fails_loudly(self):
  class Call:
   def get(self):return {'returncode':7}
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   with self.assertRaises(RemoteRunFailed):receive(Call(),pathlib.Path(td),'nonzero')
   self.assertTrue((pathlib.Path(td)/'RUN_STOP.json').exists())
 def test_unknown_remote_exception_stops_and_raises(self):self.check_exception(ValueError('unknown'))

class RemoteStopScopeTests(unittest.TestCase):
 def test_first_regular_failure_is_run_stop_second_attempt_is_global(self):
  class Call:
   def get(self):raise FileNotFoundError('missing diagnostic field')
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   p=pathlib.Path(td)
   with self.assertRaises(RemoteRunFailed):receive(Call(),p,'attempt-one',family='same')
   self.assertTrue((p/'RUN_STOP.json').exists());self.assertFalse((p/'GLOBAL_STOP.json').exists())
   with self.assertRaises(RemoteRunFailed):receive(Call(),p,'attempt-two',family='same')
   self.assertTrue((p/'GLOBAL_STOP.json').exists())
 def test_autherror_always_global_on_first_attempt(self):
  class Call:
   def get(self):raise type('AuthError',(Exception,),{})('401')
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   with self.assertRaises(RemoteRunFailed):receive(Call(),pathlib.Path(td),'auth')
   self.assertTrue((pathlib.Path(td)/'GLOBAL_STOP.json').exists())
 def test_cgroup_v1_v2_and_unavailable_are_distinguished(self):
  try:from cloud.worker.remote_receipts import cgroup_cpu_quota
  except ImportError:cgroup_cpu_quota=None
  self.assertIsNotNone(cgroup_cpu_quota)
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   p=pathlib.Path(td);self.assertEqual(cgroup_cpu_quota(p)['status'],'not_exposed')
   (p/'cpu.max').write_text('600000 100000');self.assertEqual(cgroup_cpu_quota(p)['raw'],'600000 100000')
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   p=pathlib.Path(td);(p/'cpu').mkdir();(p/'cpu/cpu.cfs_quota_us').write_text('600000');(p/'cpu/cpu.cfs_period_us').write_text('100000')
   self.assertEqual(cgroup_cpu_quota(p)['version'],1)

class ArtifactReceiptTests(unittest.TestCase):
 def test_large_detail_stays_in_file_small_return_is_hash_bound(self):
  try:from cloud.worker.remote_receipts import artifact_receipt
  except ImportError:artifact_receipt=None
  self.assertIsNotNone(artifact_receipt)
  import hashlib
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   p=pathlib.Path(td);detail={'status':'DONE','log':'z'*100000,'remote_wall_seconds':1}
   r=json.loads(artifact_receipt(detail,p,'overnight-output/task16-unit/receipt.json'))
   self.assertLess(len(receipt_json(r).encode()),65536);f=p/r['artifact']['path']
   self.assertEqual(hashlib.sha256(f.read_bytes()).hexdigest(),r['artifact']['sha256']);self.assertEqual(json.loads(f.read_text()),detail)
   with self.assertRaises(FileExistsError):artifact_receipt(detail,p,'overnight-output/task16-unit/receipt.json')
   with self.assertRaises(ValueError):artifact_receipt(detail,p,'../outside')
   json.loads(artifact_receipt(detail,p,'overnight-output/task17-unit/receipt.json'))
   with self.assertRaises(ValueError):artifact_receipt(detail,p,'overnight-output/task99-unit/receipt.json')

class OuterRemoteFailureTests(unittest.TestCase):
 def test_app_creation_exception_before_poll_also_writes_run_stop(self):
  try:from cloud.worker.remote_receipts import fail_run
  except ImportError:fail_run=None
  self.assertIsNotNone(fail_run)
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   p=pathlib.Path(td);error=type('ResourceExhaustedError',(Exception,),{})('App create rate limit')
   with self.assertRaises(RemoteRunFailed):fail_run(error,p,'app-create')
   self.assertTrue((p/'RUN_STOP.json').exists());self.assertIn('ResourceExhaustedError',(p/'app-create-exception.txt').read_text())

class StrictReceiptBoundaryTests(unittest.TestCase):
 def test_decimal64kb_limit_also_rejects_between64000_and65536(self):
  with self.assertRaises(ValueError):receipt_json({'padding':'x'*64000})
 def test_failed_artifact_preserves_nonzero_exit(self):
  from cloud.worker.remote_receipts import artifact_receipt
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   r=json.loads(artifact_receipt({'status':'FAILED_OCR','returncode':7,'log':'x'*70000},pathlib.Path(td),'overnight-output/task16-unit/error.json'))
   self.assertEqual(r.get('returncode'),7)

class FailedReceiptAccessTests(unittest.TestCase):
 def test_failed_small_receipt_remains_available_for_verified_error_file_fetch(self):
  class Call:
   def get(self):return {'returncode':1,'status':'FAILED_OCR','artifact':{'path':'error.json','sha256':'a'*64}}
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   with self.assertRaises(RemoteRunFailed) as error:receive(Call(),pathlib.Path(td),'failed-ocr')
   self.assertEqual(getattr(error.exception,'receipt',None),Call().get())

class SDKProcessFailureTests(unittest.TestCase):
 def test_uncaught_sdk_process_auth_exception_is_caught_by_shared_supervisor(self):
  try:from cloud.worker.remote_receipts import record_process_failure
  except ImportError:record_process_failure=None
  self.assertIsNotNone(record_process_failure)
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   p=pathlib.Path(td);log=p/'job.log';log.write_text("Traceback (most recent call last):\nmodal.exception.AuthError: Received401\n")
   record_process_failure(1,log,p,'job')
   self.assertTrue((p/'GLOBAL_STOP.json').exists());self.assertIn('AuthError',(p/'job-exception.txt').read_text())
 def test_expected_local_diagnostic_exit_is_not_a_remote_process(self):
  try:from cloud.worker.remote_receipts import record_process_failure
  except ImportError:record_process_failure=None
  self.assertIsNotNone(record_process_failure)
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   p=pathlib.Path(td);log=p/'job.log';log.write_text('ValueError: ordinary diagnostic failure\n')
   record_process_failure(1,log,p,'job')
   self.assertTrue((p/'RUN_STOP.json').exists());self.assertFalse((p/'GLOBAL_STOP.json').exists())
