"""Task B: mocked subprocess/SDK only; no real plan or model execution."""
from disk_test_support import DiskIndependentTestCase

import contextlib,importlib.util,json,os,pathlib,shutil,socket,subprocess,sys,tempfile,unittest
from unittest.mock import Mock,MagicMock,patch
from test_llm import load_client,scratch_directory,ROOT,SCRATCH,REQUEST

class StreamTests(DiskIndependentTestCase):
 def setUp(self):
  self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
  self.c=load_client(ROOT/'tools/claude_client.py','stream_client_'+str(id(self)))
  self.stack.enter_context(patch.dict(os.environ,{},clear=True));self.stack.enter_context(patch.dict(self.c._STATE,{'use':'cli'}))
  self.stack.enter_context(patch.object(tempfile,'TemporaryDirectory',side_effect=scratch_directory))
  self.stack.enter_context(patch.object(socket,'socket',side_effect=AssertionError('No network')))
  self.stack.enter_context(patch.object(subprocess,'Popen',side_effect=AssertionError('No subprocess launch')))
  self.run=self.stack.enter_context(patch.object(subprocess,'run',return_value=Mock(stdout=json.dumps({'result':'hello world','usage':{'input_tokens':9,'output_tokens':3}}),stderr='',returncode=0)))
  self.env=self.stack.enter_context(patch.object(self.c,'_env',return_value=None))
  self.sdk=Mock();self.stack.enter_context(patch.object(self.c,'_real',self.sdk))
  self.manager=MagicMock();self.native=Mock();self.manager.__enter__.return_value=self.native
  self.sdk.Anthropic.return_value.messages.stream.return_value=self.manager
  self.native.get_final_message.return_value=self.c._Resp('API hello',1,2,'end_turn')
  self.native.text_stream=iter(['API ','hello'])
 def test_cli_context_buffers_one_mocked_subprocess(self):
  stream=self.c.Anthropic().messages.stream(**REQUEST);self.run.assert_not_called()
  with stream as s:
   r=s.get_final_message();self.assertIs(s.get_final_message(),r)
   self.assertEqual(list(s.text_stream),['hello world']);self.assertEqual(s.get_final_text(),'hello world')
  self.run.assert_called_once();self.sdk.Anthropic.assert_not_called();self.env.assert_not_called()
  self.assertIn('claude',self.run.call_args.args[0]);self.assertEqual(r.usage.input_tokens,9)
  with self.assertRaises(RuntimeError):s.get_final_message()
 def test_cli_error_is_not_fake_message(self):
  self.run.return_value.stdout=json.dumps({'is_error':True,'result':'mock failure'})
  with self.assertRaises(RuntimeError):
   with self.c.Anthropic().messages.stream(**REQUEST):pass
  self.run.assert_called_once()
 def test_api_healthy_delegates_exact_sdk_stream_and_context(self):
  self.c._STATE['use']='api'
  with self.c.Anthropic(timeout=123).messages.stream(**REQUEST) as s:
   self.assertIs(s.get_final_message(),self.native.get_final_message.return_value)
   self.assertEqual(list(s.text_stream),['API ','hello'])
  self.sdk.Anthropic.assert_called_once_with(timeout=123)
  self.sdk.Anthropic.return_value.messages.stream.assert_called_once_with(**REQUEST)
  self.sdk.Anthropic.return_value.messages.create.assert_not_called();self.run.assert_not_called()
  self.manager.__exit__.assert_called_once_with(None,None,None)
 def test_api_context_does_not_suppress_caller_exception(self):
  self.c._STATE['use']='api';self.manager.__exit__.return_value=False
  with self.assertRaisesRegex(ValueError,'caller'):
   with self.c.Anthropic().messages.stream(**REQUEST):raise ValueError('caller')
  self.assertIs(self.manager.__exit__.call_args.args[0],ValueError);self.run.assert_not_called()
 def test_auto_dry_on_enter_falls_back_once_and_sticks(self):
  self.c._STATE['use']='auto';self.manager.__enter__.side_effect=RuntimeError('credit balance depleted')
  with self.c.Anthropic().messages.stream(**REQUEST) as s:self.assertEqual(s.get_final_text(),'hello world')
  self.assertEqual(self.c.backend(),'cli');self.run.assert_called_once();self.manager.__exit__.assert_not_called()
  with self.c.Anthropic().messages.stream(**REQUEST) as s:s.get_final_message()
  self.assertEqual(self.run.call_count,2);self.assertEqual(self.sdk.Anthropic.call_count,1)
 def test_auto_dry_during_final_closes_sdk_then_buffers_cli(self):
  self.c._STATE['use']='auto';self.native.get_final_message.side_effect=RuntimeError('authentication invalid x-api-key')
  with self.c.Anthropic().messages.stream(**REQUEST) as s:self.assertEqual(s.get_final_text(),'hello world')
  self.run.assert_called_once();self.manager.__exit__.assert_called_once();self.assertEqual(self.c.backend(),'cli')
 def test_forced_api_and_noncredit_errors_never_fallback(self):
  for mode,error in [('api','credit balance'),('auto','network timeout')]:
   self.c._STATE['use']=mode;self.manager.__enter__.side_effect=RuntimeError(error)
   with self.assertRaises(RuntimeError):
    with self.c.Anthropic().messages.stream(**REQUEST):pass
  self.run.assert_not_called()
 def test_forced_api_final_error_propagates_and_closes(self):
  self.c._STATE['use']='api';self.native.get_final_message.side_effect=RuntimeError('credit balance depleted')
  self.manager.__exit__.return_value=False
  with self.assertRaises(RuntimeError):
   with self.c.Anthropic().messages.stream(**REQUEST) as s:s.get_final_message()
  self.run.assert_not_called();self.manager.__exit__.assert_called_once();self.assertEqual(self.c.backend(),'api')
 def test_partial_api_text_is_never_replayed_via_cli(self):
  self.c._STATE['use']='auto';self.manager.__exit__.return_value=False
  def chunks():
   yield 'partial'
   raise RuntimeError('credit balance late failure')
  self.native.text_stream=chunks()
  with self.assertRaises(RuntimeError):
   with self.c.Anthropic().messages.stream(**REQUEST) as s:
    it=s.text_stream;self.assertEqual(next(it),'partial');next(it)
  self.run.assert_not_called();self.assertEqual(self.c.backend(),'auto');self.manager.__exit__.assert_called_once()
 def test_skip_and_disabled_token_raise_not_checked(self):
  for mode in ['skip','token-cli']:
   self.c._STATE['use']=mode
   with self.assertRaises(RuntimeError) as r:
    with self.c.Anthropic().messages.stream(**REQUEST):pass
   self.assertEqual(r.exception.check_status,'not_checked')
  self.run.assert_not_called();self.sdk.Anthropic.assert_not_called()
 def test_logging_on_cli_fallback_is_one_metadata_record(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'calls.jsonl';os.environ['CLAUDE_CALL_LOG']=str(p)
   with self.c.Anthropic().messages.stream(purpose='plan_review',**REQUEST) as s:s.get_final_message()
   records=[json.loads(x) for x in p.read_text().splitlines()];self.assertEqual(len(records),1)
   self.assertEqual(records[0]['purpose'],'plan_review');self.assertEqual(records[0]['status'],'ok')
 def test_stream_default_log_purpose_is_calling_module(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'calls.jsonl';os.environ['CLAUDE_CALL_LOG']=str(p)
   with self.c.Anthropic().messages.stream(**REQUEST) as s:s.get_final_message()
   self.assertEqual(json.loads(p.read_text())['purpose'],'test_stream')
 def test_context_single_use_and_final_requires_entry(self):
  s=self.c.Anthropic().messages.stream(**REQUEST)
  with self.assertRaises(RuntimeError):s.get_final_message()
  with s:s.get_final_message()
  with self.assertRaises(RuntimeError):
   with s:pass
  self.run.assert_called_once()
 def test_real_plan_review_code_with_synthetic_copy_and_mocked_cli(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);tools=root/'tools';tools.mkdir();p=tools/'plan_review.py'
   shutil.copyfile(ROOT/'tools/plan_review.py',p)
   project=root/'synthetic';project.mkdir();plan={'ad':'synthetic-test','style':'test','beats':[{'n':1,'vo':'test','visual':'a synthetic visual'}]}
   (project/'plan.json').write_text(json.dumps(plan));before=(project/'plan.json').read_bytes()
   self.run.return_value.stdout=json.dumps({'result':json.dumps({'summary':'mock only','beats':[{'n':1,'issues':[],'visual':'a synthetic visual','motion':'test'}]}),'usage':{}})
   spec=importlib.util.spec_from_file_location('synthetic_plan_review',p);module=importlib.util.module_from_spec(spec)
   with patch.object(sys,'path',list(sys.path)),patch.dict(sys.modules,{'claude_client':self.c}),patch.object(sys,'argv',[str(p),str(project)]),contextlib.redirect_stdout(__import__('io').StringIO()):
    spec.loader.exec_module(module);module.main()
   self.assertIn('mock only',(project/'QC/plan_review.md').read_text());self.assertEqual((project/'plan.json').read_bytes(),before)
   self.run.assert_called_once()
if __name__=='__main__':unittest.main()
