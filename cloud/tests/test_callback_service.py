
from disk_test_support import DiskIndependentTestCase
import pathlib,tempfile,unittest,json
from types import SimpleNamespace
from cloud.callback_service import Service,Client,gate_state,LLM_GATES
from cloud.llm import create,NotCheckedError
from hygiene import SCRATCH
KEY=b'callback-unit-test-key-not-real!!'
class CallbackTests(DiskIndependentTestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(dir=SCRATCH);self.addCleanup(self.t.cleanup);self.p=pathlib.Path(self.t.name);self.calls=[];self.now=1000
  def cli(**request):self.calls.append(request);return SimpleNamespace(content=[SimpleNamespace(text='FAIL: unit result')],usage=SimpleNamespace(input_tokens=2,output_tokens=3),stop_reason='end_turn')
  self.service=Service(self.p/'service.sqlite',key=KEY,cli=cli,models={'unit-model'},clock=lambda:self.now)
 def request(self):return {'version':1,'request':{'model':'unit-model','max_tokens':10,'messages':[{'role':'user','content':'unit'}]}}
 def test_signed_mock_roundtrip_has_no_implicit_pass(self):
  client=Client(self.service.handle,key=KEY,clock=lambda:self.now);r=create(backend='callback',cli=None,callback=client,**self.request()['request']);self.assertEqual(r.check_status,'checked');self.assertEqual(r.content[0].text,'FAIL: unit result');self.assertEqual(len(self.calls),1)
 def test_invalid_auth_expiry_replay_rejected_before_cli(self):
  client=Client(self.service.handle,key=KEY,clock=lambda:self.now);body,headers=client.signed(self.request())
  bad=dict(headers);bad['X-Signature']='0'*64;self.assertEqual(self.service.handle(body,bad)[0],403);self.assertEqual(self.calls,[])
  self.assertEqual(self.service.handle(body,headers)[0],200);self.assertEqual(self.service.handle(body,headers)[0],409);self.assertEqual(len(self.calls),1)
  body,headers=client.signed(self.request());self.now+=301;self.assertEqual(self.service.handle(body,headers)[0],403)
 def test_error_is_not_checked_and_is_never_retried(self):
  def broken(**kw):raise RuntimeError('private error')
  self.service.cli=broken;client=Client(self.service.handle,key=KEY,clock=lambda:self.now)
  with self.assertRaises(NotCheckedError):create(backend='callback',cli=None,callback=client,**self.request()['request'])
 def test_skip_propagates_all_dependent_gates_without_recording_pass(self):
  state=gate_state({name:{'check_status':'not_checked','verdict':'PASS'} for name in LLM_GATES})
  for name in ['plan_review','qc','masterqc','semantic_broll','final','hooks','deliver','upload']:self.assertNotEqual(state[name]['status'],'passed')
  state=gate_state({'qc':{'check_status':'checked','verdict':'FAIL'}});self.assertEqual(state['qc']['status'],'failed');self.assertEqual(state['final']['status'],'blocked')
