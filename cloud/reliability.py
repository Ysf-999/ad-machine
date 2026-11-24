"""Automatic durable lease renewal and cooperative cancellation. No network."""
from __future__ import annotations
import contextvars,threading
from contextlib import contextmanager
class Cancelled(RuntimeError):pass
_cancel=contextvars.ContextVar('worker_cancel',default=None)
def cancellation():return _cancel.get()
class LeaseGuard:
 def __init__(self,q,job,lease_seconds):
  self.q=q;self.job=job;self.seconds=lease_seconds;self.stop=threading.Event();self.cancel=threading.Event();self.error=None;self.renewals=0
 def pulse(self):
  try:self.q.heartbeat(self.job['id'],self.job['lease_token'],lease_seconds=self.seconds);self.renewals+=1
  except Exception as exc:self.error=type(exc).__name__;self.cancel.set()
 def loop(self):
  while not self.stop.wait(self.seconds/4):
   self.pulse()
   if self.cancel.is_set():return
 def check(self):
  if self.cancel.is_set():raise Cancelled('Lease lost or cancellation requested')
@contextmanager
def renewing(q,job,*,lease_seconds=60):
 if lease_seconds<=0:raise ValueError('Positive lease required')
 g=LeaseGuard(q,job,lease_seconds);token=_cancel.set(g.cancel);t=threading.Thread(target=g.loop,daemon=True,name='lease-heartbeat');t.start()
 try:yield g;g.check()
 finally:g.stop.set();t.join();_cancel.reset(token)
def reap(q):
 expired=q.recover_expired()
 with q._tx() as db:
  failures=[dict(r) for r in db.execute('SELECT * FROM failures ORDER BY rowid')]
  poison=[dict(r) for r in db.execute('SELECT id,attempts,error FROM jobs WHERE quarantined=1')]
 return {'expired':expired,'quarantined':poison,'failures':failures}
