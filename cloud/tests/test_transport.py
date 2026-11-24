from disk_test_support import DiskIndependentTestCase
import base64,json,pathlib,tempfile,unittest
from unittest.mock import patch
from cloud.orchestrator import Queue,SubmissionAmbiguous
from cloud.providers.paid import JournalAdapter,RealCallsDisabled
try:
 from cloud.providers.transport import ReplayHTTP,KieTransport,ElevenTransport,RealHTTP
except ImportError:ReplayHTTP=KieTransport=ElevenTransport=RealHTTP=None
C=pathlib.Path(__file__).resolve().parents[1]
class TransportTests(DiskIndependentTestCase):
 def setUp(self):
  super().setUp();self.assertIsNotNone(ReplayHTTP)
  t=tempfile.TemporaryDirectory(dir=C/'.scratch');self.addCleanup(t.cleanup);self.p=pathlib.Path(t.name)
 def job(self,provider,request):
  plan=self.p/'plan.json';plan.write_text('{}');q=Queue(self.p/'q.sqlite',provider_limits={provider:1},backoff_base=0)
  run=q.create_run(go=True,credit_cap='.25');q.enqueue(run,'ad','vo' if provider=='elevenlabs' else 'mock',{'provider_request':request},plan_path=plan,provider=provider,known_cost='.2')
  job=q.claim('unit');q.prepare_submission(job['id'],job['lease_token']);return q,job
 def test_kie_api_shapes_inside_existing_durable_journal(self):
  q,j=self.job('kie',{'model':'unit-model','input':{'prompt':'unit'}})
  http=ReplayHTTP([{'code':200,'data':{'taskId':'unit-task'}},{'code':200,'data':{'taskId':'unit-task','state':'success','resultJson':json.dumps({'resultUrls':['https://redacted.invalid/out.mp4']})}}])
  a=JournalAdapter(q,'kie',KieTransport(http),mock=True)
  with patch('socket.socket',side_effect=AssertionError('No network')):
   rid=a.submit(j);result=a.poll(q.get(j['id']),rid)
  self.assertEqual(result['status'],'done');self.assertFalse(result['result']['deliverable'])
  self.assertIn('taskId',(self.p/'jobs.jsonl').read_text());self.assertEqual(http.requests[1]['params'],{'taskId':'unit-task'})
  with self.assertRaises(SubmissionAmbiguous):a.submit(j)
 def test_kie_pending_failure_and_wrong_receipt_are_distinct(self):
  t=KieTransport(ReplayHTTP([{'code':200,'data':{'taskId':'id','state':'generating'}},{'code':200,'data':{'taskId':'id','state':'fail'}},{'code':200,'data':{'taskId':'other','state':'success'}}]))
  self.assertEqual(t.poll({},'id')['status'],'pending');self.assertEqual(t.poll({},'id')['status'],'failed')
  with self.assertRaises(ValueError):t.poll({},'id')
 def test_eleven_synchronous_receipt_survives_restart_without_second_call(self):
  q,j=self.job('elevenlabs',{'voice_id':'unit-voice','text':'Hi','voice_settings':{}})
  response={'audio_base64':base64.b64encode(b'synthetic unit audio').decode(),'alignment':{'characters':['H','i'],'character_start_times_seconds':[0,.1],'character_end_times_seconds':[.1,.2]}}
  http=ReplayHTTP([response]);t=ElevenTransport(http,self.p/'receipts');a=JournalAdapter(q,'elevenlabs',t,mock=True)
  rid=a.submit(j);self.assertTrue(rid.startswith('local-eleven-'))
  restarted=ElevenTransport(ReplayHTTP([]),self.p/'receipts')
  self.assertEqual(restarted.poll(j,rid)['status'],'done');self.assertEqual(len(http.requests),1)
  self.assertIn('/with-timestamps',http.requests[0]['url'])
 def test_invalid_eleven_response_fails_without_an_invented_receipt(self):
  t=ElevenTransport(ReplayHTTP([{'audio_base64':'bad!','alignment':{}}]),self.p/'receipts')
  with self.assertRaises(ValueError):t.submit({'inputs':{'provider_request':{'voice_id':'unit','text':'Hi','voice_settings':{}}}})
  self.assertEqual(list((self.p/'receipts').glob('*.json')),[])
 def test_actual_http_and_real_adapter_refuse_even_with_go(self):
  with patch('socket.socket',side_effect=AssertionError('No socket')):
   for go in [False,True]:
    with self.assertRaises(RealCallsDisabled):RealHTTP(go=go).request('POST','https://redacted.invalid',json={})
    with self.assertRaises(RealCallsDisabled):JournalAdapter.real('kie',go=go)
 def test_no_transport_called_until_queue_has_reserved_spend(self):
  q,j=self.job('kie',{'model':'unit','input':{}});http=ReplayHTTP([]);a=JournalAdapter(q,'kie',KieTransport(http),mock=True)
  with q._tx() as db:db.execute('UPDATE jobs SET submission_started=0,remote_open=0')
  with self.assertRaises(Exception):a.submit(j)
  self.assertEqual(http.requests,[])
