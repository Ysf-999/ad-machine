"""Integrated durable batch workflow. Mock execution only; real transports disabled.

Graph control and signed decisions use the same durable Queue as local stages.
Mock receipts are domain-separated, never real QC or deliverable approval.
"""
from __future__ import annotations
import argparse,fcntl,hashlib,hmac,html,json,os,re,time,uuid
from contextlib import contextmanager
from pathlib import Path
from cloud import approval
from cloud.orchestrator import Queue,inputs_hash,GateError
from cloud.providers.paid import JournalAdapter,MockTransport
from hygiene import require_space,_scratch_path

# Data controls expansion, dependencies, provider and queue approval semantics.
GRAPHS={
 'ad':[
  {'name':'frames','per_beat':True,'deps':[],'provider':'kie','queue_stage':'frames','await':'frames'},
  {'name':'clips','per_beat':True,'deps':['frames'],'provider':'kie','queue_stage':'clips'},
  {'name':'vo','deps':['clips'],'provider':'elevenlabs','queue_stage':'vo'},
  {'name':'qc','deps':['vo'],'provider':'ffmpeg','queue_stage':'qc'},
  {'name':'stitch','deps':['qc'],'provider':'ffmpeg','queue_stage':'stitch'},
  {'name':'masterqc','deps':['stitch'],'provider':'ffmpeg','queue_stage':'masterqc'},
  {'name':'preflight','deps':['masterqc'],'provider':'ffmpeg','queue_stage':'preflight','await':'final'}],
 'rawedit':[
  {'name':'storyboard','per_beat':True,'deps':[],'provider':'ffmpeg','queue_stage':'frames','await':'frames'},
  {'name':'render','deps':['storyboard'],'provider':'ffmpeg','queue_stage':'render'},
  {'name':'verify','deps':['render'],'provider':'ffmpeg','queue_stage':'verify'},
  {'name':'masterqc','deps':['verify'],'provider':'ffmpeg','queue_stage':'masterqc'},
  {'name':'preflight','deps':['masterqc'],'provider':'ffmpeg','queue_stage':'preflight','await':'final'}]
}

def _atomic(path,value):approval._atomic(path,approval._json(value)+b'\n')
def _name(v):
 if not isinstance(v,str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}',v):raise ValueError('Safe ad identifier required')
 return v

class Workflow:
 def __init__(self,root,*,clock=time.time,mock_budget=None):
  self.root=_scratch_path(root);self.clock=clock;self.mock_budget=mock_budget
  self.state_path=self.root/'workflow.json'
  if not self.state_path.is_file():raise ValueError('Workflow not found')
  if mock_budget is not None:
   if json.loads(self.state_path.read_text()).get('mock') is not True:raise ValueError('Mock budget cannot open real workflow')
   mock_budget.guard(self.root)
  self.q=Queue(self.root/'queue.sqlite',clock=clock,backoff_base=0)
 @classmethod
 def submit(cls,root,spec,*,clock=time.time,mock_budget=None):
  root=_scratch_path(root)
  if mock_budget is None:require_space()
  else:
   if spec.get('mock') is not True:raise ValueError('Mock budget requires explicit mock spec')
   mock_budget.guard(root)
  if root.exists():raise FileExistsError('Fresh workflow path required')
  if not isinstance(spec.get('ads'),list) or not spec['ads']:raise ValueError('Nonempty ads list required')
  mock=spec.get('mock') is True
  if not mock:raise ValueError('Real multi-ad execution not enabled: first supply verified worker/QC integration. No source copied or job run.')
  limits=spec.get('limits')
  if not isinstance(limits,dict) or set(limits)!={'kie','elevenlabs','ffmpeg'}:raise ValueError('Explicit mock provider limits required; real dashboard limits unknown')
  # Validate entire spec before creating queue or directories.
  ads={}
  for base in spec['ads']:
   entries=[dict(base,parent=None)]+[dict(base,id=h,parent=base['id'],hooks=[]) for h in base.get('hooks',[])]
   if base.get('hooks') and len(base['hooks'])!=3:raise ValueError('Base requires exactly3 hooks')
   for a in entries:
    aid=_name(a['id']);beats=a.get('beats',[1]);kind=a.get('type','ad')
    if aid in ads or kind not in GRAPHS or not beats or any(type(b)!=int or b<1 for b in beats) or len(set(beats))!=len(beats):raise ValueError('Invalid/duplicate ad or beats')
    if a.get('locked'):raise ValueError('LOCKED project refused')
    if a.get('project'):
     source=Path(a['project']);plan=json.loads((source/'plan.json').read_text())
     if plan.get('locked'):raise ValueError('LOCKED original refused')
     raise ValueError('Mock spec must not reference a real project')
    ads[aid]={'id':aid,'type':kind,'beats':beats,'parent':a['parent'],'hooks':a.get('hooks',[]),'nodes':{},'frame_approvals':{},'final':None,'generation':0,'notes':[]}
  root.mkdir(parents=True);(root/'.active-workflow.json').write_text('{"persistent":true,"mock":true}')
  q=Queue(root/'queue.sqlite',provider_limits=limits,clock=clock);run=q.create_run(go=True,credit_cap=spec.get('cap'))
  state={'version':1,'mock':True,'run':run,'ads':ads,'decisions':{},'limits':limits,'faults':spec.get('faults',{}),'spec_hash':inputs_hash(spec)}
  for a in ads.values():
   p=root/'ads'/a['id'];p.mkdir(parents=True)
   _atomic(p/'plan.json',{'ad':a['id'],'locked':False,'beats':[{'n':b,'vo':'mock'} for b in a['beats']],'approved_beats':[],'cloud_mock':True})
   (p/'REVIEW.html').write_text('<!doctype html><meta charset="utf-8"><h1>MOCK review: '+html.escape(a['id'])+'</h1><p>No real media or QC evidence.</p>')
   a['plan_hash']=inputs_hash(json.loads((p/'plan.json').read_text()))
   for node in GRAPHS[a['type']]:
    for b in a['beats'] if node.get('per_beat') else [None]:
     k=node['name']+((':'+str(b)) if b else '')
     a['nodes'][k]={'version':0,'job':None,'beat':b,'definition':node}
  _atomic(root/'workflow.json',state)
  f=cls(root,clock=clock,mock_budget=mock_budget);f.refresh();return f
 def project(self,ad):return self.root/'ads'/_name(ad)
 @contextmanager
 def _state(self):
  with (self.root/'workflow.lock').open('a+b') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   state=json.loads(self.state_path.read_text());before=approval._json(state);yield state
   if approval._json(state)!=before:_atomic(self.state_path,state)
 def _check(self,a):
  path=self.project(a['id'])/'plan.json';plan=json.loads(path.read_text())
  if plan.get('locked'):raise ValueError('LOCKED staged ad refused')
  if a.get('plan_pending') is not None:
   pending=a['plan_pending'];digest=inputs_hash(pending)
   if inputs_hash(plan) not in {a['plan_hash'],digest}:raise ValueError('Project changed during decision recovery')
   _atomic(path,pending);plan=pending;a['plan_hash']=digest;del a['plan_pending']
  if inputs_hash(plan)!=a['plan_hash']:raise ValueError('Project plan changed; submit an explicit new revision')
 def _plan_sync(self,a):
  p=self.project(a['id'])/'plan.json';plan=json.loads(p.read_text())
  if plan.get('locked'):raise ValueError('LOCKED staged ad refused')
  plan['approved_beats']=[int(n) for n in a['frame_approvals']]
  plan['cloud_workflow']={'mock':True,'notes':a['notes'],'final_confirmation':a['final']}
  a['plan_pending']=plan
 def _deps(self,a,node):
  deps=[]
  for name in node['definition']['deps']:
   choices=[(k,n) for k,n in a['nodes'].items() if n['definition']['name']==name]
   if node['definition']['name']=='clips':choices=[(k,n) for k,n in choices if n['beat']==node['beat']]
   deps.extend(choices)
  return deps
 def _done(self,a,k,n):
  if not n['job']:return False
  j=getattr(self,'_jobs',{}).get(n['job']) or self.q.get(n['job'])
  if n['definition'].get('await')=='frames':return j['state']=='done'
  # Stitch/render are physically done but remain in queue final-review state.
  return j['state'] in {'done','awaiting_approval'}
 def _enqueue(self,s,a,k,n):
  d=n['definition'];deps=self._deps(a,n)
  if not all(self._done(a,dk,dn) for dk,dn in deps):return
  if a['parent'] and not s['ads'][a['parent']]['final']:return
  if d['name']=='clips' and str(n['beat']) not in a['frame_approvals']:return
  identity={'workflow':s['spec_hash'],'ad':a['id'],'node':k,'version':n['version'],'deps':{dk:dn['job'] for dk,dn in deps}}
  # Immutable plan excludes mutable approval bookkeeping; dispatch checks live staged plan separately.
  if d['name'] in {'qc','render'}:
   identity['media']={nk:nn['job'] for nk,nn in a['nodes'].items() if nn['definition']['name'] in {'frames','storyboard','clips','vo'}}
  revision=inputs_hash(identity);path=self.root/'snapshots'/a['id']/(k.replace(':','-')+'-'+revision+'.json')
  if not path.exists():path.parent.mkdir(parents=True,exist_ok=True);_atomic(path,{'mock':True,'identity':identity,'locked':False})
  fault=s['faults'].get(a['id']+'/'+k,{})
  inputs={'graph':identity,'mock':True,'mock_fault':fault}
  adkey=a['id']+'/'+k
  job=self.q.enqueue(s['run'],adkey,d['queue_stage'],inputs,plan_path=path,provider=d['provider'],known_cost='1' if d['provider']!='ffmpeg' else None,revision=revision,max_attempts=100)
  n['job']=job['id']
  if d['queue_stage']=='frames':self.q.record_gate(adkey,revision,'plan_review',passed=True,evidence='MOCK plan review; no model call')
  if d['queue_stage'] in {'clips','stitch'}:
   sources=[fn['job'] for fn in a['nodes'].values() if fn['definition'].get('await')=='frames' and (d['queue_stage']!='clips' or fn['beat']==n['beat'])]
   self.q.inherit_frames(job['id'],sources)
 def refresh(self):
  if self.mock_budget is None:require_space()
  else:self.mock_budget.guard(self.root)
  self._jobs={j['id']:j for j in self.q.jobs()}
  with self._state() as s:
   for a in s['ads'].values():
    self._check(a)
    for jid in a.pop('cancel_pending',[]):self.q.cancel(jid)
    for k,n in a['nodes'].items():
     if n['job'] and n['definition'].get('await')=='frames' and str(n['beat']) in a['frame_approvals']:
      j=self._jobs.get(n['job']) or self.q.get(n['job'])
      if j['state']=='awaiting_approval':self._jobs[j['id']]=self.q.approve(j['id'],owner='signed MOCK decision:'+a['frame_approvals'][str(n['beat'])])
     if not n['job']:self._enqueue(s,a,k,n)
    if a['final']:
     for n in a['nodes'].values():
      if n['job'] and (self._jobs.get(n['job']) or self.q.get(n['job']))['state']=='awaiting_approval':self._jobs[n['job']]=self.q.approve(n['job'],owner='signed MOCK final:'+a['final'])
  self._jobs={}
 def node_jobs(self,ad):
  with self._state() as s:return {k:n['job'] for k,n in s['ads'][ad]['nodes'].items()}
 def waiting(self):
  rows=[];self._jobs={j['id']:j for j in self.q.jobs()}
  with self._state() as s:
   for a in s['ads'].values():
    self._check(a)
    for k,n in a['nodes'].items():
     if n['definition'].get('await')=='frames' and n['job'] and (self._jobs.get(n['job']) or self.q.get(n['job']))['state']=='awaiting_approval' and str(n['beat']) not in a['frame_approvals']:
      rows.append({'ad':a['id'],'gate':'frames','beat':n['beat'],'mock':True})
    if all(self._done(a,k,n) for k,n in a['nodes'].items()) and not a['final']:
     rows.append({'ad':a['id'],'gate':'final','beat':'all','mock':True})
  self._jobs={}
  return rows
 def _binding(self,a,gate):
  if gate=='frames':return inputs_hash({k:n['job'] for k,n in a['nodes'].items() if n['definition'].get('await')=='frames'})
  return inputs_hash({k:n['job'] for k,n in a['nodes'].items()})
 def sign(self,ad,gate,beat,action,*,key,note='',kind=None,ttl=3600):
  with self._state() as s:
   a=s['ads'][ad];self._check(a)
   if gate not in {'frames','final'} or action not in {'approve','revise'}:raise ValueError('Invalid decision')
   if beat!='all' and beat not in a['beats']:raise ValueError('Unknown beat')
   if gate=='frames' and beat=='all':raise ValueError('Approve frame beats explicitly')
   if not any(w['ad']==ad and w['gate']==gate for w in self._waiting_unlocked(a)):raise ValueError('Gate not ready')
   if action=='revise' and (beat=='all' or not note.strip()):raise ValueError('Revision needs one beat and note')
   if len(note)>4000 or any(ord(c)<32 for c in note):raise ValueError('One-line note required')
   if type(ttl)!=int or ttl>86400:raise ValueError('Lifetime at most one day')
   now=int(self.clock());p={'domain':'cloud-workflow-mock-v1','workflow':str(self.root),'ad':ad,'gate':gate,'beat':beat,'action':action,'kind':kind or ('frame' if gate=='frames' else 'clip'),'note':note,'binding':self._binding(a,gate),'id':uuid.uuid4().hex,'issued':now,'expires':now+ttl}
   return {'payload':p,'signature':hmac.new(approval._key(key),approval._json(p),hashlib.sha256).hexdigest()}
 def _waiting_unlocked(self,a):
  rows=[]
  for n in a['nodes'].values():
   if n['definition'].get('await')=='frames' and n['job'] and self.q.get(n['job'])['state']=='awaiting_approval':rows.append({'ad':a['id'],'gate':'frames','beat':n['beat']})
  if all(self._done(a,k,n) for k,n in a['nodes'].items()) and not a['final']:rows.append({'ad':a['id'],'gate':'final','beat':'all'})
  return rows
 def apply(self,decision,*,key):
  try:
   if set(decision)!={'payload','signature'}:raise ValueError('Malformed decision')
   p=decision['payload']
   if not hmac.compare_digest(decision['signature'],hmac.new(approval._key(key),approval._json(p),hashlib.sha256).hexdigest()):raise ValueError('Invalid signature')
   with self._state() as s:
    fields={'domain','workflow','ad','gate','beat','action','kind','note','binding','id','issued','expires'}
    if set(p)!=fields or p['domain']!='cloud-workflow-mock-v1' or p['workflow']!=str(self.root):raise ValueError('Wrong decision domain/workspace')
    if type(p['issued'])!=int or type(p['expires'])!=int or not p['issued']<=self.clock()<p['expires'] or p['expires']-p['issued']>86400:raise ValueError('Expired decision')
    if p['id'] in s['decisions']:raise ValueError('Duplicate decision')
    a=s['ads'][p['ad']];self._check(a)
    if p['action'] not in {'approve','revise'} or p['gate'] not in {'frames','final'} or p['kind'] not in {'frame','clip'}:raise ValueError('Invalid action/gate/kind')
    if p['gate']=='frames' and p['kind']!='frame':raise ValueError('Frame gate requires frame kind')
    if p['beat']!='all' and p['beat'] not in a['beats']:raise ValueError('Unknown beat')
    waiting=self._waiting_unlocked(a)
    if not any(w['gate']==p['gate'] and (p['gate']=='final' or w['beat']==p['beat']) for w in waiting):raise ValueError('Gate not awaiting this decision')
    if p['binding']!=self._binding(a,p['gate']):raise ValueError('Stale input hash')
    if p['action']=='approve':
     if p['gate']=='frames':a['frame_approvals'][str(p['beat'])]=p['id']
     elif p['beat']=='all':a['final']=p['id']
     else:raise ValueError('Explicit whole-final confirmation required')
    else:
     if p['beat']=='all' or not isinstance(p['note'],str) or not p['note'].strip() or len(p['note'])>4000 or any(ord(c)<32 for c in p['note']):raise ValueError('Revision needs one beat and note')
     if any(s['ads'][h]['nodes'][k]['job'] for h in a['hooks'] for k in s['ads'][h]['nodes']):raise ValueError('Hooks already started: revision requires a new base version')
     self._revise(a,p)
    s['decisions'][p['id']]=inputs_hash(decision)
    a['notes'].append({'id':p['id'],'action':p['action'],'beat':p['beat'],'kind':p['kind'],'note':p['note']})
    self._plan_sync(a)
    # Durable decision is the recovery record; plan mirror and queue release are replayable in refresh.
    out=self.root/'decisions'/(p['id']+'.json');out.parent.mkdir(exist_ok=True);_atomic(out,decision)
   self.refresh();return {'accepted':p['id'],'mock':True,'deliverable':False}
  except (ValueError,KeyError,TypeError,GateError) as exc:
   with (self.root/'decision-rejections.log').open('a') as log:log.write(type(exc).__name__+': decision rejected\n');log.flush();os.fsync(log.fileno())
   raise ValueError(str(exc)) from None
 def _sync_plans(self):
  with self._state() as s:
   for a in s['ads'].values():self._plan_sync(a)
 def _revise(self,a,p):
  affected=set()
  for k,n in a['nodes'].items():
   name=n['definition']['name']
   if n['beat']==p['beat'] and (name in {'clips'} or p['kind']=='frame' and name in {'frames','storyboard'}):affected.add(k)
  for k,n in a['nodes'].items():
   if n['definition']['name'] in {'qc','stitch','render','verify','masterqc','preflight'}:affected.add(k)
  if p['kind']=='frame':a['frame_approvals'].pop(str(p['beat']),None)
  for k in affected:
   n=a['nodes'][k]
   if n['job']:a.setdefault('cancel_pending',[]).append(n['job'])
   n['job']=None;n['version']+=1
  a['final']=None
 def batch_approved(self,base):
  with self._state() as s:
   a=s['ads'][base]
   return bool(a['final'] and len(a['hooks'])==3 and all(s['ads'][h]['final'] for h in a['hooks']))
 def adapters(self):
  transport=MockTransport(self.root/'mock-service.sqlite')
  return {p:JournalAdapter(self.q,p,transport,mock=True) for p in ['kie','elevenlabs']}
 def work_once(self):
  self.refresh();ads=json.loads(self.state_path.read_text())['ads'];adapters=self.adapters()
  flow=self
  class Local:
   def run(self,job):
    # Synthetic receipt only; real QC/preflight are never invoked or attested.
    for gate in ['caption_sync'] if job['stage'] in {'stitch','render'} else []:
     flow.q.record_gate(job['ad_id'],job['revision'],gate,passed=True,evidence='MOCK simulation receipt, not measured media')
    return {'status':'done','mock':True,'deliverable':False}
  adapters['ffmpeg']=Local()
  return self.q.run_once(adapters,lease_seconds=30)
 def drain_mock(self,limit=10000):
  for _ in range(limit):
   r=self.work_once()
   if r is None:return
  raise RuntimeError('Mock drain exceeded limit')
 def board(self):
  rows=self.waiting();parts=['<!doctype html><meta charset="utf-8"><title>Batch review</title><h1>MOCK batch review</h1><p>Simulation only. No production approvals.</p>']
  import shlex
  for gate in ['frames','final']:
   parts.append('<h2>'+gate+' approval</h2>')
   for w in rows:
    ad=w['ad'];beat=str(w['beat']);parts.append('<article><h3>'+html.escape(ad)+' · '+beat+'</h3><a href="ads/'+ad+'/REVIEW.html">Review bundle</a>')
    targets=[('approve',beat)]+[('revise',str(n)) for n in (json.loads(self.state_path.read_text())['ads'][ad]['beats'] if gate=='final' else [w['beat']])]
    for action,target in targets:
     binding=self._binding(json.loads(self.state_path.read_text())['ads'][ad],gate)[:12]
     cmd=['python','cli.py','flow-decision',str(self.root),ad,gate,target,action,'--out',str(self.root/'decisions'/(ad+'-'+gate+'-'+target+'-'+binding+'-'+action+'.json'))]
     if action=='revise':cmd+=['--note','REPLACE WITH YOUR NOTE']
     parts.append('<pre>'+html.escape(shlex.join(cmd))+'</pre>')
    parts.append('</article>')
  out=self.root/'index.html';out.write_text(''.join(parts));return out

# Real worker graph shares this graph catalog with the mock volume flow. Its
# evidence parking gate is separate from the unchanged full production approval.
REAL_GRAPHS={'rawedit':[
 {'name':'render','deps':[],'kind':'worker'},
 {'name':'finalize','deps':['render'],'kind':'worker'},
 {'name':'caption_sync','deps':['finalize'],'kind':'gate'},
 {'name':'av_check','deps':['finalize'],'kind':'gate'},
 {'name':'automated_preflight','deps':['caption_sync','av_check'],'kind':'gate'},
 {'name':'await_final_review','deps':['caption_sync','av_check','automated_preflight'],'kind':'owner_review'},
 {'name':'qc','deps':['render'],'kind':'full_approval','blocked':'current real evidence required; no Claude calls'},
 {'name':'masterqc','deps':['render'],'kind':'full_approval','blocked':'current real evidence required; no Claude calls'},
 {'name':'manual_preflight','deps':['automated_preflight'],'kind':'full_approval','blocked':'owner manual boxes unanswered'},
 {'name':'approved_batch','deps':['owner_final','all_three_hooks'],'kind':'full_approval','blocked':'explicit base and all hooks confirmations required'}]}
