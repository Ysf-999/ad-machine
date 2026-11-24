# Library v2, 2026-11-10 (agentchad.io). Keys only from your own environment; nothing here is account-specific.
# 2026-11-10: the first line always starts at 0.0 s (no dead air); line files may be .mp3, .wav, .aiff or .m4a.
"""PROJ=<dir> END=<video_seconds minus 0.15> [GAP=0.10 EARLY=0.35 TEMPO_OVERRIDE='23:1.2,24:1.25' KEEP_LEAD=0] fit.py <tempo> <prefix>
Fits the new voice lines into the original timing: trims silence from each line, speeds it up with atempo (<tempo>, e.g. 1.08),
and places each line at max(original_start - EARLY, previous_end + GAP). The FIRST line always starts at 0.0 s, so the ad
opens on the first word (set KEEP_LEAD=1 only if the original really opens on a silent shot on purpose).
TEMPO_OVERRIDE gives single lines their own tempo (line number:tempo).
Line files: <PROJ>/vo/<prefix>00.mp3 (or .wav/.aiff/.m4a), <prefix>01..., one per line of <PROJ>/lines.json.
Writes <PROJ>/vo/fitNN.wav and <PROJ>/schedule.json. Only ffmpeg is needed (any Python 3).
Exit codes: 0 OK, 1 a file is missing, 2 the last line ends after END (shorten lines or raise the tempo)."""
import os, json, subprocess, sys
if len(sys.argv) < 3 or 'PROJ' not in os.environ or 'END' not in os.environ:
    sys.exit(__doc__)
P = os.path.expanduser(os.environ['PROJ']); X = float(sys.argv[1]); prefix = sys.argv[2]
END = float(os.environ['END']); GAP = float(os.environ.get('GAP', '0.10')); EARLY = float(os.environ.get('EARLY', '0.35'))
KEEP_LEAD = os.environ.get('KEEP_LEAD', '0') == '1'
OV = {int(k): float(v) for k, v in (x.split(':') for x in os.environ.get('TEMPO_OVERRIDE', '').split(',') if x)}
lines = json.load(open(f'{P}/lines.json'))
dur = lambda f: float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f], capture_output=True, text=True).stdout)


def line_file(i):
    for ext in ('mp3', 'wav', 'aiff', 'm4a'):
        p = f'{P}/vo/{prefix}{i:02d}.{ext}'
        if os.path.exists(p):
            return p
    sys.exit(f'Missing voice file for line {i}: {P}/vo/{prefix}{i:02d}.mp3 (or .wav/.aiff/.m4a). '
             'Make the voice first (tts.py), or for a free test any local text-to-speech file.')


sched = []; prev = 0.0
for i, l in enumerate(lines):
    src = line_file(i); out = f'{P}/vo/fit{i:02d}.wav'; t = OV.get(i, X)
    af = 'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse' + (f',atempo={t}' if abs(t - 1) > 1e-3 else '')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-af', af, '-ar', '48000', '-ac', '1', out], check=True)
    d = dur(out)
    if i == 0:
        st = max(l['s'] - EARLY, 0.0) if KEEP_LEAD else 0.0
    else:
        st = max(l['s'] - EARLY, prev + GAP, 0.0)
    en = st + d
    sched.append({'i': i, 'file': out, 'start': round(st, 3), 'end': round(en, 3), 'drift': round(st - l['s'], 2), 'cap': l['cap']}); prev = en
for s in sched:
    print(f"{s['i']:02d} start {s['start']:7.2f} end {s['end']:7.2f} drift {s['drift']:+.2f}  {s['cap'][:45]}")
json.dump(sched, open(f'{P}/schedule.json', 'w'), ensure_ascii=False, indent=1)
ok = prev <= END
if lines and lines[0]['s'] > 0.5 and not KEEP_LEAD:
    print(f"note: the original speaks first at {lines[0]['s']:.2f} s; line 00 now starts at 0.00. If the opening seconds are a "
          "deliberate silent shot (a product reveal), run again with KEEP_LEAD=1 so the voice does not land early.")
far = [s['i'] for s in sched[1:] if abs(s['drift']) > 0.6]
if far:
    print('lines more than 0.6 s off the original start:', far, '(shorten them or give them their own tempo)')
print('LAST END', round(prev, 2), 'limit', END, 'OK' if ok else 'TOO LONG')
sys.exit(0 if ok else 2)
