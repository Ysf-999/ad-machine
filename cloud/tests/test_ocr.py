
from disk_test_support import DiskIndependentTestCase
import pathlib,tempfile,unittest
from cloud.ocr import compare_outputs,tilt,OCRFailure,Backend
class OCRTests(DiskIndependentTestCase):
 def test_original_tilt_boundaries_consecutive_frames_and_no_missed_hits(self):
  frames=[[('Hello world',.5,1.51,.022)],[('Hello world',.5,1.51,.022)]]
  self.assertEqual(len(tilt(frames)),1)
  for angle in [0,1.5,25,90]:self.assertEqual(tilt([[('Hello',.8,angle,.1)]]*2),[])
  self.assertEqual(tilt([[('Hello',.8,2,.1)],[],[('Hello',.8,2,.1)]]),[])
  report=compare_outputs(frames,frames);self.assertTrue(report['parity'])
  report=compare_outputs(frames,[[],[]]);self.assertFalse(report['parity']);self.assertTrue(report['missed_baseline_violation'])
 def test_angle_tolerance_does_not_relax_original_gate(self):
  a=[[('Hello',.8,1.51,.1)]]*2;b=[[('Hello',.8,1.49,.1)]]*2
  report=compare_outputs(a,b);self.assertFalse(report['parity']);self.assertTrue(report['missed_baseline_violation'])
 def test_inference_failures_never_become_no_text_pass(self):
  class Broken(Backend):
   def infer(self,path):raise OSError('broken inference')
  with self.assertRaises(OCRFailure):Broken().read('/missing.png')
 def test_geometry_text_mismatch_and_invalid_numbers_refused(self):
  with self.assertRaises(OCRFailure):compare_outputs([[('Hi',.5,float('nan'),.1)]],[[]])
  r=compare_outputs([[('Hello',.8,2,.1)]],[[('Goodbye',.8,2,.1)]]);self.assertFalse(r['parity'])

class CorpusBindingTests(DiskIndependentTestCase):
 def test_original_inference_exception_is_retained_for_diagnosis(self):
  class Broken(Backend):
   def infer(self,path):raise RuntimeError('native original exception')
  try:Broken().read('/frame')
  except OCRFailure as error:
   self.assertIsInstance(error.__cause__,RuntimeError)
   self.assertEqual(str(error.__cause__),'native original exception')
  else:self.fail('Inference failure became success')
 def test_comparison_refuses_different_pixels_even_matching_text(self):
  from cloud.ocr.parity import compare_corpus
  import copy
  base={'source_sha256':'a'*64,'masters':[{'name':'ad','master_sha256':'b'*64,'frames':[{'sha256':'c'*64,'ocr':[]}]}]}
  candidate={'version':1,'backend':'unit-fake','corpus_source_sha256':'a'*64,'masters':copy.deepcopy(base['masters'])}
  self.assertTrue(compare_corpus(base,candidate)['parity']);candidate['masters'][0]['frames'][0]['sha256']='d'*64
  with self.assertRaises(OCRFailure):compare_corpus(base,candidate)
