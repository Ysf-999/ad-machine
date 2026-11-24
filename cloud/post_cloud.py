"""Idempotent mandatory local-only gate after a hash-bound cloud render."""
import hashlib,json,pathlib,re
from cloud.runner.stage import digest
class PostCloudGate:
 def __init__(self,root):
  self.root=pathlib.Path(root).resolve();scratch=pathlib.Path(__file__).resolve().parent/'.scratch'
  if not self.root.is_relative_to(scratch):raise ValueError('Scratch-only gate receipts')
  self.root.mkdir(parents=True,exist_ok=True)
 def run(self,master,expected,context,run_checks,*,linux_caption=None):
  master=pathlib.Path(master)
  if digest(master)!=expected:raise ValueError('Master hash mismatch before local gate')
  key=hashlib.sha256(json.dumps([expected,context,'post-cloud-local-v1']).encode()).hexdigest();path=self.root/(key+'.json')
  if path.exists():
   result=json.loads(path.read_text())
   if any(digest(name)!=sha for name,sha in result['evidence_sha256'].items()):raise ValueError('Cached gate evidence hash mismatch')
   return caption_comparison(result,linux_caption)
  checks=run_checks();pf=pathlib.Path(checks['preflight_path']) if checks.get('preflight_path') else None
  text=pf.read_text() if pf and pf.is_file() else '';evidence={str(pf):digest(pf)} if text else {}
  for g in ['caption_sync','av_check','preflight']:
   if checks.get(g,{}).get('log_path'):
    log=pathlib.Path(checks[g]['log_path']);evidence[str(log)]=digest(log)
  auto=text.split('## Owner taste rules')[0]
  passes=(all(checks.get(g,{}).get('returncode')==0 for g in ['caption_sync','av_check','preflight'])
   and 'CAPTION SYNC PASS' in checks.get('caption_sync',{}).get('output','')
   and 'PASS: sound and picture in sync' in checks.get('av_check',{}).get('output','')
   and re.search(r'\b0 FAIL\b',checks.get('preflight',{}).get('output',''))
   and 'PASS T13 no tilted text found' in auto and not re.search(r'^- FAIL\b',auto,re.M)
   and not re.search(r'^- \[(?:x|n/a)\]',text,re.M|re.I))
  if digest(master)!=expected:raise ValueError('Master hash mismatch after local gate')
  result={'kind':'post-cloud-local-gate','master_sha256':expected,'context':context,'checks':checks,'evidence_sha256':evidence,
   'status':'RENDERED_PREFLIGHT_COMPLETE_NOT_APPROVED' if passes else 'BLOCKED_LOCAL_GATE','deliverable':False,'approved':False,
   'manual_boxes_unanswered':len(re.findall(r'^- \[ \]',text,re.M)),'manual_boxes_answered':False}
  path.write_text(json.dumps(result,indent=2)+'\n');return caption_comparison(result,linux_caption)

def caption_comparison(result,linux_caption):
 """Linux ASR is informational; never substitutes for a missing/failing Mac check."""
 if linux_caption is None:return result
 if linux_caption.get('master_sha256')!=result['master_sha256']:
  raise ValueError('Linux caption evidence is for another master')
 local=result['checks'].get('caption_sync',{})
 text=local.get('output','')
 local_pass=local.get('returncode')==0 and 'CAPTION SYNC PASS' in text and 'FAIL' not in text
 remote_code=linux_caption.get('checker_returncode',linux_caption.get('returncode'))
 remote_pass=remote_code==0 if type(remote_code) is int else None
 return {**result,'caption_comparison':{'authority':'native-mac-mlx','local_passed':local_pass,'linux_informational':dict(linux_caption),'linux_passed':remote_pass,'disagreement':remote_pass is not None and remote_pass!=local_pass}}
