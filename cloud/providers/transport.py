"""Source-matched HTTP contracts, exercised ONLY against synthetic replay replies.

Endpoints and JSON fields come from unchanged tools/kie.py create/status and
tools/ad.py _tts, not a live API probe. No SDK, auth/env read, asset fetch or
automatic retry. RealHTTP refuses even --go; explicit future owner admission
and a separate implementation change are required to enable actual requests.
JournalAdapter must wrap submit/poll; it commits spend+intent before submission
and fsyncs IDs before polling. ElevenLabs polls a local synchronous receipt.
"""
import base64,copy,hashlib,json,math,pathlib,re
from cloud.approval import _atomic,_json
from cloud.hygiene import _scratch_path
from cloud.providers.paid import RealCallsDisabled

class RealHTTP:
 def __init__(self,*,go=False):self.go=go
 def request(self,*args,**kwargs):raise RealCallsDisabled('Actual paid HTTP disabled for this task, even with go')

class ReplayHTTP:
 """Canned API-shaped replies. Explicitly synthetic, never historical receipts."""
 def __init__(self,replies):self.replies=iter(copy.deepcopy(replies));self.requests=[]
 def request(self,method,url,**kwargs):
  self.requests.append({'method':method,'url':url,**copy.deepcopy(kwargs)})
  reply=next(self.replies)
  if isinstance(reply,Exception):raise reply
  if not isinstance(reply,dict):raise ValueError('JSON object required')
  return reply

def _request(job):
 r=job['inputs']['provider_request']
 if not isinstance(r,dict):raise ValueError('Explicit request object required')
 return copy.deepcopy(r)
def _id(value):
 if not isinstance(value,str) or not re.fullmatch('[A-Za-z0-9_-]{1,200}',value):raise ValueError('Invalid receipt identifier')
 return value
class KieTransport:
 def __init__(self,http):self.http=http;self.mock=isinstance(http,ReplayHTTP)
 def submit(self,job):
  body=_request(job)
  if set(body)!={'model','input'} or not isinstance(body['model'],str) or not body['model'] or not isinstance(body['input'],dict):raise ValueError('Explicit model/input required')
  r=self.http.request('POST','https://api.kie.ai/api/v1/jobs/createTask',json=body,timeout=120)
  if r.get('code')!=200:raise ValueError('Create rejected; do not blindly retry an ambiguous submission')
  return _id(r['data']['taskId'])
 def poll(self,job,receipt):
  _id(receipt);r=self.http.request('GET','https://api.kie.ai/api/v1/jobs/recordInfo',params={'taskId':receipt},timeout=120)
  if r.get('code')!=200:raise ValueError('Status refused')
  data=r['data']
  if data.get('taskId')!=receipt:raise ValueError('Provider receipt mismatch')
  state=data.get('state')
  if state=='fail':return {'status':'failed'}
  if state in {'waiting','queuing','generating'}:return {'status':'pending'}
  if state!='success':raise ValueError('Unknown provider state')
  result=json.loads(data['resultJson']);urls=result['resultUrls']
  if not isinstance(urls,list) or not urls or any(not isinstance(u,str) or not u.startswith('https://') for u in urls):raise ValueError('Missing HTTPS result references')
  return {'status':'done','result':{'provider_id':receipt,'asset_references':urls,'mock':self.mock,'approved':False,'deliverable':False}}

class ElevenTransport:
 def __init__(self,http,receipts):
  self.http=http;self.mock=isinstance(http,ReplayHTTP);self.root=_scratch_path(receipts);self.root.mkdir(parents=True,exist_ok=True)
 def submit(self,job):
  r=_request(job)
  if not {'voice_id','text','voice_settings'}<=r.keys() or set(r)-{'voice_id','text','voice_settings','previous_text','next_text'}:raise ValueError('Unknown TTS fields')
  voice=_id(r.pop('voice_id'))
  if not isinstance(r['text'],str) or not r['text'] or not isinstance(r['voice_settings'],dict):raise ValueError('Text and settings required')
  for field in ['previous_text','next_text']:
   if field in r:
    if not isinstance(r[field],str):raise ValueError('Context text required')
    r[field]=r[field][-300:] if field=='previous_text' else r[field][:300]
  r['model_id']='eleven_multilingual_v2'
  response=self.http.request('POST','https://api.elevenlabs.io/v1/text-to-speech/'+voice+'/with-timestamps',params={'output_format':'mp3_44100_128'},json=r,timeout=120)
  audio=base64.b64decode(response['audio_base64'],validate=True);alignment=response['alignment']
  keys=['characters','character_start_times_seconds','character_end_times_seconds']
  if not audio or any(not isinstance(alignment.get(k),list) for k in keys):raise ValueError('Audio and timestamp arrays required')
  chars,starts,ends=[alignment[k] for k in keys]
  if not chars or not len(chars)==len(starts)==len(ends) or any(not isinstance(c,str) for c in chars):raise ValueError('Alignment length mismatch')
  if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in starts+ends) or any(a>b for a,b in zip(starts,ends)) or starts!=sorted(starts):raise ValueError('Invalid timing arrays')
  record={'request_sha256':hashlib.sha256(_json(_request(job))).hexdigest(),'response':response,'audio_sha256':hashlib.sha256(audio).hexdigest(),'mock':self.mock}
  identity=hashlib.sha256(_json(record)).hexdigest();path=self.root/(identity+'.json')
  if path.exists():
   if path.read_bytes()!=_json(record)+b'\n':raise ValueError('Receipt hash conflict')
  else:_atomic(path,_json(record)+b'\n')
  return 'local-eleven-'+identity
 def poll(self,job,receipt):
  if not re.fullmatch('local-eleven-[0-9a-f]{64}',receipt):raise ValueError('Local synchronous receipt required')
  identity=receipt.removeprefix('local-eleven-');path=self.root/(identity+'.json')
  if path.is_symlink():raise ValueError('Receipt symlink refused')
  record=json.loads(path.read_text())
  if hashlib.sha256(_json(record)).hexdigest()!=identity or record['request_sha256']!=hashlib.sha256(_json(_request(job))).hexdigest():raise ValueError('Receipt/input hash mismatch')
  return {'status':'done','result':{'receipt':receipt,'receipt_path':str(path),'audio_sha256':record['audio_sha256'],'kind':'local-synchronous-receipt','mock':record['mock'],'approved':False,'deliverable':False}}
