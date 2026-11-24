"""Authenticated owner-Mac callback application. Pure handler; never binds/listens."""
from __future__ import annotations
import contextlib,hashlib,hmac,json,pathlib,sqlite3,time,uuid
from cloud import llm
LLM_GATES=('plan_review','qc','masterqc','semantic_broll')
MAX_BYTES=32*1024*1024

def gate_state(checks):
 state={}
 for name in LLM_GATES:
  row=checks.get(name,{})
  status='not_checked' if row.get('check_status')!='checked' else ('checked_pass' if row.get('verdict') in ['PASS','SHIP'] else 'failed')
  state[name]={'status':status,'production_gate_passed':False,'reason':'genuine exact-input report validation still required' if status=='checked_pass' else 'not checked' if status=='not_checked' else 'checker did not pass'}
 for name in ['final','hooks','deliver','upload']:
  state[name]={'status':'blocked','production_gate_passed':False,'reason':'missing/failed Claude evidence' if any(state[n]['status']!='checked_pass' for n in ['qc','masterqc']) else 'owner/full production validator requirements remain'}
 return state

def _body(payload):return json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def _signature(key,expiry,nonce,body):return hmac.new(key,b'admachine-callback-v1\n'+str(expiry).encode()+b'\n'+nonce.encode()+b'\n'+body,hashlib.sha256).hexdigest()
class Service:
 def __init__(self,path,*,key,cli,models,clock=time.time):
  if not isinstance(key,bytes) or len(key)<32:raise ValueError('Private callback key required')
  self.path=pathlib.Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.key=key;self.cli=cli;self.models=frozenset(models);self.clock=clock
  with self.db() as d:d.execute('CREATE TABLE IF NOT EXISTS calls (nonce TEXT PRIMARY KEY,at REAL,status TEXT)')
 @contextlib.contextmanager
 def db(self):
  d=sqlite3.connect(self.path,timeout=30,isolation_level='IMMEDIATE');d.execute('PRAGMA synchronous=FULL')
  try:
   with d:yield d
  finally:d.close()
 def handle(self,body,headers):
  if not isinstance(body,bytes) or len(body)>MAX_BYTES:return 413,{'check_status':'not_checked','reason':'size_limit'}
  try:
   expiry=int(headers['X-Expires']);nonce=headers['X-Nonce'];signature=headers['X-Signature']
   if len(nonce)!=32 or any(c not in '0123456789abcdef' for c in nonce) or not self.clock()<=expiry<=self.clock()+300 or not hmac.compare_digest(signature,_signature(self.key,expiry,nonce,body)):return 403,{'check_status':'not_checked','reason':'auth_failed'}
   payload=json.loads(body);request=payload['request']
   if payload.get('version')!=1 or request.get('model') not in self.models or type(request.get('max_tokens')) is not int or not 0<request['max_tokens']<=64000:raise ValueError
  except (ValueError,KeyError,TypeError):return 403,{'check_status':'not_checked','reason':'request_refused'}
  with self.db() as d:
   d.execute('BEGIN IMMEDIATE')
   if d.execute('SELECT 1 FROM calls WHERE nonce=?',(nonce,)).fetchone():return 409,{'check_status':'not_checked','reason':'replay'}
   # Persist before CLI. A lost response may have consumed usage: never retry.
   d.execute('INSERT INTO calls VALUES (?,?,?)',(nonce,self.clock(),'started'))
  try:result=llm.handle_callback_request(payload,cli=self.cli);status='checked';code=200
  except Exception:result={'check_status':'not_checked','reason':'execution_failed'};status='not_checked';code=503
  with self.db() as d:d.execute('UPDATE calls SET status=? WHERE nonce=?',(status,nonce))
  return code,result
class Client:
 def __init__(self,transport,*,key,clock=time.time):
  if not isinstance(key,bytes) or len(key)<32:raise ValueError('Private callback key required')
  self.transport=transport;self.key=key;self.clock=clock
 def signed(self,payload):
  body=_body(payload);expiry=int(self.clock()+60);nonce=uuid.uuid4().hex
  return body,{'X-Expires':str(expiry),'X-Nonce':nonce,'X-Signature':_signature(self.key,expiry,nonce,body)}
 def __call__(self,payload):
  body,headers=self.signed(payload);code,result=self.transport(body,headers)
  if code!=200:raise llm.NotCheckedError('callback','authenticated_callback_failed')
  return result
