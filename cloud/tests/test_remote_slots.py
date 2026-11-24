
from disk_test_support import DiskIndependentTestCase
import pathlib,tempfile,unittest
from cloud.orchestrator import Queue
C=pathlib.Path(__file__).resolve().parents[1]
class RemoteSlotTests(DiskIndependentTestCase):
 def test_expired_lease_does_not_free_remote_slot(self):
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as t:
   p=pathlib.Path(t);plan=p/'plan.json';plan.write_text('{}');now=[1000]
   q=Queue(p/'q.sqlite',provider_limits={'kie':1},clock=lambda:now[0],backoff_base=0)
   r=q.create_run(go=True,credit_cap='2')
   one=q.enqueue(r,'one','mock',{},plan_path=plan,provider='kie',known_cost='1',max_attempts=10)
   q.enqueue(r,'two','mock',{},plan_path=plan,provider='kie',known_cost='1')
   j=q.claim('w',lease_seconds=1);q.prepare_submission(j['id'],j['lease_token']);q.record_provider_job(j['id'],j['lease_token'],'remote')
   now[0]+=2;q.recover_expired();resume=q.claim('restart')
   self.assertEqual(resume['id'],one['id']);self.assertIsNone(q.claim('other'))
   q.cancel(one['id']);self.assertIsNone(q.claim('other'))
if __name__=='__main__':unittest.main()
