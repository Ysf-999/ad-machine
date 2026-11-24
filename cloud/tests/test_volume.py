
from disk_test_support import DiskIndependentTestCase
import json,pathlib,tempfile,unittest
from cloud.workflow import Workflow,GRAPHS
from cloud.orchestrator import GateError,SubmissionAmbiguous
from cloud.providers.paid import JournalAdapter,RealCallsDisabled
C=pathlib.Path(__file__).resolve().parents[1]
KEY=b'x'*32
class VolumeTests(DiskIndependentTestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(dir=C/'.scratch');self.addCleanup(self.t.cleanup);self.p=pathlib.Path(self.t.name)
 def flow(self):
  return Workflow.submit(self.p/'flow',{'mock':True,'cap':'100','limits':{'kie':2,'elevenlabs':1,'ffmpeg':2},'ads':[{'id':'base','type':'ad','beats':[1,2],'hooks':['h1','h2','h3']} ]})
 def test_frames_park_and_signed_decision_recovers(self):
  f=self.flow();f.drain_mock();self.assertEqual(len(f.waiting()),2)
  d=f.sign('base','frames',1,'approve',key=KEY);f.apply(d,key=KEY)
  with self.assertRaises(ValueError):f.apply(d,key=KEY)
  f=Workflow(f.root);self.assertEqual(len(f.waiting()),1)
  f.apply(f.sign('base','frames',2,'approve',key=KEY),key=KEY);f.drain_mock()
  self.assertEqual(f.waiting()[0]['gate'],'final');self.assertFalse(f.batch_approved('base'))
 def test_invalid_expired_locked_and_final_prerequisites(self):
  f=self.flow();f.drain_mock();d=f.sign('base','frames',1,'approve',key=KEY);d['signature']='0'*64
  with self.assertRaises(ValueError):f.apply(d,key=KEY)
  d=f.sign('base','frames',1,'approve',key=KEY,ttl=-1)
  with self.assertRaises(ValueError):f.apply(d,key=KEY)
  with self.assertRaises(ValueError):f.sign('base','final','all','approve',key=KEY)
  p=f.project('base')/'plan.json';p.write_text('{"locked":true}')
  with self.assertRaises(ValueError):f.apply(f.sign('base','frames',1,'approve',key=KEY),key=KEY)
 def test_clip_revision_preserves_vo_and_other_beats(self):
  f=self.flow();f.drain_mock()
  for w in f.waiting():f.apply(f.sign(w['ad'],'frames',w['beat'],'approve',key=KEY),key=KEY)
  f.drain_mock();before=f.node_jobs('base')
  f.apply(f.sign('base','final',1,'revise',note='change motion',kind='clip',key=KEY),key=KEY);f.drain_mock();after=f.node_jobs('base')
  self.assertEqual(before['vo'],after['vo']);self.assertEqual(before['clips:2'],after['clips:2']);self.assertNotEqual(before['clips:1'],after['clips:1'])
 def test_graph_is_data_and_rawedit_has_no_generation(self):
  self.assertIn('frames',str(GRAPHS['ad']));self.assertNotIn('kie',str(GRAPHS['rawedit']))
 def test_real_path_always_disabled(self):
  with self.assertRaises(RealCallsDisabled):JournalAdapter.real('kie',go=False)
  with self.assertRaises(RealCallsDisabled):JournalAdapter.real('elevenlabs',go=True)
if __name__=='__main__':unittest.main()

class VolumeRecoveryTests(DiskIndependentTestCase):
 setUp=VolumeTests.setUp
 flow=VolumeTests.flow
 def test_decision_committed_before_queue_release_recovers(self):
  f=self.flow();f.drain_mock();d=f.sign('base','frames',1,'approve',key=KEY)
  from unittest.mock import patch
  with patch.object(f,'refresh',side_effect=OSError('kill after decision commit')):
   with self.assertRaises(OSError):f.apply(d,key=KEY)
  f=Workflow(f.root);f.refresh();self.assertFalse(any(w['beat']==1 for w in f.waiting()))
  self.assertIn(1,json.loads((f.project('base')/'plan.json').read_text())['approved_beats'])
 def test_frame_revision_only_requeues_affected_beat(self):
  f=self.flow();f.drain_mock();before=f.node_jobs('base')
  f.apply(f.sign('base','frames',1,'revise',note='new pose',key=KEY),key=KEY);f.drain_mock();after=f.node_jobs('base')
  self.assertNotEqual(before['frames:1'],after['frames:1']);self.assertEqual(before['frames:2'],after['frames:2'])
 def test_batch_requires_explicit_base_and_three_hooks(self):
  f=self.flow();f.drain_mock()
  for w in f.waiting():f.apply(f.sign(w['ad'],w['gate'],w['beat'],'approve',key=KEY),key=KEY)
  f.drain_mock();self.assertFalse(any(w['ad'].startswith('h') for w in f.waiting()))
  d=f.sign('base','final','all','approve',note='make more variants',key=KEY);d['payload']['action']='make more variants'
  with self.assertRaises(ValueError):f.apply(d,key=KEY)
  f.apply(f.sign('base','final','all','approve',key=KEY),key=KEY);f.drain_mock()
  self.assertFalse(f.batch_approved('base'))
  for w in f.waiting():f.apply(f.sign(w['ad'],w['gate'],w['beat'],'approve',key=KEY),key=KEY)
  f.drain_mock()
  for w in f.waiting()[:2]:f.apply(f.sign(w['ad'],w['gate'],w['beat'],'approve',key=KEY),key=KEY)
  self.assertFalse(f.batch_approved('base'))
  w=f.waiting()[0];f.apply(f.sign(w['ad'],w['gate'],w['beat'],'approve',key=KEY),key=KEY);self.assertTrue(f.batch_approved('base'))
 def test_rawedit_mock_runs_without_paid_submission(self):
  f=Workflow.submit(self.p/'raw',{'mock':True,'cap':'0','limits':{'kie':1,'elevenlabs':1,'ffmpeg':1},'ads':[{'id':'raw','type':'rawedit','beats':[1]}]});f.drain_mock();w=f.waiting()[0]
  f.apply(f.sign('raw','frames',1,'approve',key=KEY),key=KEY);f.drain_mock();self.assertEqual(f.waiting()[0]['gate'],'final')
  self.assertEqual(f.q.run_status(json.loads(f.state_path.read_text())['run'])['reserved'],'0')
