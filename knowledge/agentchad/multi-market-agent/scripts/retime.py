# Library v2, 2026-11-09 (agentchad.io). Keys only from your own environment; nothing here is account-specific.
# 2026-11-10: finds AGENTCHAD_PY from ~/.agentchad/settings.env and re-starts itself with it when numpy is missing.
"""retime.py <original> <cleaned> <out.mp4> <bitrate>
A caption-removal tool sometimes drops single frames, so its picture runs ahead of the original and the caption band no longer
lines up. Compare frame counts first (ffprobe -count_packets). This aligns the two files frame by frame (monotonic matching,
caption rows ignored) and writes a cleaned video with exactly the original's frame count and rate, repeating a frame at each drop.
Env VCODEC: default hevc_videotoolbox (Mac hardware HEVC); use libx264 elsewhere.
Env CAP_ROWS: the rows to ignore while matching, as fractions of the height (default "0.62,0.80" = a lower caption
band on a full 9:16 frame). For a cropped caption strip, set it to the part of the strip where the text sits.
Needs numpy."""
import sys, subprocess, json, os
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py import need  # noqa: E402  (finds AGENTCHAD_PY: environment, then ~/.agentchad/settings.env)
need(['numpy'])   # another Python: switches to AGENTCHAD_PY by itself, else exit 3 with the install line
import numpy as np
if len(sys.argv) < 5:
    sys.exit(__doc__)
src, cl, out, br = sys.argv[1:5]
VCODEC = os.environ.get('VCODEC', 'hevc_videotoolbox')
pr = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,r_frame_rate', '-of', 'json', src], capture_output=True, text=True).stdout)['streams'][0]
Wd, Hd = pr['width'], pr['height']; fps = pr['r_frame_rate']
_c0, _c1 = (float(v) for v in os.environ.get('CAP_ROWS', '0.62,0.80').split(','))
cap0, cap1 = int(Hd * _c0), int(Hd * _c1)   # skip the caption rows (they differ by design)
def rd(f):
    vf = f'scale=48:{round(Hd * 48 / Wd)},format=gray'
    a = np.frombuffer(subprocess.run(['ffmpeg', '-v', 'error', '-i', f, '-vf', vf, '-f', 'rawvideo', '-'], capture_output=True).stdout, np.uint8)
    h = round(Hd * 48 / Wd); a = a.reshape(-1, h, 48).astype(np.float32)
    k = h / Hd; return np.concatenate([a[:, :int(cap0 * k)], a[:, int(cap1 * k) + 1:]], 1)
A = rd(src); B = rd(cl); n, m = len(A), len(B); print('original', n, 'cleaned', m)
if m > n:
    sys.exit('The cleaned file has MORE frames than the original; this tool only repairs dropped frames.')
INF = 1e18; cost = np.full((n, m), INF); back = np.zeros((n, m), np.int8)
D = lambda i, j: float(np.abs(A[i] - B[j]).mean())
cost[0, 0] = D(0, 0)
for i in range(1, n):
    lo = max(0, i - (n - m) - 2); hi = min(m - 1, i)
    for j in range(lo, hi + 1):
        c0 = cost[i - 1, j]; c1 = cost[i - 1, j - 1] if j > 0 else INF
        if c0 <= c1:
            cost[i, j] = c0 + D(i, j); back[i, j] = 0
        else:
            cost[i, j] = c1 + D(i, j); back[i, j] = 1
j = m - 1; mp = [0] * n
for i in range(n - 1, -1, -1):
    mp[i] = j
    if i > 0 and back[i, j] == 1:
        j -= 1
rep = [i for i in range(1, n) if mp[i] == mp[i - 1]]
print('repeat at original frames', rep, 'mean err', round(cost[n - 1, m - 1] / n, 3))
json.dump(mp, open(out + '.map.json', 'w'))
fs = Wd * Hd * 3
vtag = ['-tag:v', 'hvc1'] if 'hevc' in VCODEC else []
dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', cl, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{Wd}x{Hd}', '-r', fps, '-i', '-', '-c:v', VCODEC, '-b:v', br, *vtag, '-pix_fmt', 'yuv420p', out], stdin=subprocess.PIPE)
cur = -1; buf = None
for i in range(n):
    while cur < mp[i]:
        buf = dec.stdout.read(fs); cur += 1
    enc.stdin.write(buf)
enc.stdin.close(); enc.wait(); dec.stdout.close(); dec.wait(); print('wrote', out)
