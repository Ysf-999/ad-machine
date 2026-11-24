"""Provider-neutral isolation plans. Linux code is written/tested, never run here."""
from __future__ import annotations
import dataclasses,json,os,pathlib,re,shutil,subprocess
class Unavailable(RuntimeError):pass
MODAL_ATTESTATION = 'admachine-cpu-no-secrets-network-blocked-v1'

class ModalContainer:
 """Only the explicit owner-admitted Modal wrapper may trust its outer sandbox.

 No implicit Linux fallback. The wrapper owns block_network/restrict_modal_access;
 credential absence and executable/path refusals are still checked here.
 """
 def __init__(self):
  if os.environ.get('ADMACHINE_MODAL_CONTAINER') != MODAL_ATTESTATION:
   raise Unavailable('Explicit Modal container attestation required')
  if any(k.startswith(('KIE_', 'ELEVENLABS_', 'ANTHROPIC_', 'AWS_', 'SLACK_', 'MODAL_TOKEN_')) for k in os.environ):
   raise Unavailable('Secret-bearing environment refused')
 def plan(self,r,inputs,output,argv):
  self.__init__();paths(inputs,output)
  return Plan(command(r,argv),r.environment(),timeout=600,label='Owner-admitted Modal sandbox; not general Linux proof')
@dataclasses.dataclass(frozen=True)
class Runtime:
 python:str;ffmpeg:str;ffprobe:str;fonts:str;models:str;tmp:str
 image:str='';directory:str='/runtime';rootfs:str='/runtime/rootfs'
 def __post_init__(self):
  if self.directory=='/' or self.rootfs=='/':raise ValueError('Host root must never be a runtime/rootfs mount')
  for value in [self.python,self.ffmpeg,self.ffprobe,self.fonts,self.models,self.tmp,self.directory,self.rootfs]:
   p=pathlib.PurePosixPath(value)
   if not p.is_absolute() or '..' in p.parts or any(c in value for c in '\n\r\x00,:'):raise ValueError('Absolute safe manifest runtime paths required')
  for value in [self.python,self.ffmpeg,self.ffprobe,self.fonts,self.models,self.rootfs]:
   if not pathlib.PurePosixPath(value).is_relative_to(self.directory):raise ValueError('Runtime files must be below declared mount')
  if not pathlib.PurePosixPath(self.tmp).is_relative_to('/work'):raise ValueError('Private temp must be under writable work mount')
 def environment(self):
  return {'PATH':':'.join(dict.fromkeys([str(pathlib.PurePosixPath(p).parent) for p in [self.python,self.ffmpeg,self.ffprobe]]))+':/usr/bin:/bin','HOME':'/work/home','TMPDIR':self.tmp,'HF_HUB_CACHE':self.models,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','PYTHONDONTWRITEBYTECODE':'1','FFMPEG_NO_GATE':'1','CLAUDE_BACKEND':'skip','MOMENTS_BACKEND':'skip','LANG':'C.UTF-8','ADMACHINE_FONTS_DIR':self.fonts}
@dataclasses.dataclass(frozen=True)
class Plan:
 argv:list[str];env:dict[str,str];timeout:int=1800;label:str='written-not-run'
def paths(inputs,output):
 for p in [inputs,output]:
  if not pathlib.PurePosixPath(p).is_absolute() or any(c in p for c in '\x00\n\r,:') or '..' in pathlib.PurePosixPath(p).parts:raise ValueError('Safe absolute mounts required')
 if pathlib.PurePosixPath(inputs).is_relative_to(output) or pathlib.PurePosixPath(output).is_relative_to(inputs):raise ValueError('Disjoint input and output mounts required')
def command(runtime,argv):
 if not argv or argv[0] not in [runtime.python,runtime.ffmpeg,runtime.ffprobe] or any(not isinstance(v,str) or '\x00' in v for v in argv):raise ValueError('Only declared runtime executables')
 return list(argv)
class MacSeatbelt:
 def __init__(self,binary):self.binary=binary
 def prefix(self,work,root,*,deny_system_fonts=False):
  q=lambda p:json.dumps(str(pathlib.Path(p).resolve()))
  policy=[self.binary,'-p','(version 1)(allow default)(deny network*)'+f'(deny file-write* (require-all (require-not (subpath {q(work)})) (require-not (literal "/dev/null"))))'+f'(deny file-read* (require-all (subpath {q(root)}) (require-not (subpath {q(pathlib.Path(root)/".venv")})) (require-not (subpath {q(work)}))))']
  if deny_system_fonts:
   policy[2]+=''.join('(deny file-read* (subpath '+q(p)+'))' for p in ['/System/Library/Fonts','/Library/Fonts',pathlib.Path(root).parent/'Library/Fonts'])
  return policy
 def plan(self,r,inputs,output,argv,*,source_root):
  paths(inputs,output);return Plan(self.prefix(output,source_root)+command(r,argv),r.environment(),label='Mac policy; existing real proof')
class Container:
 def __init__(self,binary):self.binary=binary
 def plan(self,r,inputs,output,argv):
  paths(inputs,output)
  if '@sha256:' not in r.image or not re.fullmatch('[0-9a-f]{64}',r.image.rsplit('@sha256:',1)[1]):raise ValueError('Pinned offline image digest required')
  argv=command(r,argv);env=r.environment();a=[self.binary,'run','--rm','--pull=never','--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=256','--memory=4g','--cpus=2','--user',str(os.getuid())+':'+str(os.getgid()),'--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=64m','-v',inputs+':/input:ro','-v',r.directory+':'+r.directory+':ro','-v',output+':/work:rw','--workdir','/work']
  for k,v in env.items():a+=['--env',k+'='+v]
  return Plan(a+['--entrypoint',argv[0],r.image]+command(r,argv)[1:],{})
class Bubblewrap:
 def __init__(self,binary,unshare):self.binary=binary;self.unshare=unshare
 def plan(self,r,inputs,output,argv):
  paths(inputs,output);a=[self.unshare,'--user','--map-root-user','--net',self.binary,'--unshare-all','--die-with-parent','--new-session','--clearenv','--ro-bind',r.rootfs,'/','--ro-bind',r.directory,r.directory,'--ro-bind',inputs,'/input','--bind',output,'/work','--proc','/proc','--dev','/dev','--tmpfs','/tmp','--chdir','/work','--cap-drop','ALL']
  for k,v in r.environment().items():a+=['--setenv',k,v]
  return Plan(a+['--']+command(r,argv),{})
def probe(platform,*,check=None,which=shutil.which):
 """No daemon/socket probes by default. Trusted opt-in probe is injectable."""
 bins={n:which(n) for n in ['sandbox-exec','docker','bwrap','unshare']};result={**bins,'container':False,'userns':False}
 if check:
  if platform=='linux' and bins['docker']:result['container']=check('container',bins['docker']) is True
  if platform=='linux' and bins['bwrap'] and bins['unshare']:result['userns']=check('userns',[bins['bwrap'],bins['unshare']]) is True
 return result
def select_backend(platform,capabilities):
 if platform=='darwin' and capabilities.get('sandbox-exec'):return MacSeatbelt(capabilities['sandbox-exec'])
 if platform=='linux':
  if capabilities.get('modal-container') is True:return ModalContainer()
  if capabilities.get('container') is True and capabilities.get('docker'):return Container(capabilities['docker'])
  if capabilities.get('userns') is True and capabilities.get('bwrap') and capabilities.get('unshare'):return Bubblewrap(capabilities['bwrap'],capabilities['unshare'])
 raise Unavailable('No positively verified no-network isolation capability')
def run(plan,*,executor=subprocess.run):
 return executor(plan.argv,env=plan.env,timeout=plan.timeout,shell=False,check=True)
