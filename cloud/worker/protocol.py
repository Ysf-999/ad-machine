"""Versioned storage-backed execution. Injected storage/runner; no SDK or listener."""
from __future__ import annotations
import dataclasses,fcntl,json,pathlib,resource,time
from cloud.storage import ObjectRef,Manifest as Files,IntegrityError,_no_symlinks
from cloud.orchestrator import inputs_hash,GateError
from runner import Manifest,run_stage
from runner.stage import digest
from hygiene import require_space,_scratch_path
from reliability import renewing

def save(path,value):
 from cloud.approval import _atomic
 _atomic(path,json.dumps(value,sort_keys=True,allow_nan=False,indent=2).encode()+b'\n')
def validate_job(j):
 if not isinstance(j,dict) or set(j)!={'version','id','manifest','inputs','limits','options'} or type(j['version']) is not int or j['version']!=1:raise ValueError('Unsupported job envelope')
 if not isinstance(j['id'],str) or not j['id'] or len(j['id'])>128 or any(not(c.isalnum() or c in '-_') for c in j['id']):raise ValueError('Invalid job id')
 m=Manifest(**j['manifest']);m.validate();Files({n:ObjectRef.from_dict(v) for n,v in j['inputs'].items()})
 if set(j['limits'])!={'timeout_seconds','max_output_bytes'} or any(type(v) is not int or v<1 for v in j['limits'].values()) or j['limits']['timeout_seconds']>1800 or j['limits']['max_output_bytes']>2_000_000_000:raise ValueError('Invalid limits')
 if set(j['options'])!={'project'}:raise ValueError('Unrecognized stage options')
 project=j['options']['project'];Files({project+'/plan.json':ObjectRef('a'*64,0)})
 if project+'/plan.json' not in j['inputs']:raise ValueError('Declare staged project plan')
 for name in m.project_inputs:
  prefix=project+'/'+name
  if not any(n==prefix or n.startswith(prefix+'/') for n in j['inputs']):raise ValueError('Missing project input')
 return m

def _verify_local(path,ref):
 if path.is_symlink() or not path.is_file() or path.stat().st_size!=ref.size or digest(path)!=ref.sha256:raise IntegrityError('Resumed local object changed')

def execute(job,storage,workspace,*,runtime_root,runner=None):
 m=validate_job(job);workspace=_scratch_path(workspace);_no_symlinks(workspace);require_space();workspace.mkdir(parents=True,exist_ok=True)
 with (workspace/'worker.lock').open('a+b') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);fingerprint=inputs_hash(job);identity=workspace/'job-sha256'
  if identity.exists() and identity.read_text()!=fingerprint:raise ValueError('Workspace belongs to another immutable envelope')
  identity.write_text(fingerprint);root=workspace/'inputs';root.mkdir(exist_ok=True)
  for name,row in job['inputs'].items():
   ref=ObjectRef.from_dict(row);path=root/name;_no_symlinks(path)
   if path.exists():_verify_local(path,ref)
   else:
    require_space(write_bytes=ref.size);storage.get(ref,path)
   _verify_local(path,ref) # Never trust a backend implementation's return alone.
  done=workspace/'result-envelope.json'
  if done.exists():
   result=json.loads(done.read_text())
   if result['job_sha256']!=fingerprint:raise IntegrityError('Result belongs to another job')
   for row in [*result['files'].values(),*result['logs'].values()]:
    ref=ObjectRef.from_dict(row);destination=workspace/'verify'/ref.sha256;storage.get(ref,destination);_verify_local(destination,ref);destination.unlink()
   return result
  runtime=pathlib.Path(runtime_root).resolve()
  # Existing runner reads root inputs from its trusted runtime root. They MUST be
  # declared and match that root exactly; no unverified local fallbacks.
  if runner is None:
   for name in m.root_inputs:
    files=sorted((runtime/name).rglob('*')) if (runtime/name).is_dir() else [runtime/name]
    for path in files:
     if not path.is_file():continue
     key=str(path.relative_to(runtime));ref=job['inputs'].get(key)
     if ref is None:raise ValueError('Undeclared trusted-root input')
     _verify_local(path,ObjectRef.from_dict(ref))
  m.timeout=min(m.timeout,job['limits']['timeout_seconds']);start=time.monotonic();usage=resource.getrusage(resource.RUSAGE_CHILDREN)
  result_dir=workspace/'stage';call=runner or run_stage
  report=call(runtime,root/job['options']['project'],m,result_dir,keep=True)
  elapsed=time.monotonic()-start;after=resource.getrusage(resource.RUSAGE_CHILDREN)
  if report.get('deliverable') is True:raise ValueError('Runner cannot certify deliverability')
  files={};logs={};total=0
  declared=[result_dir/'outputs'/name for name in m.outputs]
  declared += sorted(result_dir.glob('*.log'))[:16]
  for path in declared:
   if not path.exists():continue
   _no_symlinks(path);total+=path.stat().st_size
   if total>job['limits']['max_output_bytes']:raise ValueError('Output size cap exceeded')
   ref=storage.put(path,expected_sha256=digest(path));target=logs if path.suffix=='.log' else files;target[str(path.relative_to(result_dir))]=ref.to_dict()
  code=report.get('returncode',0 if report.get('status')=='done' else 1)
  if type(code) is not int:raise ValueError('Invalid runner exit status')
  result={'version':1,'id':job['id'],'job_sha256':fingerprint,'exit_status':code,'status':'done' if code==0 and report.get('status')=='done' else 'failed','files':files,'logs':logs,'timings':{'wall_seconds':elapsed},'resources':{'child_user_cpu_seconds_delta':after.ru_utime-usage.ru_utime,'child_system_cpu_seconds_delta':after.ru_stime-usage.ru_stime,'process_children_maxrss_high_water':after.ru_maxrss,'maxrss_unit':'bytes on macOS, KiB on Linux; process cumulative high-water, not job-exclusive'},'evidence_kind':'injected-runner' if runner else 'existing-runner','deliverable':False}
  save(done,result);return result

def queue_once(queue,storage,workspace,*,runtime_root,runner=None,lease_seconds=60):
 job=queue.claim('storage-worker',lease_seconds=lease_seconds)
 if job is None:return None
 try:
  if job['external'] or job['submission_started']:raise GateError('External/paid work disabled')
  envelope=job['inputs'];m=validate_job(envelope)
  if m.stage!=job['stage']:raise GateError('Queue stage differs from envelope')
  with renewing(queue,job,lease_seconds=lease_seconds):result=execute(envelope,storage,pathlib.Path(workspace)/job['id'],runtime_root=runtime_root,runner=runner)
  if result['status']!='done':return queue.fail(job['id'],job['lease_token'],error='Worker nonzero exit',retryable=False)
  # Render/stitch still need genuine separate exact-file gate receipts; this
  # adapter does NOT infer caption PASS or an approval from exit zero.
  return queue.complete(job['id'],job['lease_token'],result=result)
 except Exception as exc:
  from cloud.orchestrator import LeaseError
  try:queue.fail(job['id'],job['lease_token'],error='Worker '+type(exc).__name__,retryable=False)
  except LeaseError:pass
  raise
