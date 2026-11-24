
from disk_test_support import DiskIndependentTestCase
import contextlib,io,json,pathlib,tempfile,unittest
import cli
class CLITests(DiskIndependentTestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=cli.ROOT/'cloud/.scratch');self.addCleanup(self.tmp.cleanup);self.p=pathlib.Path(self.tmp.name)
  (self.p/'plan.json').write_text('{"beats":[],"locked":false}')
  self.m=self.p/'manifest.json';self.m.write_text('{"tool":"ad","stage":"status","project_inputs":["plan.json"]}')
 def test_dry_run_does_not_execute_or_write(self):
  before=set(self.p.iterdir());s=io.StringIO()
  with contextlib.redirect_stdout(s):self.assertEqual(cli.main(['run',str(self.p),str(self.m)]),0)
  self.assertTrue(json.loads(s.getvalue())['dry_run']);self.assertEqual(before,set(self.p.iterdir()))
 def test_paid_and_locked_refused(self):
  self.m.write_text('{"tool":"ad","stage":"vo","project_inputs":["plan.json"]}')
  with self.assertRaises(ValueError):cli.main(['run',str(self.p),str(self.m)])
  self.m.write_text('{"tool":"ad","stage":"status","project_inputs":["plan.json"]}')
  (self.p/'plan.json').write_text('{"locked":true}')
  with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):cli.main(['run',str(self.p),str(self.m)])
if __name__=='__main__':unittest.main()
