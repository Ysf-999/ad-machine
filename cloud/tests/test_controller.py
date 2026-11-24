from disk_test_support import DiskIndependentTestCase
import json,pathlib,tempfile,unittest
from cloud.orchestrator import Queue
from cloud.post_cloud import PostCloudGate
from cloud.runner.stage import digest
try:
 from cloud.worker.controller import Controller
except ImportError:Controller=None
C=pathlib.Path(__file__).resolve().parents[1]
class ControllerTests(DiskIndependentTestCase):
 def setUp(self):
  super().setUp();self.assertIsNotNone(Controller)
  t=tempfile.TemporaryDirectory(dir=C/'.scratch');self.addCleanup(t.cleanup);self.p=pathlib.Path(t.name)
  self.plan=self.p/'plan.json';self.plan.write_text('{}')
  self.q=Queue(self.p/'q.sqlite',provider_limits={'modal':1,'kie':1},backoff_base=0)
  self.run=self.q.create_run(go=True,credit_cap='.4')
 def add(self,name='a',stage='render',provider='modal'):
  return self.q.enqueue(self.run,name,stage,{'sha':'a'*64},plan_path=self.plan,provider=provider,known_cost='.1')
 def adapter(self):
  q=self.q;run=self.run;calls=[]
  class Adapter:
   mock=True
   def submit(s,j):
    assert q.get(j['id'])['submission_started'] and q.run_status(run)['reserved']!='0'
    calls.append(j['id']);return 'receipt-'+j['id']
   def poll(s,j,r):
    assert q.poll_ready(j['id'],j['lease_token'])==r
    return {'status':'done','result':{'master':{'sha256':digest(self.p/'MASTER.mp4')},'deliverable':False}}
  return Adapter(),calls
 def gate(self,job,result):
  pf=self.p/'PREFLIGHT.md';pf.write_text('## Automatic checks\n- PASS T13 no tilted text found\n## Owner taste rules\n- [ ] Review\n')
  checks={'caption_sync':{'returncode':0,'output':'CAPTION SYNC PASS'},'av_check':{'returncode':0,'output':'PASS: sound and picture in sync'},'preflight':{'returncode':0,'output':'0 FAIL, 0 WARN'},'preflight_path':str(pf)}
  return PostCloudGate(self.p/'receipts').run(self.p/'MASTER.mp4',result['master']['sha256'],'unit',lambda:checks)
 def test_durable_reserve_id_before_gate_and_approval_parking(self):
  (self.p/'MASTER.mp4').write_bytes(b'synthetic unit master');a,calls=self.adapter();job=self.add()
  ctl=Controller(self.q,{'modal':a},post_cloud_gate=self.gate)
  rows=ctl.drain(max_steps=5)
  self.assertEqual(len(rows),1);self.assertEqual(calls,[job['id']]);self.assertEqual(rows[0]['state'],'awaiting_approval')
  self.assertFalse(rows[0]['result']['deliverable']);self.assertFalse(rows[0]['result']['approved'])
  self.assertIn('- [ ] Review',(self.p/'PREFLIGHT.md').read_text());self.assertEqual(ctl.drain(max_steps=5),[])
 def test_missing_gate_fails_closed_and_no_automatic_paid_calls(self):
  (self.p/'MASTER.mp4').write_bytes(b'unit');a,calls=self.adapter();job=self.add()
  row=Controller(self.q,{'modal':a}).drain(max_steps=1)[0]
  self.assertEqual(row['state'],'failed');self.assertFalse(row['result'] and row['result'].get('deliverable'))
  class RealPaid:
   def submit(s,j):raise AssertionError('must never reach sender')
  self.add('paid','vo','kie')
  row=Controller(self.q,{'kie':RealPaid()}).drain(max_steps=1)[0]
  self.assertEqual(row['state'],'failed');self.assertFalse(row['submission_started'])
 def test_provider_slot_remains_held_for_pending_id_and_not_resubmitted(self):
  self.add('a','vo');self.add('b','vo');seen=[]
  class Pending:
   mock=True
   def submit(s,j):seen.append(j['id']);return 'one'
   def poll(s,j,r):return {'status':'pending'}
  ctl=Controller(self.q,{'modal':Pending()});ctl.drain(max_steps=2)
  self.assertEqual(len(seen),1);self.assertEqual(sum(j['submission_started'] for j in self.q.jobs()),1)
  self.assertEqual(self.q.run_status(self.run)['reserved'],'0.1')
 def test_unknown_poll_error_keeps_remote_slot_and_prevents_new_submission(self):
  self.add('a','vo');self.add('b','vo');seen=[]
  class Unknown:
   mock=True
   def submit(s,j):seen.append(j['id']);return 'remote-unknown'
   def poll(s,j,r):raise TimeoutError('reply lost; remote may still be running')
  ctl=Controller(self.q,{'modal':Unknown()});ctl.drain(max_steps=2)
  self.assertEqual(len(seen),1)
  self.assertTrue(next(j for j in self.q.jobs() if j['provider_job_id'])['remote_open'])
