
from disk_test_support import DiskIndependentTestCase
import json, pathlib, tempfile, unittest
from runner.stage import Manifest, run_stage, _sandbox
import subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[2]
class RunnerTests(DiskIndependentTestCase):
 def test_manifest_refusals(self):
  for m in [Manifest('ad','vo',['plan.json']), Manifest('ad','status',['../plan.json']), Manifest('ad','status',['plan.json'],args=['--force'])]:
   with self.assertRaises(ValueError): m.validate()
 def test_locked(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'cloud/.scratch') as d:
   p=pathlib.Path(d); (p/'plan.json').write_text('{"locked":true}')
   with self.assertRaisesRegex(ValueError,'LOCKED'): run_stage(ROOT,p,Manifest('ad','status',['plan.json']),p/'result')
 @unittest.skipUnless(sys.platform=='darwin','Seatbelt')
 def test_os_isolation(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'cloud/.scratch') as d:
   p=pathlib.Path(d)
   code='import pathlib,socket; pathlib.Path('+repr(str(ROOT/'AGENTS.md'))+').read_text()'
   r=subprocess.run(_sandbox(p,ROOT)+[sys.executable,'-c',code],capture_output=True,text=True,cwd=p)
   self.assertNotEqual(r.returncode,0); self.assertIn('PermissionError',r.stderr)
   r=subprocess.run(_sandbox(p,ROOT)+[sys.executable,'-c',"import socket; socket.create_connection(('127.0.0.1',9))"],capture_output=True,text=True,cwd=p)
   self.assertNotEqual(r.returncode,0); self.assertIn('Operation not permitted',r.stderr)
 def test_real_status(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'cloud/.scratch') as d:
   p=pathlib.Path(d); src=p/'source';src.mkdir();(src/'plan.json').write_text('{"ad":"test","beats":[],"locked":false}')
   result=run_stage(ROOT,src,Manifest('ad','status',['plan.json']),p/'result')
   self.assertEqual(result['status'],'done');self.assertFalse((src/'QC').exists())
if __name__=='__main__':unittest.main()
