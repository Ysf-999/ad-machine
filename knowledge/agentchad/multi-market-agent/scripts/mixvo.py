# Library v2, 2026-11-09 (agentchad.io). Keys only from your own environment; nothing here is account-specific.
"""PROJ=<dir> mixvo.py <out.wav> <video_seconds>
Builds one voice track: every line in <PROJ>/schedule.json is placed at its start time (mono, 48 kHz), padded to the video length."""
import os, json, subprocess, sys
if len(sys.argv) < 3 or 'PROJ' not in os.environ:
    sys.exit(__doc__)
P = os.environ['PROJ']; out, DUR = sys.argv[1], float(sys.argv[2])
s = json.load(open(f'{P}/schedule.json')); ins = []; fl = []
for k, x in enumerate(s):
    ins += ['-i', x['file']]; ms = int(round(x['start'] * 1000)); fl.append(f'[{k}:a]adelay={ms}|{ms}[a{k}]')
fl.append(''.join(f'[a{k}]' for k in range(len(s))) + f'amix=inputs={len(s)}:normalize=0,apad=whole_dur={DUR},atrim=0:{DUR}[out]')
subprocess.run(['ffmpeg', '-v', 'error', '-y', *ins, '-filter_complex', ';'.join(fl), '-map', '[out]', '-ar', '48000', '-ac', '1', out], check=True)
print('wrote', out)
