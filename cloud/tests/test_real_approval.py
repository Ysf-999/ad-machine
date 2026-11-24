
from disk_test_support import DiskIndependentTestCase
import copy,json,pathlib,unittest
from unittest.mock import patch
import test_approval as fixtures
KEY=fixtures.KEY
from cloud import approval as a
class RealApprovalTests(DiskIndependentTestCase):
 setUp=fixtures.ApprovalTests.setUp
 write=staticmethod(fixtures.ApprovalTests.write)
 files=staticmethod(fixtures.ApprovalTests.files)
 tree=fixtures.ApprovalTests.tree
 plan=fixtures.ApprovalTests.plan
 decision=fixtures.ApprovalTests.decision
 apply=fixtures.ApprovalTests.apply
 checks=fixtures.ApprovalTests.checks
 def test_production_validator_accepts_only_complete_in_memory_test_fixture(self):
  self.apply();self.checks();decision=self.decision(phase='final')
  result=a.apply_decision(self.project,decision,key=KEY);self.assertTrue(result['approved'])
  # Actual file remains unanswered even though the synthetic unit read is completed.
  raw=(self.project/'PREFLIGHT.md').read_bytes().decode();self.assertIn('- [ ] Taste',raw);self.assertNotIn('- [x]',raw)
  with self.assertRaises(a.ApprovalError):a.apply_decision(self.project,decision,key=KEY)
 def test_mock_decision_and_different_master_and_locked_and_under_evidenced_rejected(self):
  from cloud.workflow import Workflow
  mock=Workflow.submit(self.root/'mock-domain',{'mock':True,'cap':'3','limits':{'kie':1,'elevenlabs':1,'ffmpeg':1},'ads':[{'id':'mock','beats':[1]}]})
  mock.drain_mock();mock_signed=mock.sign('mock','frames',1,'approve',key=KEY)
  mock.apply(mock_signed,key=KEY)  # Actual valid mock-domain decision, same test key.
  with self.assertRaises(a.ApprovalError):a.apply_decision(self.project,mock_signed,key=KEY)
  with self.assertRaises(a.ApprovalError):self.decision(phase='final')
  self.apply();self.checks();d=self.decision(phase='final')
  self.write(self.project,'MASTER.mp4',b'other master')
  with self.assertRaises(a.ApprovalError):a.apply_decision(self.project,d,key=KEY)
  p=self.plan();p['locked']=True;self.write(self.project,'plan.json',json.dumps(p))
  with self.assertRaises(a.ApprovalError):a.apply_decision(self.project,d,key=KEY)
 def test_automated_evidence_accepts_exact_output_without_answering_manual_boxes(self):
  self.synthetic_checklists.clear()
  self.write(self.project,'QC/caption.txt','CAPTION SYNC PASS')
  self.write(self.project,'QC/av.txt','PASS: sound and picture in sync')
  self.write(self.project,'PREFLIGHT.md','master: MASTER.mp4\nfingerprint: '+a.preflight_fingerprint(self.project/'MASTER.mp4')+'\n## Automatic checks\n- PASS format 1080x1920\n- PASS T13 no tilt\n- PASS T09 no repeats\n- PASS T24 cuts\n- PASS T23 no freeze\n- PASS T06 no banned references\n- PASS T19 quiet tail\n- PASS av_check\n- PASS T17 CAPTION SYNC PASS\n## Owner taste rules\n- [ ] Owner visual review\n')
  sha=a._digest(self.project/'MASTER.mp4');reports={'caption_sync':'QC/caption.txt','av_check':'QC/av.txt','preflight':'PREFLIGHT.md'}
  a.record_automated_review(self.project,reports,master_sha256=sha,returncodes={n:0 for n in reports})
  r=a.automated_review_status(self.project);self.assertEqual(r['state'],'awaiting_final_review');self.assertFalse(r['approved'])
  self.assertIn('- [ ] Owner visual review',(self.project/'PREFLIGHT.md').read_bytes().decode())
  with self.assertRaises(a.ApprovalError):self.decision(phase='final')
  self.write(self.project,'MASTER.mp4',b'new master')
  self.assertEqual(a.automated_review_status(self.project)['state'],'blocked')
if __name__=='__main__':unittest.main()
