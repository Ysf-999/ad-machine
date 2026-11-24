"""Numeric frame corpus builder. Never displays images or writes original projects."""
import json,pathlib,subprocess,time
from cloud.ocr import AppleVision,SOURCE,tilt
from runner.stage import digest
from hygiene import require_space,guarded_run,_scratch_path

def build(masters,output,*,ffmpeg):
 output=_scratch_path(output);output.mkdir(parents=True,exist_ok=True);(output/'.keep').write_text('OCR validation corpus; preserve until parity complete\n');backend=AppleVision();rows=[]
 for name,master in masters.items():
  require_space();master=pathlib.Path(master);before=digest(master);folder=output/name
  if folder.exists():raise ValueError('Fresh corpus required')
  folder.mkdir();start=time.monotonic()
  cmd=[str(ffmpeg),'-nostdin','-v','error','-i',str(master),'-vf','fps=1,scale=720:-2',str(folder/'f%05d.png')]
  r=guarded_run(cmd,capture_output=True,text=True,timeout=300)
  if r.returncode:raise RuntimeError('Frame extraction failed')
  frames=[]
  for i,p in enumerate(sorted(folder.glob('f*.png'))):
   require_space(min_free_gb=8);raw=backend.read(p);frames.append({'frame':i,'time_seconds':float(i),'path':str(p),'sha256':digest(p),'ocr':raw})
  if not frames:raise RuntimeError('No extracted frames')
  after=digest(master)
  if before!=after:raise RuntimeError('Original master changed')
  row={'name':name,'master':str(master),'master_sha256':before,'source_unchanged':True,'frames':frames,'tilt':tilt([f['ocr'] for f in frames]),'wall_seconds':time.monotonic()-start};rows.append(row)
  (output/(name+'.json')).write_text(json.dumps(row,indent=2)+'\n');print(name,len(frames),'tilt groups',len(row['tilt']),flush=True)
 return {'version':1,'source_sha256':digest(SOURCE),'backend':backend.name,'sampling':'fps=1,scale=720:-2; original preflight sampling','masters':rows,'linux_parity':'NOT CHECKED'}
