
from disk_test_support import DiskIndependentTestCase
import json,pathlib,tempfile,unittest
from unittest.mock import patch
from cloud.workflow import Workflow
from cloud.review_service import Application
from cloud.notifications import build
C=pathlib.Path(__file__).resolve().parents[1];KEY=b'r'*32
class ServiceTests(DiskIndependentTestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(dir=C/'.scratch');self.addCleanup(self.t.cleanup);self.p=pathlib.Path(self.t.name)
  self.f=Workflow.submit(self.p/'flow',{'mock':True,'cap':'20','limits':{'kie':1,'elevenlabs':1,'ffmpeg':1},'ads':[{'id':'x','beats':[1]}]});self.f.drain_mock();self.app=Application(self.f,key=KEY)
 def test_board_and_bundle_without_binding_socket(self):
  with patch('socket.socket',side_effect=AssertionError('No sockets')):
   self.assertEqual(self.app.handle('GET','/')[0],200);self.assertEqual(self.app.handle('GET','/ads/x/REVIEW.html')[0],200)
 def test_signed_post_same_cli_decision_file_and_replay(self):
  d=self.f.sign('x','frames',1,'approve',key=KEY);body=json.dumps(d).encode()
  self.assertEqual(self.app.handle('POST','/decision',body)[0],200)
  self.assertEqual(json.loads((self.f.root/'decisions'/(d['payload']['id']+'.json')).read_text()),d)
  self.assertEqual(self.app.handle('POST','/decision',body)[0],409)
 def test_invalid_expired_traversal_and_large_body_rejected(self):
  self.assertEqual(self.app.handle('POST','/decision',b'{}')[0],409)
  self.assertEqual(self.app.handle('GET','/%2e%2e/workflow.json')[0],404)
  self.assertEqual(self.app.handle('GET','/workflow.json')[0],404)
  self.assertEqual(self.app.handle('POST','/decision',b'x'*70000)[0],413)
  d=self.f.sign('x','frames',1,'approve',key=KEY,ttl=-1)
  self.assertEqual(self.app.handle('POST','/decision',json.dumps(d).encode())[0],409)
 def test_notifications_exact_text_and_never_execute(self):
  with patch('subprocess.run',side_effect=AssertionError('Must not send')),patch('cloud.notifications.names.config',return_value={'slack_user_id':'U0TESTUSER'}):
   x=build('x','awaiting_approval','http://127.0.0.1:8765/ads/x/REVIEW.html',gate='frames')
   self.assertEqual(x['text'],'<@U0TESTUSER> Ad x awaiting approval at gate frames. Review: http://127.0.0.1:8765/ads/x/REVIEW.html')
   self.assertTrue(x['dry_run']);self.assertEqual(build('x','failed','http://127.0.0.1:8765/')['text'],'<@U0TESTUSER> Ad x failed. Review: http://127.0.0.1:8765/')
if __name__=='__main__':unittest.main()

class HandlerTests(DiskIndependentTestCase):
 def test_handler_delegates_without_opening_socket(self):
  import io
  from cloud.review_service import handler_for
  class FakeApplication:
   def handle(self,method,path,body):return 200,{'Content-Type':'application/json'},b'{}'
  h=handler_for(FakeApplication()).__new__(handler_for(FakeApplication()))
  h.command='POST';h.path='/decision';h.headers={'Content-Length':'2'};h.rfile=io.BytesIO(b'{}');h.wfile=io.BytesIO();codes=[]
  h.send_response=lambda c:codes.append(c);h.send_header=lambda *x:None;h.end_headers=lambda:None
  h.do_POST();self.assertEqual(codes,[200]);self.assertEqual(h.wfile.getvalue(),b'{}')
 def test_serve_dry_run_does_not_bind(self):
  from cloud.review_service import main
  with patch('cloud.review_service.ThreadingHTTPServer',side_effect=AssertionError('No listener')),patch('sys.stdout'):
   self.assertEqual(main(['/unused','--port','8765']),0)
