"""Modal definition factory for the queue-based offline worker prototype (not the deployed controller, which is
controller/app.py). No SDK import, App, image build or run on import."""
from __future__ import annotations
import dataclasses,os,pathlib,re,sqlite3
from contextlib import contextmanager
from decimal import Decimal,InvalidOperation
class Disabled(PermissionError):pass
PREFIX=os.environ.get('ADMACHINE_PREFIX') or 'admachine'

def amount(value):
 try:
  if isinstance(value,(bool,float)) or value is None:raise ValueError
  n=Decimal(value)
  if not n.is_finite() or n<=0:raise ValueError
  return n
 except (ValueError,TypeError,InvalidOperation):raise Disabled('Owner positive cap and known positive bound required') from None
@dataclasses.dataclass(frozen=True)
class Config:
 run_id:str;owner_cap:str|None=None;known_job_bound:str|None=None
 base_image:str='';linux_lock_sha256:str='';timeout:int=1800;max_containers:int=1;concurrency:int=1
 model_volume:str=PREFIX+'-offline-models';control_volume:str=PREFIX+'-worker-control';bucket:str=PREFIX+'-private-artifacts'
 secret_names:tuple[str,...]=(PREFIX+'-storage',PREFIX+'-runtime-admission')
 def validate(self):
  if amount(self.known_job_bound)>amount(self.owner_cap):raise Disabled('Job bound exceeds owner run cap')
  if not re.fullmatch('[a-zA-Z0-9_-]{1,80}',self.run_id):raise ValueError('Safe run id required')
  if self.max_containers!=1 or self.concurrency!=1:raise Disabled('Multiple containers need a shared distributed budget authority')
  if type(self.timeout) is not int or not 1<=self.timeout<=1800:raise ValueError('Timeout exceeds bound')
  if not re.fullmatch('.+@sha256:[a-f0-9]{64}',self.base_image) or not re.fullmatch('[a-f0-9]{64}',self.linux_lock_sha256):raise Disabled('Owner pinned Linux image/lock required')
  if any(not re.fullmatch('[a-zA-Z0-9_-]+',v) for v in [self.model_volume,self.control_volume,self.bucket,*self.secret_names]):raise ValueError('Names only; no credentials')
class Budget:
 """Single-coordinator FULL SQLite reservation ledger, never provider billing proof."""
 def __init__(self,path,run_id,cap):
  self.path=pathlib.Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.run=run_id;self.cap=amount(cap)
  with self.db() as d:
   d.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, cap TEXT)');d.execute('CREATE TABLE IF NOT EXISTS reservations (run TEXT,id TEXT,bound TEXT,fingerprint TEXT,PRIMARY KEY(run,id))')
   old=d.execute('SELECT cap FROM runs WHERE id=?',(run_id,)).fetchone()
   if old and Decimal(old[0])!=self.cap:raise Disabled('Immutable owner cap differs')
   d.execute('INSERT OR IGNORE INTO runs VALUES (?,?)',(run_id,str(self.cap)))
 @contextmanager
 def db(self):
  d=sqlite3.connect(self.path,timeout=30,isolation_level='IMMEDIATE');d.execute('PRAGMA synchronous=FULL')
  try:
   with d:yield d
  finally:d.close()
 def reserved(self):
  with self.db() as d:return str(sum((Decimal(r[0]) for r in d.execute('SELECT bound FROM reservations WHERE run=?',(self.run,))),Decimal(0)))
 def reserve(self,job_id,bound,fingerprint=''):
  bound=amount(bound)
  with self.db() as d:
   d.execute('BEGIN IMMEDIATE');old=d.execute('SELECT bound,fingerprint FROM reservations WHERE run=? AND id=?',(self.run,job_id)).fetchone()
   if old:
    if Decimal(old[0])!=bound or old[1]!=fingerprint:raise Disabled('Immutable job admission differs')
    return
   total=sum((Decimal(r[0]) for r in d.execute('SELECT bound FROM reservations WHERE run=?',(self.run,))),Decimal(0))
   if total+bound>self.cap:raise Disabled('Owner run cap exhausted before worker stage')
   d.execute('INSERT INTO reservations VALUES (?,?,?,?)',(self.run,job_id,str(bound),fingerprint))
def build_app(config,*,modal_module=None,storage_factory=None,execute=None,budget=None):
 config.validate() # Must fail before SDK import/App/image/volume side effects.
 if storage_factory is None or budget is None:raise Disabled('Trusted storage adapter and durable pre-admission ledger not configured')
 if budget.run!=config.run_id or budget.cap!=amount(config.owner_cap):raise Disabled('Budget authority differs from owner cap')
 if modal_module is None:
  if not budget.path.is_absolute() or not budget.path.is_relative_to('/control'):raise Disabled('Real Modal ledger must use the separate persistent /control volume')
  try:import modal as modal_module
  except ImportError:raise Disabled('Modal is not installed; no install is attempted') from None
 from cloud.worker.protocol import execute as entrypoint
 from cloud.orchestrator import inputs_hash
 sdk=modal_module;cloud=pathlib.Path(__file__).resolve().parents[1]
 image=sdk.Image.from_dockerfile(str(cloud/'Dockerfile'),context_dir=str(cloud.parent),build_args={'BASE_IMAGE':config.base_image})
 app=sdk.App(PREFIX+'-offline-worker')
 secrets=[sdk.Secret.from_name(n) for n in config.secret_names]
 mounts={'/models':sdk.Volume.from_name(config.model_volume,create_if_missing=False),'/control':sdk.Volume.from_name(config.control_volume,create_if_missing=False),'/artifacts':sdk.CloudBucketMount(config.bucket,secret=sdk.Secret.from_name(config.secret_names[0]),read_only=False)}
 @app.function(image=image,secrets=secrets,volumes=mounts,timeout=config.timeout,retries=0,min_containers=0,max_containers=config.max_containers)
 @sdk.concurrent(max_inputs=config.concurrency)
 def worker(envelope):
  # Initialize/check the ledger in the worker's persistent control mount,
  # not an ephemeral captured host directory. Single container/input only.
  active_budget=Budget(budget.path,budget.run,str(budget.cap))
  active_budget.reserve(envelope['id'],config.known_job_bound,inputs_hash(envelope))
  return (execute or entrypoint)(envelope,storage_factory(),pathlib.Path('/opt/pipeline/cloud/.scratch')/config.run_id/envelope['id'],runtime_root='/opt/pipeline')
 return app,worker
