"""Worker needs DEVNULL for original AV checker; other boundaries stay denied."""
from disk_test_support import DiskIndependentTestCase

import pathlib,subprocess,sys,tempfile,unittest
from runner.stage import _sandbox
ROOT=pathlib.Path(__file__).resolve().parents[2]
@unittest.skipUnless(sys.platform=='darwin','macOS Seatbelt')
class NullPolicyTests(DiskIndependentTestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'cloud/.scratch');self.addCleanup(self.tmp.cleanup);self.work=pathlib.Path(self.tmp.name)
 def run_code(self,code):
  return subprocess.run(_sandbox(self.work,ROOT)+[sys.executable,'-I','-c',code],cwd=self.work,capture_output=True,text=True)
 def test_devnull_rdwr_and_subprocess_devnull_work(self):
  r=self.run_code("import os,subprocess; f=os.open('/dev/null',os.O_RDWR);os.write(f,b'x');os.close(f);p=subprocess.Popen(['/usr/bin/true'],stderr=subprocess.DEVNULL);raise SystemExit(p.wait())")
  self.assertEqual(r.returncode,0,r.stderr)
 def test_outside_regular_write_and_source_read_still_denied(self):
  for code in [f"open({str(ROOT/'AGENTS.md')!r}).read()",f"open({str(self.work.parent/'must-not-write.txt')!r},'w').write('bad')"]:
   r=self.run_code(code);self.assertNotEqual(r.returncode,0);self.assertIn('PermissionError',r.stderr)
if __name__=='__main__':unittest.main()
