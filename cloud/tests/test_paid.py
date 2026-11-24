
from disk_test_support import DiskIndependentTestCase
import json,pathlib,tempfile,unittest
from unittest.mock import patch
from cloud.orchestrator import Queue,SubmissionAmbiguous
from cloud.providers.paid import JournalAdapter,MockTransport
C=pathlib.Path(__file__).resolve().parents[1]
class PaidTests(DiskIndependentTestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(dir=C/'.scratch');self.addCleanup(self.t.cleanup);self.p=pathlib.Path(self.t.name);plan=self.p/'plan.json';plan.write_text('{}')
  self.q=Queue(self.p/'q.sqlite',provider_limits={'kie':1});run=self.q.create_run(go=True,credit_cap='1')
  self.job=self.q.enqueue(run,'ad','mock',{'mock':True},plan_path=plan,provider='kie',known_cost='1');self.j=self.q.claim('w');self.q.prepare_submission(self.j['id'],self.j['lease_token']);self.transport=MockTransport(self.p/'fake.sqlite');self.a=JournalAdapter(self.q,'kie',self.transport,mock=True)
 def test_id_durable_before_poll_and_adapter_restart(self):
  pid=self.a.submit(self.j);a=JournalAdapter(self.q,'kie',self.transport,mock=True)
  self.assertEqual(a.recover_receipt(self.j['id']),pid);self.assertEqual(a.poll(self.q.get(self.j['id']),pid)['status'],'done')
  with self.assertRaises(SubmissionAmbiguous):a.submit(self.j)
 def test_intent_exists_after_transport_exception_never_retries(self):
  with patch.object(self.transport,'submit',side_effect=RuntimeError('ambiguous')):
   with self.assertRaises(RuntimeError):self.a.submit(self.j)
  with patch.object(self.transport,'submit') as submit,self.assertRaises(SubmissionAmbiguous):self.a.submit(self.j)
  submit.assert_not_called()
 def test_lost_queue_id_can_recover_durable_receipt_without_submit(self):
  with patch.object(self.q,'record_provider_job',side_effect=OSError('crash')):
   with self.assertRaises(OSError):self.a.submit(self.j)
  pid=self.a.recover_receipt(self.j['id']);self.assertTrue(pid)
  with self.assertRaises(SubmissionAmbiguous):self.a.submit(self.j)
  self.q.record_provider_job(self.j['id'],self.j['lease_token'],pid)
  self.assertEqual(self.a.poll(self.q.get(self.j['id']),pid)['status'],'done')
 def test_restart_repairs_known_receipt_but_never_submits_again(self):
  with patch.object(self.q,'record_provider_job',side_effect=OSError('crash')):
   with self.assertRaises(OSError):self.a.submit(self.j)
  self.q.fail(self.j['id'],self.j['lease_token'],error='killed after receipt',ambiguous=True)
  with patch.object(self.transport,'submit',side_effect=AssertionError('No resubmit')):
   a=JournalAdapter(self.q,'kie',self.transport,mock=True)
   resumed=self.q.claim('restart')
   self.assertEqual(resumed['id'],self.j['id'])
   self.assertEqual(a.poll(resumed,resumed['provider_job_id'])['status'],'done')
if __name__=='__main__':unittest.main()
