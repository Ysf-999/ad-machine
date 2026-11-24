"""Run original delivery checks on a scratch result; never marks manual QA passed."""
import json,pathlib,sys,time
from runner import Manifest,run_stage
ROOT=pathlib.Path(__file__).resolve().parents[1]
project=pathlib.Path(sys.argv[1]).resolve()
base=['plan.json','MASTER.mp4','VO/vo.mp3','EDIT_KIT/captions.ass']
for tool in ['caption_sync_check','av_check','preflight']:
 m=Manifest(tool,'check',base,['feedback','footage/BANNED_CLIPS.json'] if tool=='preflight' else [],
            ['PREFLIGHT.md'] if tool=='preflight' else [],timeout=900,
            model_cache='models--mlx-community--whisper-large-v3-turbo' if tool in {'preflight','caption_sync_check'} else None)
 out=ROOT/'cloud/.scratch'/(tool+'-'+str(time.time_ns()))
 r=run_stage(ROOT,project,m,out)
 print(json.dumps({'gate':tool,'result':str(out),'status':r['status'],'wall_seconds':r['wall_seconds']}),flush=True)
 print((out/'stage.log').read_text(),flush=True)
 if r['status']!='done':raise SystemExit(1)
