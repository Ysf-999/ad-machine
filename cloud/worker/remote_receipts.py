"""Small JSON-only remote returns and fail-closed client exception handling."""
import datetime,json,pathlib,re,traceback,fcntl
MAX_RECEIPT_BYTES=64000
class RemoteRunFailed(RuntimeError):
 def __init__(self,message,receipt=None):
  super().__init__(message);self.receipt=receipt

def receipt_json(value):
 text=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))
 if len(text.encode('utf-8'))>MAX_RECEIPT_BYTES:raise ValueError('Remote receipt exceeds64KB; put diagnostic in declared private Volume')
 return text

def receive(call,evidence,key,*,family=None,diagnostic=False):
 root=pathlib.Path(evidence);root.mkdir(parents=True,exist_ok=True)
 if not re.fullmatch(r'[a-zA-Z0-9_-]+',key):raise ValueError('Unsafe receipt key')
 value=None
 try:
  value=call.get()
  if isinstance(value,str):
   if len(value.encode())>MAX_RECEIPT_BYTES:raise ValueError('Remote return over64KB')
   value=json.loads(value)
  receipt_json(value)
  if not isinstance(value,dict):raise ValueError('JSON object receipt required')
  if value.get('returncode',0)!=0 or value.get('status') in {'FAILED','FAILED_RENDER','FAILED_REMOTE'}:raise RuntimeError('Nonzero remote result: '+receipt_json(value))
  return value
 except Exception as error:
  fail_run(error,root,key,family=family,receipt=value,diagnostic=diagnostic)

def fail_run(error,evidence,key,*,family=None,receipt=None,diagnostic=False,critical=False):
 root=pathlib.Path(evidence);root.mkdir(parents=True,exist_ok=True)
 trace=''.join(traceback.format_exception(type(error),error,error.__traceback__));(root/(key+'-exception.txt')).write_text(trace)
 marker={'at':datetime.datetime.now().astimezone().isoformat(),'reason':type(error).__name__+': '+str(error),'call':key,'full_exception':key+'-exception.txt','global_stop':False}
 (root/'RUN_STOP.json').write_text(json.dumps(marker,indent=2)+'\n')
 family=family or key
 with (root/'remote-failures.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  path=root/'remote-failures.json';counts=json.loads(path.read_text()) if path.exists() else {}
  attempts=counts.setdefault(family,[])
  if key not in attempts:attempts.append(key)
  path.write_text(json.dumps(counts,indent=2)+'\n')
  hard=bool(re.search(r'autherror|\b401\b|HTTP\s*401|Received\s*401|unauthenticated|permission_denied|permissionerror|billing|payment required|hash.?mismatch',type(error).__name__+' '+str(error),re.I))
  if diagnostic and len(attempts)>=2 and not hard:
   marker["workstream_stop"]=True;(root/"WORKSTREAM_STOP.json").write_text(json.dumps(marker,indent=2)+"\n")
  if hard or critical or (len(attempts)>=2 and not diagnostic):
   marker['global_stop']=True;marker['failure_attempts']=len(attempts)
   (root/'GLOBAL_STOP.json').write_text(json.dumps(marker,indent=2)+'\n')
 raise RemoteRunFailed(marker['reason'],receipt=receipt) from error

def cgroup_cpu_quota(root='/sys/fs/cgroup'):
 root=pathlib.Path(root)
 for base in [root,root/'cpu',root/'cpu,cpuacct']:
  v2=base/'cpu.max'
  if v2.is_file():return {'status':'observed','version':2,'path':str(v2),'raw':v2.read_text().strip()}
  quota=base/'cpu.cfs_quota_us';period=base/'cpu.cfs_period_us'
  if quota.is_file() and period.is_file():return {'status':'observed','version':1,'quota_us':quota.read_text().strip(),'period_us':period.read_text().strip()}
 return {'status':'not_exposed','version':None,'raw':None,'note':'Neither cgroup v1 CPU quota nor v2 cpu.max is visible; requested Modal resources are not a measured host quota'}

def artifact_receipt(value,root,relative,*,cap_bytes=2000000,commit=None):
 import hashlib
 root=pathlib.Path(root).resolve();path=pathlib.PurePosixPath(relative)
 if path.is_absolute() or '..' in path.parts or not re.fullmatch(r'overnight-output/task(?:16|17|18)-[a-z0-9-]+/[a-z0-9-]+\.json',relative):raise ValueError('Owned Task16/17/18 artifact path required')
 target=root/path
 if not target.resolve().is_relative_to(root) or target.is_symlink():raise ValueError('Artifact leaves declared Volume')
 data=(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode()
 if len(data)>cap_bytes:raise ValueError('Artifact exceeds admitted output cap')
 target.parent.mkdir(parents=True,exist_ok=True)
 with target.open('xb') as f:
  import os
  f.write(data);f.flush();os.fsync(f.fileno())
 if commit is not None:commit() # persist closed file BEFORE advertising its path
 r={k:value[k] for k in ['status','returncode','fixture','remote_wall_seconds','master','original_real_spec_sha256','host'] if k in value}
 r['artifact']={'path':relative,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
 return receipt_json(r)

def record_process_failure(returncode,log,evidence,key,*,diagnostic=False,critical=False):
 """Cover SDK setup, submit, poll and download errors that escape a child driver."""
 if returncode==0:return
 text=pathlib.Path(log).read_text();lines=[x.strip() for x in text.splitlines() if x.strip()]
 error=RuntimeError('Remote subprocess exit'+str(returncode)+': '+(lines[-1] if lines else 'no output'))
 try:fail_run(error,evidence,key,family=key.removesuffix('-retry'),diagnostic=diagnostic,critical=critical)
 except RemoteRunFailed:
  # Retain the exact original child traceback in addition to supervisor context.
  (pathlib.Path(evidence)/(key+'-exception.txt')).write_text(text)

def download_artifact(volume,artifact,destination,*,fresh=None,attempts=3,delay=.5,sleep=None,max_bytes=50000000):
 """Bounded GET-only visibility retry; never resubmits a Function/provider task."""
 import hashlib,os,time
 if type(attempts) is not int or not 1<=attempts<=5:raise ValueError('Bounded read attempts required')
 size=artifact['bytes']
 if type(size) is not int or not 0<=size<=max_bytes:raise ValueError('Artifact size cap')
 path=pathlib.PurePosixPath(artifact['path'])
 if path.is_absolute() or '..' in path.parts:raise ValueError('Safe Volume-relative artifact required')
 destination=pathlib.Path(destination)
 if destination.exists():raise FileExistsError(destination)
 part=destination.with_name(destination.name+'.part');errors=[];sleep=sleep or time.sleep
 for attempt in range(attempts):
  try:
   count=0;h=hashlib.sha256()
   with part.open('wb') as out:
    for chunk in volume.read_file(str(path)):
     count+=len(chunk)
     if count>size:raise ValueError('GLOBAL_HASH_MISMATCH artifact size')
     out.write(chunk);h.update(chunk)
    out.flush();os.fsync(out.fileno())
   if count!=size or h.hexdigest()!=artifact['sha256']:raise ValueError('GLOBAL_HASH_MISMATCH artifact bytes')
   os.replace(part,destination)
   return {'attempts':attempt+1,'bytes':count,'sha256':h.hexdigest(),'visibility_exceptions':errors}
  except FileNotFoundError:
   errors.append(traceback.format_exc())
   if attempt+1==attempts:
    error=FileNotFoundError('Artifact not visible after '+str(attempts)+' bounded reads: '+str(path));error.visibility_exceptions=errors;raise error
   sleep(delay)
   if fresh is not None:volume=fresh()
