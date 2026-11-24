
from disk_test_support import DiskIndependentTestCase
import pathlib,tempfile,json,unittest
from cloud.review_auth import Auth,SecureApplication,Denied
from hygiene import SCRATCH
KEY=b'view-access-key-unit-test-only!!!'
class ReviewAuthTests(DiskIndependentTestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(dir=SCRATCH);self.addCleanup(self.t.cleanup);self.p=pathlib.Path(self.t.name);self.now=1000;self.auth=Auth(self.p/'auth.sqlite',key=KEY,clock=lambda:self.now,limit=50)
  class App:
   key=b'different-production-key-only-unit'
   def __init__(s):s.calls=[]
   def handle(s,method,path,body=b''):s.calls.append((method,path,body));return 200,{},b'unit'
  self.app=App();self.secure=SecureApplication(self.app,self.auth,origin='https://unit.invalid',workspace_for=lambda ad:'workspace-'+ad)
 def test_scoped_one_time_view_link_exchanges_private_cookie(self):
  token=self.auth.issue('a','view');status,h,b=self.secure.handle('GET','/ads/a/REVIEW.html?access='+token)
  self.assertEqual(status,302);self.assertIn('HttpOnly',h['Set-Cookie']);self.assertIn('Secure',h['Set-Cookie']);cookie=h['Set-Cookie'].split(';')[0]
  self.assertEqual(self.secure.handle('GET','/ads/a/MASTER.mp4',headers={'Cookie':cookie})[0],200)
  self.assertEqual(self.secure.handle('GET','/ads/b/MASTER.mp4',headers={'Cookie':cookie})[0],403)
  self.assertEqual(self.secure.handle('GET','/ads/a/REVIEW.html?access='+token)[0],403)
 def test_expired_tampered_wrong_scope_and_cross_ad_refused(self):
  token=self.auth.issue('a','view');self.now+=61
  with self.assertRaises(Denied):self.auth.consume(token,'a','view')
  token=self.auth.issue('a','view')
  for token2,ad,scope in [(token+'x','a','view'),(token,'b','view'),(token,'a','decision')]:
   with self.assertRaises(Denied):self.auth.consume(token2,ad,scope)
 def test_decision_requires_scoped_auth_and_existing_signed_body_binding(self):
  token=self.auth.issue('a','decision');body=json.dumps({'payload':{'workspace_id':'workspace-a'},'signature':'unit-not-production'}).encode();headers={'Authorization':'Bearer '+token,'Origin':'https://unit.invalid'}
  self.assertEqual(self.secure.handle('POST','/ads/b/decision',body,headers=headers)[0],403);self.assertEqual(self.app.calls,[])
  self.assertEqual(self.secure.handle('POST','/ads/a/decision',body,headers=headers)[0],200);self.assertEqual(self.app.calls[0][1],'/decision')
  self.assertEqual(self.secure.handle('POST','/ads/a/decision',body,headers=headers)[0],403)
 def test_rate_limit_audit_does_not_store_tokens_or_body(self):
  auth=Auth(self.p/'limited.sqlite',key=KEY,clock=lambda:self.now,limit=2);app=SecureApplication(self.app,auth,origin='https://unit.invalid',workspace_for=lambda a:'x')
  for _ in range(2):self.assertEqual(app.handle('GET','/ads/a/MASTER.mp4',peer='unit-peer')[0],403)
  self.assertEqual(app.handle('GET','/ads/a/MASTER.mp4',peer='unit-peer')[0],429)
  raw=(self.p/'limited.sqlite').read_bytes();self.assertNotIn(b'unit-peer',raw)
 def test_no_unauthenticated_root_traversal_or_cookie_decision(self):
  self.assertEqual(self.secure.handle('GET','/')[0],404)
  self.assertEqual(self.secure.handle('GET','/ads/a/%2e%2e/plan.json')[0],404)
  self.assertEqual(self.secure.handle('POST','/ads/a/decision',b'{}',headers={'Cookie':'review-session=anything'})[0],403)

 def test_private_plan_and_key_rotation_session_refused(self):
  token=self.auth.issue('a','view');status,headers,_=self.secure.handle('GET','/ads/a/REVIEW.html?access='+token);cookie=headers['Set-Cookie'].split(';')[0]
  self.assertEqual(self.secure.handle('GET','/ads/a/plan.json',headers={'Cookie':cookie})[0],404)
  other=Auth(self.p/'auth.sqlite',key=b'rotated-unit-access-key-xxxxxxxxxx',clock=lambda:self.now)
  secured=SecureApplication(self.app,other,origin='https://unit.invalid',workspace_for=lambda a:'workspace-'+a)
  self.assertEqual(secured.handle('GET','/ads/a/MASTER.mp4',headers={'Cookie':cookie})[0],403)
