"""Reproducible metadata-only 100/500-ad simulation; never calls real transports."""
from __future__ import annotations
import argparse,json,os,pathlib,random,signal,subprocess,sys,tempfile,time,traceback
from decimal import Decimal
from cloud.workflow import Workflow
from cloud.orchestrator import BudgetError,inputs_hash
from hygiene import disk_free_probe,DiskEmergency
from cloud.mock_budget import MockBudget,DEFAULT_BYTES,TURN_RESERVE
KEY=b'simulation-key-never-production!!'
class Clock:
 def __init__(self,n=1700000000):self.now=n
 def __call__(self):return self.now

def killed_child(root,now,budget_bytes=DEFAULT_BYTES):
 budget=MockBudget(pathlib.Path(root).parent,limit=budget_bytes)
 f=Workflow(root,clock=lambda:now,mock_budget=budget);j=f.q.claim('killed-worker',lease_seconds=1)
 if not j or not j['external']:raise RuntimeError('Expected paid job for kill')
 f.q.prepare_submission(j['id'],j['lease_token']);f.adapters()[j['provider']].submit(j)
 # Both SQLite receipt and project JSONL are durable before this actual process kill.
 os.kill(os.getpid(),signal.SIGKILL)

def scenario(seed,ads):
 if ads not in (100,500):raise ValueError('Only declared100/500ad scenarios')
 rng=random.Random(seed);limits={'kie':3,'elevenlabs':2,'ffmpeg':4}
 spec={'mock':True,'cap':str(ads*3),'limits':limits,'ads':[],'faults':{}}
 # Each base has three hooks, one beat/ad; all units are fictional.
 for n in range(ads//4):spec['ads'].append({'id':f'base{n:02}','beats':[1],'hooks':[f'base{n:02}h{i}' for i in range(1,4)]})
 for base in spec['ads']:
  for aid in [base['id'],*base['hooks']]:
   for node in ['frames:1','clips:1','vo']:
    spec['faults'][aid+'/'+node]={'poll_failures':rng.randrange(3)}
 return spec

def simulate(seed,*,root,ads=100,budget=None):
 if budget is None:raise ValueError('Explicit bounded mock workspace required')
 budget.guard(root)
 source_root=pathlib.Path(__file__).resolve().parent
 files=['simulation.py','workflow.py','orchestrator.py','providers/paid.py','hygiene.py','mock_budget.py']
 import hashlib
 code={n:hashlib.sha256((source_root/n).read_bytes()).hexdigest() for n in files}
 spec=scenario(seed,ads);rng=random.Random(seed);clock=Clock();limits=spec['limits'];cap=ads*3
 f=Workflow.submit(root,spec,clock=clock,mock_budget=budget);poll_errors=kills=restarts=expired=0;peak={p:0 for p in limits};approvals=0;resume_ids=set();gate_blocks=0
 # Actual killed process at durable ID boundary, plus expired lease recovery.
 child=[sys.executable,'-m','cloud.simulation','--kill-child',str(f.root),'--now',str(clock.now),'--budget-bytes',str(budget.limit)]
 env={'PATH':'/usr/bin:/bin','PYTHONPATH':str(pathlib.Path(__file__).resolve().parent.parent)+os.pathsep+str(pathlib.Path(__file__).resolve().parent),'HOME':str(f.root),'PYTHONDONTWRITEBYTECODE':'1'}
 r=subprocess.run(child,env=env,capture_output=True,text=True)
 if r.returncode!=-signal.SIGKILL:raise AssertionError('Kill injection failed: '+r.stderr[:200])
 kills+=1;clock.now+=2;expired+=f.q.recover_expired();f=Workflow(f.root,clock=clock,mock_budget=budget);restarts+=1
 for tick in range(4000):
  budget.guard(root);f.refresh()
  # Review all gates only after work actually parked; approvals exercise real HMAC verifier.
  waiting=f.waiting()
  if waiting:
   before=[(w['ad'],w['gate'],w['beat']) for w in waiting]
   f=Workflow(f.root,clock=clock,mock_budget=budget);restarts+=1
   assert before==[(w['ad'],w['gate'],w['beat']) for w in f.waiting()]
   for w in waiting:
    f.apply(f.sign(w['ad'],w['gate'],w['beat'],'approve',key=KEY),key=KEY);approvals+=1
  # Fill provider slots BEFORE completing any task. Resumed jobs hold remote slots.
  claimed=[]
  for worker in range(20):
   j=f.q.claim(f'w{worker}',lease_seconds=2)
   if j:claimed.append(j)
  adapters=f.adapters()
  for j in claimed:
   if not j['external']:continue
   if j['provider_job_id']:resume_ids.add(j['id'])
   else:
    f.q.prepare_submission(j['id'],j['lease_token']);adapters[j['provider']].submit(j)
  jobs=f.q.jobs()
  (budget.root/'trace.json').write_text(json.dumps({'seed':seed,'tick':tick,'claimed':[{'ad':j['ad_id'],'stage':j['stage'],'state':j['state'],'resuming':bool(j['provider_job_id'])} for j in claimed],'poll_errors':poll_errors,'expired_leases':expired,'approvals':approvals}))
  budget.check()
  for provider,limit in limits.items():
   active=sum(j['provider']==provider and (j['state']=='running' or j['remote_open']) for j in jobs)
   peak[provider]=max(peak[provider],active);assert active<=limit
  assert Decimal(f.q.run_status(json.loads(f.state_path.read_text())['run'])['reserved'])<=cap
  # Seeded lease expiry on some accepted tasks: no new task permitted in their slots.
  expire_batch=bool(claimed and rng.random()<.12)
  if expire_batch:
   clock.now+=3;expired+=f.q.recover_expired();f=Workflow(f.root,clock=clock,mock_budget=budget);restarts+=1
   continue
  for j in claimed:
   token=j['lease_token']
   if j['external']:
    current=f.q.get(j['id']);pid=f.q.poll_ready(j['id'],token)
    lines=[json.loads(x) for x in (pathlib.Path(current['plan_path']).parent/'jobs.jsonl').read_text().splitlines()]
    assert any(x.get('taskId')==pid for x in lines)
    try:reply=adapters[j['provider']].poll(current,pid)
    except RuntimeError:poll_errors+=1;f.q.fail(j['id'],token,error='seeded polling failure');continue
    assert reply['status']=='done';f.q.complete(j['id'],token,result=reply['result'])
   else:
    if j['stage'] in {'stitch','render'}:f.q.record_gate(j['ad_id'],j['revision'],'caption_sync',passed=True,evidence='MOCK simulation receipt')
    f.q.complete(j['id'],token,result={'mock':True,'deliverable':False})
  state=json.loads(f.state_path.read_text())
  f._jobs={j['id']:j for j in f.q.jobs()}
  for a in state['ads'].values():
   if a['parent'] and any(n['job'] for n in a['nodes'].values()):assert state['ads'][a['parent']]['final']
   for k,n in a['nodes'].items():
    if n['definition']['name']=='clips' and n['job']:assert str(n['beat']) in a['frame_approvals']
   if a['final']:assert all(f._done(a,k,n) for k,n in a['nodes'].items())
  f._jobs={}
  budget.check()
  if all(a['final'] for a in state['ads'].values()):break
 else:raise AssertionError('Declared simulation did not drain')
 assert all(f.batch_approved(b['id']) for b in spec['ads'])
 transport=adapters['kie'].transport
 with transport.db() as db:
  submitted=db.execute('SELECT count(*) FROM accepted').fetchone()[0];polls=db.execute('SELECT sum(polls) FROM accepted').fetchone()[0]
 assert submitted==ads*3
 jobs=f.q.jobs();assert len(jobs)==ads*7 and all(j['state']=='done' for j in jobs)
 # Explicit cap exhaustion: a301st immutable task cannot reach transport.
 run=state['run'];plan=next((f.root/'snapshots').rglob('*.json'))
 extra=f.q.enqueue(run,'cap-probe','mock',{'mock':True},plan_path=plan,provider='kie',known_cost='1')
 j=f.q.claim('cap-probe')
 try:f.q.prepare_submission(j['id'],j['lease_token'])
 except BudgetError:gate_blocks+=1;f.q.fail(j['id'],j['lease_token'],error='budget cap refused',retryable=False)
 else:raise AssertionError('Cap exceeded')
 report={'seed':seed,'ads':ads,'bases':ads//4,'hooks':ads*3//4,'stage_jobs_done':ads*7,'paid_submissions':submitted,'approvals':approvals,'approved_batches':ads//4,'polls':polls,'poll_errors':poll_errors,'process_kills':kills,'process_restarts':restarts,'expired_leases':expired,'resumed_ids':len(resume_ids),'reserved_mock_units':f.q.run_status(run)['reserved'],'cap_mock_units':str(cap),'cap_probe_refusals':gate_blocks,'provider_limits':limits,'provider_peak':peak,'invariants':{name:True for name in ['once_per_immutable_job','id_journal_before_poll','resume_without_resubmit','reservation_within_cap','frame_before_clip','base_final_before_hooks','all_hooks_explicitly_confirmed','awaiting_recoverable','provider_limits_hold']},'mock_only':True,'real_QC_measured':False,'deliverable':False}
 report['scenario_hash']=inputs_hash(spec)
 assert code=={n:hashlib.sha256((source_root/n).read_bytes()).hexdigest() for n in files},'Source changed mid-simulation'
 report['code_sha256']=code;report['python']=sys.version.split()[0];return report

def main():
 p=argparse.ArgumentParser();p.add_argument('--seed',type=int,default=5415);p.add_argument('--out',type=pathlib.Path);p.add_argument('--ads',type=int,default=100,choices=[100,500]);p.add_argument('--kill-child');p.add_argument('--now',type=float);p.add_argument('--budget-bytes',type=int,default=DEFAULT_BYTES);p.add_argument('--resources',type=pathlib.Path);a=p.parse_args()
 if a.kill_child:killed_child(a.kill_child,a.now,a.budget_bytes);return
 from hygiene import SCRATCH
 before=disk_free_probe(SCRATCH);started=time.monotonic()
 # Validate free space before allocating workspace. No real guards are bypassed.
 MockBudget(SCRATCH/'simulation-admission',limit=a.budget_bytes).check(reserve=TURN_RESERVE)
 with tempfile.TemporaryDirectory(dir=SCRATCH,prefix='simulation-') as d:
  budget=MockBudget(d,limit=a.budget_bytes)
  try:
   with budget:report=simulate(a.seed,root=pathlib.Path(d)/'flow',ads=a.ads,budget=budget)
  except DiskEmergency as exc:
   print(str(exc),file=sys.stderr,flush=True);os._exit(86) # owner: emergency means no cleanup or further writes
  except Exception:
   if a.out:
    trace=pathlib.Path(d)/'trace.json'
    a.out.with_suffix('.failure.json').write_text(json.dumps({'seed':a.seed,'trace':json.loads(trace.read_text()) if trace.exists() else None,'error':traceback.format_exc(),'budget':budget.receipt()},indent=2)+'\n')
   raise
 resources=dict(budget.receipt(),seed=a.seed,ads=a.ads,wall_seconds=time.monotonic()-started,free_before_bytes=before,free_after_bytes=disk_free_probe(SCRATCH),workspace_removed=not pathlib.Path(d).exists())
 if a.resources:a.resources.write_text(json.dumps(resources,indent=2)+'\n')
 if a.out:a.out.write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report,indent=2))
if __name__=='__main__':main()
