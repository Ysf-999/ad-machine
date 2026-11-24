"""Disk safety and bounded cleanup for cloud scratch work, without network."""
from __future__ import annotations
import ctypes,errno,json,os,pathlib,shutil,sys,time
CLOUD=pathlib.Path(__file__).resolve().parent
SCRATCH=CLOUD/'.scratch'
GB=1_000_000_000
EMERGENCY=8*GB

class DiskSafetyError(RuntimeError):pass
class DiskEmergency(DiskSafetyError):pass

def disk_free_probe(path=CLOUD):
 """Single injectable free-space dependency; production always probes the host."""
 return shutil.disk_usage(path).free

def free_bytes(path=CLOUD):return disk_free_probe(path)

def require_space(path=CLOUD,*,min_free_gb=None,write_bytes=0):
 if isinstance(write_bytes,bool) or int(write_bytes)<0:raise ValueError('write_bytes must be nonnegative')
 minimum=float(os.environ.get('CLOUD_MIN_FREE_GB','10')) if min_free_gb is None else float(min_free_gb)
 if not 8<=minimum<1_000_000:raise ValueError('min_free_gb must be finite and at least8')
 available=free_bytes(path)
 if available<EMERGENCY:raise DiskEmergency('STOP: free disk below8 GB; no further work permitted')
 if available-int(write_bytes)<minimum*GB:raise DiskSafetyError(f'Free disk must remain at least {minimum:g} GB before render/copy')
 return available

def _scratch_path(path):
 p=pathlib.Path(path).absolute()
 if p==SCRATCH or not p.resolve().is_relative_to(SCRATCH.resolve()):raise ValueError('Scratch descendant required')
 for x in (p,*p.parents):
  if x==SCRATCH:break
  if x.is_symlink():raise ValueError('Scratch symlink refused')
 return p

def clone_file(source,destination):
 """Independent APFS COW copy; bounded ordinary copy only if clones unavailable."""
 src=pathlib.Path(source);dst=_scratch_path(destination);require_space()
 if src.is_symlink() or not src.is_file():raise ValueError('Regular source file required')
 if dst.exists():raise FileExistsError(dst)
 dst.parent.mkdir(parents=True,exist_ok=True)
 if sys.platform=='darwin':
  libc=ctypes.CDLL(None,use_errno=True);fn=getattr(libc,'clonefile',None)
  if fn:
   fn.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_int];fn.restype=ctypes.c_int
   if fn(os.fsencode(src),os.fsencode(dst),0)==0:
    if src.stat().st_ino==dst.stat().st_ino:raise RuntimeError('Hardlink refused')
    return str(dst)
   error=ctypes.get_errno()
   if error not in {errno.EXDEV,errno.ENOTSUP,errno.EINVAL,errno.ENOSYS}:raise OSError(error,'clonefile failed')
 require_space(write_bytes=src.stat().st_size)
 shutil.copyfile(src,dst)
 if src.stat().st_ino==dst.stat().st_ino:raise RuntimeError('Hardlink refused')
 return str(dst)

def tree_size(path):
 root=pathlib.Path(path);logical=allocated=count=0
 if root.is_symlink():return {'logical_bytes':0,'allocated_bytes':0,'files':0}
 if not root.exists():return {'logical_bytes':0,'allocated_bytes':0,'files':0}
 for parent,dirs,names in os.walk(root,followlinks=False):
  dirs[:]=[n for n in dirs if not (pathlib.Path(parent)/n).is_symlink()]
  for name in names:
   p=pathlib.Path(parent)/name
   if p.is_symlink() or not p.is_file():continue
   st=p.stat();logical+=st.st_size;allocated+=getattr(st,'st_blocks',0)*512;count+=1
 return {'logical_bytes':logical,'allocated_bytes':allocated,'files':count}

def disk_report():
 minimum=float(os.environ.get('CLOUD_MIN_FREE_GB','10'))*GB
 available=free_bytes();return {'free_bytes':available,'minimum_free_bytes':minimum,'emergency_stop_bytes':EMERGENCY,'status':'STOP' if available<EMERGENCY else ('render_refused' if available<minimum else 'ok'),'directories':{n:tree_size(CLOUD/n) for n in ['.scratch','models','evidence']},'size_note':'Logical/allocated totals may double-count APFS shared blocks; guard uses actual filesystem free space.'}

def finish_result(path,*,success,keep=False):
 """Only logs and a bounded result summary survive failures/default success."""
 root=_scratch_path(path)
 if not root.exists():return
 if any(_protected(p) and not (p!=root and _protected(p)=='active/persistent workspace') for p in (root,*root.parents) if p!=SCRATCH and p.is_relative_to(SCRATCH)):
  raise ValueError('Protected runtime/cache/active workspace refused')
 if success and keep:return
 saved={}
 for p in sorted(root.rglob('*.log'))[:16]:
  if p.is_symlink() or not p.is_file():continue
  with p.open('rb') as f:
   f.seek(max(0,p.stat().st_size-131072));saved[p.name]=f.read()
 if success:
  for name in ['plan.patch.json','jobs.append.jsonl']:
   p=root/name
   if p.is_file() and not p.is_symlink() and p.stat().st_size<=65536:saved[name]=p.read_bytes()
 summary={}
 p=root/'result.json'
 if p.is_file() and not p.is_symlink():
  try:
   data=json.loads(p.read_text())
   summary={k:data[k] for k in ['status','tool','stage','returncode','wall_seconds','gates','deliverable','error','outputs_retained'] if k in data}
  except (ValueError,OSError):summary={'status':'failed','error':'invalid result summary'}
 summary.update(success=bool(success),outputs_retained=False,cleanup='media/input copies removed; bounded logs and summary only')
 shutil.rmtree(root);root.mkdir()
 for name,data in saved.items():(root/name).write_bytes(data)
 (root/'result.json').write_text(json.dumps(summary,indent=2)+'\n')

def _protected(path):
 n=path.name.lower()
 if path.is_symlink():return 'symlink'
 if any(x in n for x in ['venv','cache']) or n.startswith('models--') or n in {'.models','models','hf','offline-models'}:return 'runtime/model/cache'
 if (path/'.keep').exists() or (path/'.active-workflow.json').exists():return 'active/persistent workspace'
 if (path/'.models').exists() or any(path.glob('models--*')):return 'contains offline model cache'
 return None

def _nested_protection(path):
 # A temporary parent can contain an active workflow or protected runtime.
 # Never follow symlinks while checking descendants.
 for parent,dirs,names in os.walk(path,followlinks=False):
  if '.active-workflow.json' in names or '.keep' in names:return 'contains active/persistent workspace'
  for n in dirs:
   child=pathlib.Path(parent)/n
   if not child.is_symlink() and _protected(child):return 'contains runtime/model/cache'
  dirs[:]=[n for n in dirs if not (pathlib.Path(parent)/n).is_symlink()]
 return None

def clean_scratch(*,age_hours=24,go=False,root=SCRATCH,now=None,names=None):
 root=pathlib.Path(root).absolute()
 if root!=SCRATCH:_scratch_path(root)
 if age_hours<0:raise ValueError('age_hours must be nonnegative')
 now=time.time() if now is None else now;candidates=[];excluded=[]
 if not root.exists():return {'dry_run':not go,'candidates':[],'excluded':[]}
 if names is not None and (not names or any(pathlib.Path(n).name!=n or n in {'.','..'} for n in names)):raise ValueError('Exact scratch child names required')
 for p in sorted(root.iterdir()):
  if names is not None and p.name not in names:continue
  reason=_protected(p) or (_nested_protection(p) if p.is_dir() and not p.is_symlink() else None)
  if reason:excluded.append({'name':p.name,'reason':reason});continue
  if not p.is_dir():continue
  try:
   newest=max([p.stat().st_mtime]+[x.stat().st_mtime for x in p.rglob('*') if not x.is_symlink()])
   if newest>now-age_hours*3600:continue
   row={'name':p.name,'path':str(p),'age_hours':(now-newest)/3600,**tree_size(p),'deleted':False}
  except FileNotFoundError:
   excluded.append({'name':p.name,'reason':'changed while listing; try again'});continue
  if go:
   _scratch_path(p)
   if _protected(p) or _nested_protection(p):raise ValueError('Protected path changed before deletion')
   shutil.rmtree(p);row['deleted']=True
  candidates.append(row)
 return {'dry_run':not go,'candidates':candidates,'excluded':excluded}

def guarded_run(args,*,timeout=600,probe_seconds=1,cancel=None,lifecycle_path=None,**kwargs):
 """Watch the emergency floor and reap the whole owned child group on failure."""
 import signal,subprocess
 require_space()
 if kwargs.pop('capture_output',False):kwargs['stdout']=subprocess.PIPE;kwargs['stderr']=subprocess.PIPE
 from reliability import cancellation,Cancelled
 cancel=cancel or cancellation()
 started=time.monotonic()
 with subprocess.Popen(args,start_new_session=True,**kwargs) as proc:
  try:
   guard=subprocess.Popen([sys.executable,'-I',str(CLOUD/'worker/guardian.py'),str(proc.pid),str(timeout),str(CLOUD)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
  except BaseException:
   try:os.killpg(proc.pid,signal.SIGKILL)
   except ProcessLookupError:pass
   proc.communicate();raise
  try:
   if guard.stdout.read(1)!=b'1':raise RuntimeError('Guardian unavailable')
   if lifecycle_path:
    with pathlib.Path(lifecycle_path).open('a') as f:f.write(json.dumps({'child_pid':proc.pid,'controller_pid':os.getpid(),'guardian_pid':guard.pid})+'\n');f.flush();os.fsync(f.fileno())
   while True:
    if cancel and cancel.is_set():raise Cancelled('Lease lost or cancellation requested')
    require_space(min_free_gb=8)
    remaining=timeout-(time.monotonic()-started)
    if remaining<=0:raise subprocess.TimeoutExpired(args,timeout)
    try:
     out,err=proc.communicate(timeout=min(probe_seconds,remaining));break
    except subprocess.TimeoutExpired:continue
  except BaseException:
   try:os.killpg(proc.pid,signal.SIGKILL)
   except ProcessLookupError:pass
   proc.communicate();raise
  finally:
   try:guard.stdin.write(b'D');guard.stdin.flush()
   except (BrokenPipeError,OSError):pass
   guard.stdin.close();guard.stdout.close()
   try:guard.wait(timeout=3)
   except subprocess.TimeoutExpired:guard.kill();guard.wait()
 return subprocess.CompletedProcess(args,proc.returncode,out,err)
