# Library v2, 2026-11-09 (agentchad.io). Keys only from your own environment; nothing here is account-specific.
"""comp.py <spec.json>
Final render: builds and runs one ffmpeg command. Uses the ORIGINAL video everywhere and the cleaned (caption-removed) video
only inside the bands you list, with feathered edges, then PNG overlays, caption lists and the new audio.
spec: {"src": "<original.mp4>", "clean": "<cleaned.mp4>", "out": "<out.mp4>", "bitrate": "12M", "dur": <seconds>, "fps": <fps>,
 "audio": "src" | "<mix.wav>", "afilter": null | "<ffmpeg audio filter>", "W": <frame width>,
 "bands": [{"x":0,"y":..,"w":..,"h":..,"t0":0,"t1":999,"f":6}], "pngs": [{"file":..,"t0":..,"t1":..}],
 "caps": "<dir>/list.ffconcat" | ["<list1>", "<list2>"] | null}
Env VCODEC: default hevc_videotoolbox (Mac hardware HEVC); use libx264 on other machines or when the player needs H.264."""
import sys, json, subprocess, os
if len(sys.argv) < 2:
    sys.exit(__doc__)
s = json.load(open(sys.argv[1]))
VCODEC = os.environ.get('VCODEC', 'hevc_videotoolbox')
ins = ['-i', s['src'], '-i', s['clean']]; n = 2; fl = []
B = s.get('bands', [])
fl.append(f"[1:v]split={max(len(B), 1)}" + ''.join(f'[cl{i}]' for i in range(max(len(B), 1))))
cur = '0:v'
for i, b in enumerate(B):
    F = b.get('f', 6)
    fx = "255" if b['x'] == 0 and b['w'] >= s.get('W', 99999) else f"255*min(1,min(X,W-1-X)/{F})"
    fl.append(f"[cl{i}]crop={b['w']}:{b['h']}:{b['x']}:{b['y']},format=yuva420p,geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':a='min({fx},255*min(1,min(Y,H-1-Y)/{F}))'[b{i}]")
    fl.append(f"[{cur}][b{i}]overlay={b['x']}:{b['y']}:enable='between(t,{b['t0']},{b['t1']})'[v{i}]"); cur = f'v{i}'
if not B:
    fl[-1] = fl[-1] + ';[cl0]nullsink'
for j, p in enumerate(s.get('pngs', [])):
    ins += ['-loop', '1', '-i', p['file']]; k = n; n += 1
    fl.append(f"[{k}:v]format=rgba[p{j}];[{cur}][p{j}]overlay=0:0:shortest=1:enable='between(t,{p['t0']},{p['t1']})'[q{j}]"); cur = f'q{j}'
caps = s.get('caps') or []
if isinstance(caps, str):
    caps = [caps]
for j, c in enumerate(caps):
    ins += ['-f', 'concat', '-safe', '0', '-i', c]; k = n; n += 1
    fl.append(f"[{k}:v]fps={s['fps']},format=rgba[cp{j}];[{cur}][cp{j}]overlay=0:0:eof_action=pass[cc{j}]"); cur = f'cc{j}'
fl.append(f"[{cur}]format=yuv420p[vout]")
amap = ['-map', '0:a', '-c:a', 'copy']
if s.get('audio', 'src') != 'src':
    ins += ['-i', s['audio']]; k = n; n += 1
    fl.append(f"[{k}:a]{s.get('afilter') or 'anull'}[aout]"); amap = ['-map', '[aout]', '-c:a', 'aac', '-b:a', '256k']
vtag = ['-tag:v', 'hvc1'] if 'hevc' in VCODEC else []
cmd = ['ffmpeg', '-v', 'error', '-y', *ins, '-filter_complex', ';'.join(fl), '-map', '[vout]', *amap, '-c:v', VCODEC, '-b:v', s['bitrate'], *vtag, '-t', str(s['dur']), '-movflags', '+faststart', s['out']]
print(' '.join(cmd[-14:]), flush=True)
subprocess.run(cmd, check=True); print('wrote', s['out'])
