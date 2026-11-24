# Library v2, 2026-11-10 (agentchad.io). Free and local: ffmpeg only, any Python 3. Never plays audio.
# 2026-11-10: the result is measured with ffmpeg's ebur128 (the same meter qa-sniper and the platforms use) and the
#             gain is set from that reading; loudnorm's measuring pass read short clips about 1.3 LU low (false exit 4).
"""mixbed.py <voice.wav> <bed.wav | none> <out.wav> [--ref-vocals <old vocals.wav>] [--duck] [--lufs -14] [--tp -1.5]
Mixes the new voice track (from mixvo.py) with the music bed and sets the final loudness for social video.

  voice.wav      the new voice, every line at its place (mixvo.py output)
  bed.wav        the original music and room sound without the old voice (stems.py writes no_vocals.wav),
                 or the editor's music file, or "none" (voice only)
  --ref-vocals   the OLD voice stem (stems.py writes vocals.wav). The new voice is set to the same loudness the old
                 voice had, so voice and music sit together exactly like in the original mix. Best result.
  --duck         without --ref-vocals: the bed is set to a fixed level under the voice (default 12 dB under,
                 change with --bed-db -10), like a normal edit. Use it for an editor's music file or the free
                 side-channel bed. Fixed on purpose: a bed that pumps back up in every pause sounds like a riser.
  --lufs / --tp  final integrated loudness (default -14 LUFS) and the true-peak ceiling (default -1.5 dBTP).

Loudness: the mix is measured with ebur128 (EBU R128 / BS.1770, the meter qa-sniper uses), a linear gain sets it to
the target, an oversampled limiter keeps the true peak under the ceiling, and the result is measured again (up to
three rounds). It prints the measured LUFS and true peak of the result.
Exit codes: 0 OK, 1 bad input or ffmpeg error, 4 the result missed the target by more than 1 LU or the peak ceiling."""
import os
import re
import subprocess
import sys


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit('ffmpeg failed:\n' + r.stderr[-800:])
    return r.stderr


def loud(path):
    """Integrated loudness (LUFS) and true peak (dBTP) of a file, measured with ebur128 like qa-sniper."""
    err = run(['ffmpeg', '-hide_banner', '-nostats', '-i', path, '-vn', '-af', 'ebur128=peak=true', '-f', 'null', '-'])
    tail = err[err.rfind('Summary:'):] if 'Summary:' in err else ''
    mi = re.search(r'I:\s+(-?[\d.]+|-inf) LUFS', tail)
    mt = re.search(r'Peak:\s+(-?[\d.]+|-inf) dBFS', tail)
    if not mi or mi.group(1) == '-inf':
        sys.exit(f'could not measure the loudness of {path} (silent or no audio)')
    return {'input_i': float(mi.group(1)), 'input_tp': float(mt.group(1)) if mt and mt.group(1) != '-inf' else -99.0}


def dur(path):
    return float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                                capture_output=True, text=True).stdout)


a = sys.argv[1:]
if len(a) < 3 or a[0] in ('-h', '--help'):
    sys.exit(__doc__)
voice, bed, out = (os.path.expanduser(x) for x in a[:3])
opt = lambda k, d=None: a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else d
ref = opt('--ref-vocals'); ref = os.path.expanduser(ref) if ref else None
DUCK = '--duck' in a
BED_DB = float(opt('--bed-db', -12))
LUFS = float(opt('--lufs', -14)); TP = float(opt('--tp', -1.5))
no_bed = bed.lower() == 'none'
for p in [voice] + ([] if no_bed else [bed]) + ([ref] if ref else []):
    if not os.path.exists(p):
        sys.exit(f'not found: {p}')
D = dur(voice)

# 1. voice gain: match the old voice (best), else leave it and let the final pass set the level
vgain = 0.0
if ref and not no_bed:
    lv, lr = float(loud(voice)['input_i']), float(loud(ref)['input_i'])
    vgain = lr - lv
    print(f'old voice {lr:.1f} LUFS, new voice {lv:.1f} LUFS -> new voice {vgain:+.1f} dB')

# 2. mix
if no_bed:
    fl = f'[0:a]aresample=48000,pan=stereo|c0=c0|c1=c0,volume={vgain}dB[mix]'
    ins = ['-i', voice]
    print('no bed: voice only. The ad will sound emptier than the original; add a music track you have the rights to if you can.')
else:
    ins = ['-i', voice, '-i', bed]
    v = f'[0:a]aresample=48000,pan=stereo|c0=c0|c1=c0,volume={vgain}dB'
    b = f'[1:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=0:{D:.3f}'
    if DUCK and not ref:
        lv, lb = float(loud(voice)['input_i']), float(loud(bed)['input_i'])
        bgain = (lv + BED_DB) - lb   # a fixed bed level under the voice
        print(f'bed {lb:.1f} LUFS -> {bgain:+.1f} dB ({-BED_DB:.0f} dB under the voice)')
        fl = f'{v}[v];{b},volume={bgain:.2f}dB[bd];[v][bd]amix=inputs=2:normalize=0[mix]'
    else:
        fl = f'{v}[v];{b}[bd];[v][bd]amix=inputs=2:normalize=0[mix]'
tmp = out + f'.premix.{os.getpid()}.wav'
run(['ffmpeg', '-v', 'error', '-y', *ins, '-filter_complex', fl, '-map', '[mix]', '-t', f'{D:.3f}', '-ar', '48000', '-c:a', 'pcm_s24le', tmp])

# 3. loudness to the target, measured with ebur128; true peak under the ceiling (oversampled limiter)
src = tmp
LIM = (f"aresample=192000,alimiter=limit={10 ** ((TP - 0.5) / 20):.4f}:attack=1:release=50:level=disabled,"
       "aresample=48000")
for rnd in range(3):
    m = loud(src)
    gain = LUFS - m['input_i']
    af = f"volume={gain:.2f}dB" + ("," + LIM if m['input_tp'] + gain > TP - 0.3 else "")
    nxt = out + f'.round{rnd}.{os.getpid()}.wav'
    run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-af', af, '-ar', '48000', '-c:a', 'pcm_s24le', nxt])
    os.remove(src)
    src = nxt
    r = loud(src)
    if abs(r['input_i'] - LUFS) <= 0.3 and r['input_tp'] <= TP + 0.05:
        break
os.replace(src, out)
I, T = float(r['input_i']), float(r['input_tp'])
ok = abs(I - LUFS) <= 1.0 and T <= TP + 0.05
print(f'wrote {out}: {I:.1f} LUFS, true peak {T:.1f} dBTP (target {LUFS} LUFS, peak <= {TP}) ' + ('OK' if ok else 'CHECK'))
sys.exit(0 if ok else 4)
