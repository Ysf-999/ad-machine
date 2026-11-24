"""Numeric host comparison only. Never equates partial metrics with cloud parity."""
import argparse,json,pathlib,re,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parent.parent
BIN=next((ROOT/'.venv').glob('lib/python*/site-packages/static_ffmpeg/bin/darwin_arm64'))
def call(args):return subprocess.run([str(x) for x in args],capture_output=True,text=True,check=True)
def meta(f):
 j=json.loads(call([BIN/'ffprobe','-v','error','-show_entries','format=duration,size:stream=codec_type,width,height,r_frame_rate','-of','json',f]).stdout)
 return {'duration':float(j['format']['duration']),'size':int(j['format']['size']),'video':next(s for s in j['streams'] if s['codec_type']=='video')}
def compare(a,b):
 x,y=meta(a),meta(b)
 audio={}
 for label,f in [('original',a),('worker',b)]:
  r=call([ROOT/'.venv/bin/python',ROOT/'tools/audio_check.py',f,'--json']);audio[label]=json.loads(r.stdout)
 # Decode sampled frames only; no images are displayed/read into an agent context.
 r=call([BIN/'ffmpeg','-v','info','-i',a,'-i',b,'-filter_complex','[0:v]fps=1,scale=270:480,setpts=PTS-STARTPTS[a];[1:v]fps=1,scale=270:480,setpts=PTS-STARTPTS[b];[a][b]ssim','-an','-f','null','-'])
 m=re.search(r'All:([0-9.]+)',r.stderr)
 fps=x['video']['r_frame_rate'];n,d=map(int,fps.split('/'));tol=d/n
 return {'original':x,'worker':y,'duration_delta_seconds':y['duration']-x['duration'],'duration_within_one_frame':abs(y['duration']-x['duration'])<=tol,
         'audio_check':audio,'ssim_sampled_1fps_270x480':float(m.group(1)) if m else None,
         'full_parity':'NOT_CHECKED: faster-whisper, caption sync, A/V and preflight gates required separately'}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('original',type=pathlib.Path);p.add_argument('worker',type=pathlib.Path);p.add_argument('--out',type=pathlib.Path,required=True);a=p.parse_args();r=compare(a.original,a.worker);a.out.write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))
