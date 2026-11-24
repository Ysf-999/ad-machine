"""Unit-only disk dependency injection. No production environment bypass exists."""
import contextlib,pathlib,subprocess,sys,unittest
from unittest.mock import patch
import hygiene
FAKE_FREE_BYTES=50_000_000_000
HOST_DISK_PROBE=getattr(hygiene,'disk_free_probe',None)
BOOTSTRAP=pathlib.Path(__file__).with_name('disk_child.py')
(pathlib.Path(__file__).resolve().parents[1]/'.scratch').mkdir(exist_ok=True)   # scratch root the tests write under (git-ignored)
def child_launcher(original):
 def launch(args,*a,**kw):
  # Only internal helpers that themselves guard disk; never rewrite isolated
  # original-tool commands or their sandbox/read/write/network policy.
  if isinstance(args,(list,tuple)) and args:
   parts=[str(v) for v in args];python=pathlib.Path(parts[0]).name.startswith('python')
   internal=(len(parts)>2 and parts[1:3]==['-m','providers.worker']) or any(v.endswith('/worker/guardian.py') for v in parts) or (len(parts)>2 and parts[1]=='-c' and 'from hygiene import guarded_run' in parts[2])
   if python and internal:args=[parts[0],'-I',str(BOOTSTRAP),str(FAKE_FREE_BYTES),*parts[1:]]
  return original(args,*a,**kw)
 return launch
@contextlib.contextmanager
def injected_disk():
 with patch.object(hygiene,'disk_free_probe',return_value=FAKE_FREE_BYTES),patch.object(subprocess,'Popen',new=child_launcher(subprocess.Popen)):
  yield
class DiskIndependentTestCase(unittest.TestCase):
 def run(self,result=None):
  with injected_disk():return super().run(result)
