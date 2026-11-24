"""Single-host overnight admission journal; estimates are never a billing fact."""
import contextlib,fcntl,json,os,pathlib
from decimal import Decimal as D
class Budget:
 def __init__(self,path,cap='3.00',stop='2.40',task='overnight'):
  self.path=pathlib.Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
  if not D('0')<D(stop)<=D(cap):raise ValueError('0 < stop <= cap required')
  if not self.path.exists():self.write({'task':task,'cap_usd':str(cap),'stop_at_usd':str(stop),'calls':[],'estimated_total_usd':'0','reserved_total_usd':'0','global_stop':False})
 def write(self,data):
  temp=self.path.with_suffix('.pending')
  with temp.open('w') as f:json.dump(data,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
  os.replace(temp,self.path)
 @contextlib.contextmanager
 def locked(self):
  with self.path.with_suffix('.lock').open('a') as f:
   fcntl.flock(f,fcntl.LOCK_EX);yield json.loads(self.path.read_text())
 def reserve(self,key,bound,kind,details):
  bound=D(bound)
  if not bound.is_finite() or bound<0 or bound==0 and kind!='metadata':raise PermissionError('Known positive bound required')
  if bound>D('.40' if kind=='build' else '.25'):raise PermissionError('Per-call cap refused')
  with self.locked() as data:
   if data['global_stop']:raise PermissionError('Existing global stop')
   old=next((x for x in data['calls'] if x['id']==key),None)
   if old:
    if old['details']!=details or D(old['admitted_worst_case_usd'])!=bound or old['kind']!=kind:raise PermissionError('Journal identity conflict')
    return False
   total=sum((min(D(x['estimate_usd']),D(x['admitted_worst_case_usd'])) if x.get('estimate_usd') is not None else D(x['admitted_worst_case_usd']) for x in data['calls']),D(0))+bound   # finished calls count their recorded estimate, open ones their worst case
   if total>=D(data.get('stop_at_usd','2.40')) or total>D(data.get('cap_usd','3')):raise PermissionError('Global budget threshold refused before action')   # the ledger's own cap/stop (default 3.00/2.40)
   if kind=='build' and (data.get('max_builds',2) not in (1,2) or sum(x['kind']=='build' for x in data['calls'])>=data.get('max_builds',2)):raise PermissionError('Task build allowance used')
   data['calls'].append({'id':key,'kind':kind,'admitted_worst_case_usd':str(bound),'status':'ADMITTED','details':details,'estimate_usd':None})
   data['reserved_total_usd']=str(total);self.write(data);return True
 def finish(self,key,status,estimate,wall_seconds,**extra):
  estimate=D(estimate)
  if not estimate.is_finite() or estimate<0:raise ValueError('Finite nonnegative estimate required')
  with self.locked() as data:
   call=next(x for x in data['calls'] if x['id']==key);call.update(status=status,estimate_usd=str(estimate),wall_seconds=wall_seconds,**extra)
   total=sum((D(x['estimate_usd']) for x in data['calls'] if x['estimate_usd'] is not None),D(0));data['estimated_total_usd']=str(total)
   family=call['details'].get('family',key)
   failures=sum(x['status'] in {'FAILED','SETUP_REJECTED'} and x['details'].get('family',x['id'])==family for x in data['calls'])
   reason='Paid call failed' if status=='FAILED' and call['details'].get('paid_call',False) else 'Call failed twice' if failures>=2 and not call['details'].get('diagnostic_only',False) else 'Cost inconsistent with admission' if estimate>D(call['admitted_worst_case_usd']) else 'Running estimate reached the stop line' if total>=D(data.get('stop_at_usd','2.40')) else None
   if reason:data.update(global_stop=True,stop_reason=reason)
   self.write(data)
   if reason:
    self.path.with_name('GLOBAL_STOP.json').write_text(json.dumps({'reason':reason,'call_id':key},indent=2)+'\n')
    raise PermissionError(reason)
 def link(self,key,call_id,app_id):
  with self.locked() as data:
   call=next(x for x in data['calls'] if x['id']==key)
   if call.get('provider_call_id') and (call['provider_call_id'],call['app_id'])!=(call_id,app_id):raise PermissionError('Provider call identity cannot be replaced')
   call.update(provider_call_id=call_id,app_id=app_id,status='REMOTE_STARTED');self.write(data)
