"""Real signing/parser/application path with synthetic assets; no approvals."""
from disk_test_support import DiskIndependentTestCase
import json,pathlib,tempfile,unittest
from unittest.mock import patch
from cloud import approval
from cloud.review_service import authenticated_application
C=pathlib.Path(__file__).resolve().parents[1]
class BundleIntegrationTests(DiskIndependentTestCase):
 def test_private_bundle_and_signed_revision_without_a_listener_or_approval(self):
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as td:
   root=pathlib.Path(td);source=root/'source';source.mkdir()
   files={'plan.json':json.dumps({'ad':'unit','beats':[{'n':1,'vo':'unit'}]}),'MASTER.mp4':'synthetic unit master','REVIEW.html':'<a href="MASTER.mp4">Unit</a><img src="FRAMES/scene_01.png">','FRAMES/scene_01.png':'synthetic frame','PREFLIGHT.md':'## Owner taste rules\n- [ ] Review\n'}
   for name,value in files.items():p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
   project=approval.stage_project(source,list(files))
   # Keep all unit assets inside this TemporaryDirectory's owned lifetime.
   moved=root/'review';project.rename(moved);project=moved
   decision_key=b'synthetic-decision-key-32-bytes!!!';access_key=b'synthetic-access-key-different!!!'
   class Flow:
    def project(s,ad):
     if ad!='unit':raise ValueError('Unknown ad')
     return project
    def apply(s,decision,*,key):return approval.apply_decision(project,decision,key=key)
   app=authenticated_application(Flow(),decision_key=decision_key,access_key=access_key,database=root/'auth.sqlite',origin='https://unit.invalid')
   original=(source/'plan.json').read_bytes()
   with patch('socket.socket',side_effect=AssertionError('No sockets')):
    self.assertEqual(app.handle('GET','/ads/unit/MASTER.mp4')[0],403)
    token=app.auth.issue('unit','view');status,h,_=app.handle('GET','/ads/unit/REVIEW.html?access='+token)
    self.assertEqual(status,302);cookie=h['Set-Cookie'].split(';')[0]
    status,_,body=app.handle('GET','/ads/unit/MASTER.mp4',headers={'Cookie':cookie});self.assertEqual(status,200);self.assertEqual(body,b'synthetic unit master')
    self.assertEqual(app.handle('GET','/ads/unit/plan.json',headers={'Cookie':cookie})[0],404)
    d=approval.sign_decision(project,'revise','frames',1,'synthetic unit revision',key=decision_key,kind='frame')
    token=app.auth.issue('unit','decision');headers={'Origin':'https://unit.invalid','Authorization':'Bearer '+token}
    status,_,_=app.handle('POST','/ads/unit/decision',json.dumps(d).encode(),headers=headers);self.assertEqual(status,200)
    self.assertEqual(app.handle('POST','/ads/unit/decision',json.dumps(d).encode(),headers=headers)[0],403)
   self.assertFalse(approval.status(project)['approved']);self.assertEqual((source/'plan.json').read_bytes(),original)
   self.assertEqual((project/'PREFLIGHT.md').read_text(),files['PREFLIGHT.md'])
