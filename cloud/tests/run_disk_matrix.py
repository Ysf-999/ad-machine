"""Run disk-sensitive unit parts with the underlying host probe at four levels."""
import collections,json,pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import hygiene
EXCLUDE={'test_runner','test_null_policy','test_local_integration','test_hygiene_runner','test_protocol_real_status'}
def flatten(suite):
 for value in suite:
  if isinstance(value,unittest.TestSuite):yield from flatten(value)
  else:yield value
if __name__=='__main__':
 free=int(sys.argv[1]);usage=collections.namedtuple('usage','total used free')(100_000_000_000,100_000_000_000-free,free)
 suite=unittest.defaultTestLoader.discover(str(pathlib.Path(__file__).parent))
 tests=[t for t in flatten(suite) if t.id().split('.')[0] not in EXCLUDE and not t.id().startswith('test_disk_matrix.')]
 with patch.object(hygiene.shutil,'disk_usage',return_value=usage):
  result=unittest.TextTestRunner(verbosity=0).run(unittest.TestSuite(tests))
 print('DISK_MATRIX '+json.dumps({'underlying_host_free_bytes':free,'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'success':result.wasSuccessful()},sort_keys=True))
 raise SystemExit(0 if result.wasSuccessful() else 1)
