"""Bounded queue drain, never deployed or scheduled by this module.

Queue owns durable spend intents, slots, leases and receipt journaling. Adapters
are injected. Production paid transports and delivery remain unconditionally
disabled. A caller supplies the hash-verifying fetch + native gate callback;
the measured implementation is cloud.local_gate.evaluate / PostCloudGate.
"""
from decimal import Decimal
from cloud.orchestrator import GateError,LeaseError
from cloud.reliability import renewing

class Controller:
 def __init__(self,queue,adapters,*,post_cloud_gate=None,worker='bounded-controller',lease_seconds=120):
  self.q=queue;self.adapters=adapters;self.gate=post_cloud_gate;self.worker=worker;self.lease_seconds=lease_seconds
 def step(self):
  j=self.q.claim(self.worker,lease_seconds=self.lease_seconds)
  if j is None:return None
  jid,token=j['id'],j['lease_token'];submitting=False;terminal_known=False
  try:
   if j['stage'] in {'deliver','upload'}:raise GateError('Delivery disabled')
   adapter=self.adapters[j['provider']]
   if j['provider'] in {'kie','elevenlabs'} and getattr(adapter,'mock',False) is not True:
    raise GateError('Real paid calls disabled, including explicit go')
   with renewing(self.q,j,lease_seconds=self.lease_seconds):
    if j['external']:
     if j['known_cost'] is None or not Decimal('0')<=Decimal(j['known_cost'])<=Decimal('.25'):
      raise GateError('Exact per-call bound at most .25 required')
     if not j['provider_job_id']:
      self.q.prepare_submission(jid,token) # FULL SQLite commit before submit
      submitting=True
      receipt=adapter.submit(self.q.get(jid))
      self.q.record_provider_job(jid,token,receipt) # fsync JSONL before poll
      submitting=False
     receipt=self.q.poll_ready(jid,token)
     reply=adapter.poll(self.q.get(jid),receipt)
     if reply['status']=='pending':return self.q.fail(jid,token,error='provider pending',retryable=True)
     if reply['status']=='failed':
      self.q.provider_terminal(jid,token)
      return self.q.fail(jid,token,error='provider terminal failure',retryable=False)
     if reply['status']!='done':raise GateError('Unknown provider status')
     terminal_known=True
     result=dict(reply['result'])
    else:result=dict(adapter.run(j))
    if result.get('deliverable') or result.get('approved'):raise GateError('Transport cannot approve')
    result.update(deliverable=False,approved=False)
    if j['provider']=='modal' and j['stage'] in {'render','stitch','captions'}:
     if self.gate is None:raise GateError('Local post-cloud gate missing')
     gated=self.gate(self.q.get(jid),result)
     if (gated.get('status')!='RENDERED_PREFLIGHT_COMPLETE_NOT_APPROVED'
         or gated.get('master_sha256')!=result['master']['sha256']
         or gated.get('approved') is not False or gated.get('deliverable') is not False):
      raise GateError('Local post-cloud gate failed or wrong master')
     result['post_cloud_local_gate']=gated
     self.q.record_gate(j['ad_id'],j['revision'],'caption_sync',passed=True,
                        evidence='hash-bound post-cloud receipt '+gated['master_sha256'])
    return self.q.complete(jid,token,result=result) # render/stitch park at approval
  except LeaseError:raise
  except Exception as error:
   # Full provider diagnostics belong in the injected adapter's private receipt.
   # No provider response body or credential-bearing exception is printed here.
   if j['external'] and terminal_known and not submitting and self.q.get(jid)['provider_job_id']:
    self.q.provider_terminal(jid,token)
   return self.q.fail(jid,token,error='controller '+type(error).__name__,retryable=False,ambiguous=submitting)
 def drain(self,*,max_steps=100):
  if type(max_steps) is not int or not 1<=max_steps<=10000:raise ValueError('Bounded drain required')
  rows=[]
  for _ in range(max_steps):
   row=self.step()
   if row is None:break
   rows.append(row)
  return rows
