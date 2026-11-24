"""Verify declared engine options reach the SDK without changing MLX defaults."""
from disk_test_support import DiskIndependentTestCase

import pathlib,tempfile,unittest,sys
from unittest.mock import Mock,patch
from types import SimpleNamespace as NS
import transcription as tx
class WhisperOptionTests(DiskIndependentTestCase):
 def test_faster_token_limit_and_thread_budget_forwarded(self):
  with tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).resolve().parents[1]/'.scratch') as d:
   p=pathlib.Path(d);a=p/'audio';a.write_bytes(b'x');m=p/'model';m.mkdir()
   for n in ['config.json','model.bin','tokenizer.json','vocabulary.json']:(m/n).write_text('{}')
   eng=Mock();eng.transcribe.return_value=(iter([]),NS(language='en'));factory=Mock(return_value=eng)
   with patch.dict(sys.modules,{'faster_whisper':NS(WhisperModel=factory)}):
    tx.transcribe(a,backend='faster-whisper',model_path=m,compute_type='float32',cpu_threads=6,beam_size=1,best_of=1,max_new_tokens=224,temperature=(0,.2,.4,.6,.8,1))
   self.assertEqual(factory.call_args.kwargs['cpu_threads'],6)
   self.assertEqual(factory.call_args.kwargs['compute_type'],'float32')
   self.assertEqual(eng.transcribe.call_args.kwargs['max_new_tokens'],224)
   self.assertEqual(eng.transcribe.call_args.kwargs['best_of'],1)
   self.assertEqual(eng.transcribe.call_args.kwargs['temperature'],(0,.2,.4,.6,.8,1))
 def test_invalid_thread_budget_refused(self):
  for n in [-1,True,1.5]:
   with self.assertRaisesRegex(ValueError,'cpu_threads must'):tx.transcribe('unused',cpu_threads=n)
if __name__=='__main__':unittest.main()
