"""Bounded metadata-only workspace policy; never accepted by real render/copy APIs."""
from __future__ import annotations
import pathlib,threading,time
import hygiene
DEFAULT_BYTES=300_000_000
MAX_BYTES=1_000_000_000
EMERGENCY_BYTES=6_000_000_000
# One simulation turn writes at most20 tiny receipts plus one500-ad state.
# Keep headroom for SQLite WALs and atomic state replacement between samples.
TURN_RESERVE=8_000_000
class MockBudget:
 def __init__(self,root,*,limit=DEFAULT_BYTES):
  if type(limit)!=int or not TURN_RESERVE<limit<=MAX_BYTES:raise ValueError('Mock footprint budget must exceed8MB and never exceed1GB')
  self.root=hygiene._scratch_path(root);self.limit=limit;self.peak_bytes=0;self.samples=0;self.failure=None;self._stop=threading.Event()
 def footprint(self):
  total=0
  if self.root.exists():
   for p in self.root.rglob('*'):
    try:
     s=p.lstat()
     if p.is_symlink():raise ValueError('Mock workspace cannot contain symlinks')
     total+=max(s.st_size,s.st_blocks*512)
    except FileNotFoundError:continue # atomic state/WAL rename during meter sample
  return total
 def check(self,*,reserve=0):
  if self.failure:raise self.failure
  available=hygiene.disk_free_probe(hygiene.CLOUD)
  if available<EMERGENCY_BYTES:raise hygiene.DiskEmergency('STOP: mock task emergency below6GB; free='+str(available))
  used=self.footprint();self.peak_bytes=max(self.peak_bytes,used);self.samples+=1
  if used+reserve>self.limit:raise hygiene.DiskSafetyError('Mock footprint budget exceeded: '+str(used)+' + reserve '+str(reserve)+' > '+str(self.limit))
  return used
 def guard(self,root):
  p=pathlib.Path(root).resolve()
  if p!=self.root and self.root not in p.parents:raise ValueError('Mock budget bound to another workspace')
  self.check(reserve=TURN_RESERVE)
 def __enter__(self):
  self.check(reserve=TURN_RESERVE)
  def meter():
   while not self._stop.wait(.1):
    try:self.check()
    except Exception as exc:self.failure=exc;return
  self.thread=threading.Thread(target=meter,daemon=True);self.thread.start();return self
 def __exit__(self,*exc):
  self._stop.set();self.thread.join();self.check()
 def receipt(self):return {'budget_bytes':self.limit,'peak_bytes':self.peak_bytes,'meter_samples':self.samples,'meter_interval_seconds':.1,'turn_reserve_bytes':TURN_RESERVE,'peak_measurement':'max logical/allocated footprint sampled every0.1s and at operation boundaries;8MB headroom reserved before each turn'}
