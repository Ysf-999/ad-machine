import json,pathlib,subprocess,sys
from disk_test_support import DiskIndependentTestCase
class DiskMatrixTests(DiskIndependentTestCase):
 def test_disk_sensitive_unit_parts_at_four_host_levels(self):
  driver=pathlib.Path(__file__).with_name('run_disk_matrix.py')
  for free in [4_000_000_000,9_900_000_000,10_000_000_000,50_000_000_000]:
   with self.subTest(host_free=free):
    r=subprocess.run([sys.executable,str(driver),str(free)],capture_output=True,text=True,timeout=120)
    lines=[line for line in r.stdout.splitlines() if line.startswith('DISK_MATRIX ')]
    self.assertTrue(lines,r.stderr[-2000:])
    result=json.loads(lines[-1].split(' ',1)[1]);self.assertTrue(result['success'],r.stderr[-3000:]);self.assertEqual(r.returncode,0)
    self.assertGreater(result['tests'],200);print(lines[-1],flush=True)
