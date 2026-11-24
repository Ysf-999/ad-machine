"""Test-only bootstrap for internal subprocess helpers, never a worker option."""
import pathlib,runpy,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from disk_test_support import injected_disk
value=int(sys.argv[1]);args=sys.argv[2:]
if value!=50_000_000_000:raise ValueError('Fixed unit fixture only')
if args and args[0]=='-I':args=args[1:]
with injected_disk():
 if args[0]=='-m':
  sys.argv=args[1:];runpy.run_module(args[1],run_name='__main__',alter_sys=True)
 elif args[0]=='-c':
  sys.argv=['-c',*args[2:]];exec(compile(args[1],'<unit-child>','exec'),{'__name__':'__main__'})
 else:
  sys.argv=args;runpy.run_path(args[0],run_name='__main__')
