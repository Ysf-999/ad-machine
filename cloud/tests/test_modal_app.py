
from disk_test_support import DiskIndependentTestCase
import importlib,pathlib,tempfile,unittest
from decimal import Decimal
from cloud.worker.modal_app import build_app,Config,Budget,Disabled
from hygiene import SCRATCH
class Fake:
 calls=[]
 class App:
  def __init__(self,name):Fake.calls.append(('App',name))
  def function(self,**kw):Fake.calls.append(('function',kw));return lambda fn:fn
 class Image:
  @staticmethod
  def from_dockerfile(*a,**kw):Fake.calls.append(('image',kw));return 'image'
 class Secret:
  @staticmethod
  def from_name(name):return ('secret',name)
 class Volume:
  @staticmethod
  def from_name(name,**kw):return ('volume',name)
 @staticmethod
 def CloudBucketMount(name,**kw):return ('bucket',name,kw)
 @staticmethod
 def concurrent(**kw):Fake.calls.append(('concurrent',kw));return lambda f:f
class ModalTests(DiskIndependentTestCase):
 def setUp(self):
  Fake.calls=[];self.t=tempfile.TemporaryDirectory(dir=SCRATCH);self.addCleanup(self.t.cleanup);self.p=pathlib.Path(self.t.name)
 def config(self,**kw):return Config(run_id='mock-run',owner_cap='2',known_job_bound='1',base_image='python@sha256:'+'a'*64,linux_lock_sha256='b'*64,**kw)
 def test_import_has_no_sdk_or_side_effects(self):
  import cloud.worker.modal_app as m
  self.assertIs(importlib.import_module('cloud.worker.modal_app'),m);self.assertEqual(Fake.calls,[])
 def test_cap_required_before_sdk_app_or_image(self):
  for cap in [None,'0','unknown','NaN']:
   with self.assertRaises((ValueError,Disabled)):build_app(Config(run_id='x',owner_cap=cap,known_job_bound='1'),modal_module=Fake)
  self.assertEqual(Fake.calls,[])
 def test_fake_modal_definition_never_remote_invokes_and_bounded(self):
  app,fn=build_app(self.config(),modal_module=Fake,storage_factory=lambda:None,execute=lambda *a,**kw:{'mock':True},budget=Budget(self.p/'budget.sqlite','mock-run','2'))
  opts=dict(Fake.calls)['function'];self.assertEqual(opts['retries'],0);self.assertEqual(opts['max_containers'],1);self.assertEqual(opts['min_containers'],0);self.assertEqual(opts['timeout'],1800);self.assertIn('/control',opts['volumes'])
  self.assertEqual(fn({'id':'a'}),{'mock':True});self.assertEqual(fn({'id':'a'}),{'mock':True});self.assertEqual(fn({'id':'b'}),{'mock':True})
  with self.assertRaises(Disabled):fn({'id':'c'})
 def test_budget_durable_idempotent_and_bound_conflicts_refused(self):
  p=self.p/'budget.sqlite';b=Budget(p,'run','2');b.reserve('a','1');b.reserve('a','1');b=Budget(p,'run','2');self.assertEqual(b.reserved(),'1')
  with self.assertRaises(Disabled):b.reserve('a','2')
  b.reserve('b','1')
  with self.assertRaises(Disabled):b.reserve('c','1')
  with self.assertRaises(Disabled):Budget(p,'run','3')
 def test_no_implicit_real_storage_adapter(self):
  with self.assertRaises(Disabled):build_app(self.config(),modal_module=Fake)

 def test_real_definition_refuses_ephemeral_ledger_before_sdk_import(self):
  budget=Budget(self.p/'ephemeral.sqlite','mock-run','2')
  with self.assertRaises(Disabled):build_app(self.config(),storage_factory=lambda:None,budget=budget)
