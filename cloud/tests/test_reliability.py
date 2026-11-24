
from disk_test_support import DiskIndependentTestCase
import pathlib,tempfile,time,threading,unittest,subprocess,sys,json,os,signal
from unittest.mock import patch
from cloud.orchestrator import Queue,LeaseError
from reliability import renewing,reap,Cancelled
from hygiene import SCRATCH,guarded_run
class ReliabilityTests(DiskIndependentTestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(dir=SCRATCH);self.addCleanup(self.t.cleanup);self.p=pathlib.Path(self.t.name);self.plan=self.p/'plan.json';self.plan.write_text('{}');self.q=Queue(self.p/'q.sqlite',backoff_base=.001,backoff_max=.01);self.r=self.q.create_run(go=True,credit_cap='0')
 def job(self):return self.q.enqueue(self.r,'ad','mock',{},plan_path=self.plan,max_attempts=2)
 def test_long_work_renews_and_reaper_cannot_steal(self):
  clock=[1000.];self.q.clock=lambda:clock[0]
  self.job();j=self.q.claim('worker',lease_seconds=2)
  with renewing(self.q,j,lease_seconds=2) as guard:
   clock[0]+=1.5
   deadline=time.monotonic()+4
   while guard.renewals<1 and time.monotonic()<deadline:time.sleep(.01)
   self.assertGreaterEqual(guard.renewals,1)
   clock[0]+=1 # Past the original lease; inside the automatically extended one.
   self.assertEqual(reap(self.q)['expired'],0);guard.check()
  self.assertEqual(self.q.complete(j['id'],j['lease_token'])['state'],'done')
 def test_cancel_fences_and_stops_owned_subprocess(self):
  self.job();j=self.q.claim('w',lease_seconds=.2)
  def cancel():time.sleep(.12);self.q.cancel(j['id'])
  t=threading.Thread(target=cancel);t.start()
  try:
   with self.assertRaises(Cancelled):
    with renewing(self.q,j,lease_seconds=.2):guarded_run([sys.executable,'-c','import time;time.sleep(10)'],probe_seconds=.03)
  finally:t.join()
  self.assertEqual(self.q.get(j['id'])['state'],'cancelled')
 def test_poison_is_quarantined_with_history_and_no_retry(self):
  self.job()
  for n in range(2):
   j=self.q.claim('w');self.q.fail(j['id'],j['lease_token'],error='controlled failure');time.sleep(.02)
  report=reap(self.q);self.assertEqual(len(report['quarantined']),1);self.assertEqual(len(report['failures']),2);self.assertIsNone(self.q.claim('w'))
 def test_backoff_jitter_bounded_and_seedable(self):
  q=Queue(self.p/'q.sqlite',backoff_base=10,backoff_max=50,jitter=lambda:.5)
  self.assertEqual(q._delay(1),7.5);self.assertEqual(q._delay(30),37.5)
 def test_controller_sigkill_reaps_child_group(self):
  marker=self.p/'child.json';source="from hygiene import guarded_run;import sys;guarded_run([sys.executable,'-c','import time;time.sleep(30)'],lifecycle_path=sys.argv[1])"
  env={'PATH':'/usr/bin:/bin','PYTHONPATH':str(SCRATCH.parent),'HOME':str(self.p),'TMPDIR':str(self.p)}
  parent=subprocess.Popen([sys.executable,'-c',source,str(marker)],env=env)
  try:
   end=time.monotonic()+5
   # Wait for the first complete line, not just the file: the writer creates it before writing (Task19 flaky fix).
   while not (marker.exists() and '\n' in marker.read_text()) and time.monotonic()<end:time.sleep(.02)
   self.assertTrue(marker.exists() and '\n' in marker.read_text());child=json.loads(marker.read_text().splitlines()[0])['child_pid'];os.kill(parent.pid,signal.SIGKILL);parent.wait()
   end=time.monotonic()+5
   while time.monotonic()<end:
    try:os.kill(child,0)
    except ProcessLookupError:break
    time.sleep(.03)
   else:self.fail('Owned child survived controller SIGKILL')
  finally:
   if parent.poll() is None:parent.kill();parent.wait()
if __name__=='__main__':unittest.main()

class TargetedCleanupTests(DiskIndependentTestCase):
 def test_exact_name_cleanup_leaves_unselected_and_protected(self):
  from hygiene import clean_scratch
  with tempfile.TemporaryDirectory(dir=SCRATCH) as td:
   root=pathlib.Path(td)
   for n in ['own','other','protected']:(root/n).mkdir()
   (root/'protected/.keep').write_text('')
   listing=clean_scratch(root=root,age_hours=0,names=['own','protected']);self.assertEqual([v['name'] for v in listing['candidates']],['own'])
   clean_scratch(root=root,age_hours=0,names=['own','protected'],go=True);self.assertTrue((root/'other').exists());self.assertTrue((root/'protected').exists());self.assertFalse((root/'own').exists())
   with self.assertRaises(ValueError):clean_scratch(root=root,age_hours=0,names=['../escape'],go=True)
