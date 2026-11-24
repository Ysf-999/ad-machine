
from disk_test_support import DiskIndependentTestCase
import json,pathlib,tempfile,unittest
from cloud.worker.protocol import execute,validate_job,queue_once
from cloud.storage import S3Storage,IntegrityError
from test_storage import FakeS3
from cloud.orchestrator import Queue
from hygiene import SCRATCH
from runner.stage import digest
class ProtocolTests(DiskIndependentTestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(dir=SCRATCH);self.addCleanup(self.t.cleanup);self.p=pathlib.Path(self.t.name);self.s=S3Storage(FakeS3(),'fake',go=True,credit_cap='0',costs={'get':'0','put':'0'});self.src=self.p/'source';self.src.write_bytes(b'{}');ref=self.s.put(self.src)
  self.job={'version':1,'id':'unit','manifest':{'tool':'ad','stage':'status','project_inputs':['plan.json'],'outputs':['plan.json']},'inputs':{'project/plan.json':ref.to_dict()},'limits':{'timeout_seconds':60,'max_output_bytes':10000},'options':{'project':'project'}}
 def runner(self,root,project,manifest,result_dir,**kw):
  p=pathlib.Path(result_dir);(p/'outputs').mkdir(parents=True);(p/'outputs/plan.json').write_bytes((pathlib.Path(project)/'plan.json').read_bytes());return {'status':'done','returncode':0,'deliverable':False}
 def test_fake_s3_queue_pull_run_push_upload_once_and_resume(self):
  calls=[]
  def run(*args,**kw):calls.append(1);return self.runner(*args,**kw)
  first=execute(self.job,self.s,self.p/'worker',runtime_root=self.p,runner=run);again=execute(self.job,self.s,self.p/'worker',runtime_root=self.p,runner=run)
  self.assertEqual(first,again);self.assertEqual(len(calls),1);self.assertEqual(self.s.client.uploads,1);self.assertEqual(first['exit_status'],0);self.assertEqual(first['evidence_kind'],'injected-runner');self.assertFalse(first['deliverable'])
  q=Queue(self.p/'queue.sqlite');r=q.create_run(go=True,credit_cap='0');j=q.enqueue(r,'ad','status',self.job,plan_path=self.src)
  result=queue_once(q,self.s,self.p/'queue-worker',runtime_root=self.p,runner=run);self.assertEqual(result['state'],'done');self.assertEqual(result['id'],j['id'])
 def test_input_corruption_fails_before_runner_or_result(self):
  ref=self.job['inputs']['project/plan.json'];self.s.client.objects['fake',ref['key']]=b'corrupt'
  def refuse(*a,**k):self.fail('Runner must not execute corrupt input')
  with self.assertRaises(IntegrityError):execute(self.job,self.s,self.p/'worker',runtime_root=self.p,runner=refuse)
  self.assertFalse((self.p/'worker/result-envelope.json').exists())
 def test_resume_after_transfer_failure_and_local_corruption(self):
  self.job['inputs']['project/b']=self.s.put(self.src).to_dict();original=self.s.get;calls=[]
  def get(ref,dest):
   calls.append(str(dest))
   if len(calls)==2:raise OSError('injected interruption')
   return original(ref,dest)
  self.s.get=get
  with self.assertRaises(OSError):execute(self.job,self.s,self.p/'worker',runtime_root=self.p,runner=self.runner)
  self.s.get=original
  result=execute(self.job,self.s,self.p/'worker',runtime_root=self.p,runner=self.runner);self.assertEqual(result['exit_status'],0)
  (self.p/'worker/inputs/project/plan.json').write_bytes(b'changed')
  with self.assertRaises(IntegrityError):execute(self.job,self.s,self.p/'worker',runtime_root=self.p,runner=self.runner)
 def test_arbitrary_paid_path_unknown_versions_limits_refused(self):
  for mutate in [lambda j:j.update(version=2),lambda j:j['manifest'].update(stage='vo'),lambda j:j['inputs'].update({'../escape':j['inputs']['project/plan.json']}),lambda j:j['limits'].update(timeout_seconds=True),lambda j:j['options'].update(project='../bad')]:
   j=json.loads(json.dumps(self.job));mutate(j)
   with self.assertRaises(ValueError):validate_job(j)
