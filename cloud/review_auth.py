"""Private review authentication, pure application tests only; no listener."""
from __future__ import annotations
import base64,contextlib,hashlib,hmac,json,pathlib,re,secrets,sqlite3,time,uuid
from http.cookies import SimpleCookie
from urllib.parse import urlsplit,parse_qs,unquote
class Denied(PermissionError):pass
class Limited(Denied):pass
def raw(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def ad_name(ad):
 if not isinstance(ad,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',ad):raise Denied('Invalid ad scope')
 return ad
class Auth:
 def __init__(self,path,*,key,clock=time.time,limit=30):
  if not isinstance(key,bytes) or len(key)<32 or type(limit) is not int or limit<1:raise ValueError('Separate strong review key and positive limit required')
  self.path=pathlib.Path(path);self.path.parent.mkdir(parents=True,exist_ok=True);self.key=key;self.clock=clock;self.limit=limit
  with self.db() as d:d.executescript('CREATE TABLE IF NOT EXISTS used(id TEXT PRIMARY KEY,at REAL);CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,ad TEXT,expires REAL);CREATE TABLE IF NOT EXISTS rates(peer TEXT,bucket INTEGER,count INTEGER,PRIMARY KEY(peer,bucket));CREATE TABLE IF NOT EXISTS audit(at REAL,peer TEXT,ad TEXT,event TEXT);')
 @contextlib.contextmanager
 def db(self):
  d=sqlite3.connect(self.path,timeout=30,isolation_level='IMMEDIATE');d.execute('PRAGMA synchronous=FULL')
  try:
   with d:yield d
  finally:d.close()
 def _peer(self,peer):return hmac.new(self.key,str(peer).encode(),hashlib.sha256).hexdigest()
 def rate(self,peer):
  peer=self._peer(peer);bucket=int(self.clock()//60)
  with self.db() as d:
   d.execute('BEGIN IMMEDIATE');d.execute('INSERT INTO rates VALUES (?,?,1) ON CONFLICT(peer,bucket) DO UPDATE SET count=count+1',(peer,bucket))
   n=d.execute('SELECT count FROM rates WHERE peer=? AND bucket=?',(peer,bucket)).fetchone()[0]
  if n>self.limit:raise Limited('Rate limit')
 def audit(self,peer,ad,event):
  with self.db() as d:d.execute('INSERT INTO audit VALUES (?,?,?,?)',(self.clock(),self._peer(peer),ad_name(ad),event))
 def issue(self,ad,scope,*,ttl=60):
  ad_name(ad)
  if scope not in ['view','decision'] or type(ttl) is not int or not 1<=ttl<=3600:raise ValueError('Bounded scoped access required')
  now=int(self.clock());p={'v':1,'domain':'admachine-review-access-v1','id':uuid.uuid4().hex,'ad':ad,'scope':scope,'issued':now,'expires':now+ttl};b=base64.urlsafe_b64encode(raw(p)).rstrip(b'=')
  return b.decode()+'.'+hmac.new(self.key,b,hashlib.sha256).hexdigest()
 def consume(self,token,ad,scope):
  try:
   if not isinstance(token,str) or len(token)>4096:raise ValueError
   body,signature=token.rsplit('.',1)
   if not hmac.compare_digest(signature,hmac.new(self.key,body.encode(),hashlib.sha256).hexdigest()):raise ValueError
   p=json.loads(base64.urlsafe_b64decode(body+'='*((-len(body))%4)))
   if set(p)!={'v','domain','id','ad','scope','issued','expires'} or type(p['v']) is not int or p['v']!=1 or p['domain']!='admachine-review-access-v1' or p['ad']!=ad_name(ad) or p['scope']!=scope or type(p['issued']) is not int or type(p['expires']) is not int or not p['issued']<=self.clock()<p['expires'] or not 0<p['expires']-p['issued']<=3600:raise ValueError
  except (ValueError,TypeError,KeyError):raise Denied('Scoped access rejected') from None
  with self.db() as d:
   try:d.execute('INSERT INTO used VALUES (?,?)',(p['id'],self.clock()))
   except sqlite3.IntegrityError:raise Denied('Replay rejected') from None
  return p
 def session(self,ad,expires):
  token=secrets.token_urlsafe(32)
  with self.db() as d:d.execute('INSERT INTO sessions VALUES (?,?,?)',(hmac.new(self.key,b'review-session-v1\n'+token.encode(),hashlib.sha256).hexdigest(),ad_name(ad),expires))
  return token
 def check_session(self,token,ad):
  with self.db() as d:r=d.execute('SELECT ad,expires FROM sessions WHERE hash=?',(hmac.new(self.key,b'review-session-v1\n'+token.encode(),hashlib.sha256).hexdigest(),)).fetchone()
  if not r or r[0]!=ad or self.clock()>=r[1]:raise Denied('Session rejected')
class SecureApplication:
 requires_headers=True
 def __init__(self,application,auth,*,origin,workspace_for):
  url=urlsplit(origin)
  if url.scheme!='https' or not url.hostname or url.path or url.query or url.fragment or url.username:raise ValueError('Owner exact HTTPS origin required')
  if hasattr(application,'key') and hmac.compare_digest(application.key,auth.key):raise ValueError('Review access and production signing keys must differ')
  self.app=application;self.auth=auth;self.origin=origin;self.workspace_for=workspace_for
 def handle(self,method,path,body=b'',*,headers=None,peer='local'):
  headers=headers or {};base={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; script-src 'none'; frame-ancestors 'none'"};ad='invalid'
  def error(code):
   self.auth.audit(peer,ad if re.fullmatch('[A-Za-z0-9_-]{1,100}',ad) else 'invalid','http_'+str(code))
   return code,base,b'Access refused'
  try:
   self.auth.rate(peer);url=urlsplit(path);route=unquote(url.path);parts=route.split('/')
   if len(parts)<4 or parts[1]!='ads' or any(p in ['', '.', '..'] for p in parts[1:]) or '\\' in route:return error(404)
   ad=ad_name(parts[2])
   if method=='GET':
    if any(p.startswith('.') or p in ['plan.json','jobs.jsonl'] or p.endswith(('.sqlite','.py','.lock')) for p in parts[3:]):return error(404)
    access=parse_qs(url.query).get('access',[])
    if access:
     if len(access)!=1:return error(403)
     p=self.auth.consume(access[0],ad,'view');session=self.auth.session(ad,p['expires']);base.update({'Set-Cookie':'review-session='+session+'; Path=/ads/'+ad+'/; Secure; HttpOnly; SameSite=Strict; Max-Age='+str(max(0,p['expires']-int(self.auth.clock()))),'Location':route})
     self.auth.audit(peer,ad,'view_link_exchanged');return 302,base,b''
    cookie=SimpleCookie();cookie.load(headers.get('Cookie',''));value=cookie.get('review-session')
    if value is None:raise Denied('Session required')
    self.auth.check_session(value.value,ad);result=self.app.handle(method,route,body)
   elif method=='POST' and parts[3:] == ['decision']:
    if len(body)>65536:return error(413)
    if headers.get('Origin')!=self.origin:raise Denied('Origin refused')
    auth=headers.get('Authorization','')
    if not auth.startswith('Bearer '):raise Denied('Decision token required')
    decision=json.loads(body);payload=decision.get('payload',{})
    if payload.get('workspace_id')!=self.workspace_for(ad):raise Denied('Decision belongs to another ad')
    self.auth.consume(auth[7:],ad,'decision')
    result=self.app.handle('POST','/decision',body)
   else:return error(405)
   self.auth.audit(peer,ad,'request_accepted' if result[0]<400 else 'underlying_rejected');return result[0],{**result[1],**base},result[2]
  except Limited:return error(429)
  except (Denied,ValueError,TypeError,KeyError):
   self.auth.audit(peer,ad if re.fullmatch('[A-Za-z0-9_-]{1,100}',ad) else 'invalid','request_rejected');return error(403)
