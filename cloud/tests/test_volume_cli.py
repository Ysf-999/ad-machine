
from disk_test_support import DiskIndependentTestCase
import contextlib,io,json,os,pathlib,tempfile,unittest
from unittest.mock import patch
import cli
C=pathlib.Path(__file__).resolve().parents[1]
class VolumeCLITests(DiskIndependentTestCase):
 def test_submit_and_board_via_main_cli(self):
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as d:
   p=pathlib.Path(d);spec=p/'spec.json';spec.write_text(json.dumps({'mock':True,'cap':'3','limits':{'kie':1,'elevenlabs':1,'ffmpeg':1},'ads':[{'id':'demo'}]}))
   with contextlib.redirect_stdout(io.StringIO()):
    self.assertEqual(cli.main(['submit',str(spec),'--workspace',str(p/'flow')]),0)
    self.assertEqual(cli.main(['mock-work',str(p/'flow')]),0)
    self.assertEqual(cli.main(['board',str(p/'flow')]),0)
   self.assertIn('flow-decision',(p/'flow/index.html').read_text())
 def test_real_intake_refuses_before_any_copy(self):
  with tempfile.TemporaryDirectory(dir=C/'.scratch') as d:
   p=pathlib.Path(d);spec=p/'spec.json';spec.write_text('{"ads":[{"id":"real"}]}')
   with self.assertRaisesRegex(ValueError,'Real multi-ad execution not enabled'):cli.main(['submit',str(spec),'--workspace',str(p/'flow')])
   self.assertFalse((p/'flow').exists())
if __name__=='__main__':unittest.main()
