# Library v2, 2026-11-10 (agentchad.io). Free and local. Never plays audio.
# 2026-11-10: writes <out_dir>/stems.json ({"method": "demucs" | "side"}) so songcheck.py knows when its number is a hint only.
"""stems.py <video or audio> <out_dir> [--seconds N] [--side] [--fine]
Splits the original audio into the old voice and the music bed:
  <out_dir>/vocals.wav      the old voice (level reference for mixbed.py, input for songcheck.py)
  <out_dir>/no_vocals.wav   the music and room sound without the old voice (the bed you keep)
  <out_dir>/v16.wav         the voice as 16 kHz mono, ready for songcheck.py
  <out_dir>/stems.json      how the split was made (demucs or side); songcheck.py reads it

With demucs (best): runs DEMUCS_PYTHON (env -> ~/.agentchad/settings.env -> ~/.venvs/demucs/bin/python3).
  --fine     the slower, cleaner model (htdemucs_ft, 2 shifts): use it when the bed has hiss or "s" sounds where the
             old voice was. --seconds N splits only the first N seconds (50 is enough for the sung-or-spoken check).
Without demucs it stops and says so (exit code 3), unless you pass --side:
  --side     free rough split for STEREO audio with the voice in the middle (most voiceover ads): the bed is the
             left-minus-right side signal (same on both channels, so phone speakers do not cancel it), the voice is the middle. The bed sounds thinner (bass and anything in the
             middle are gone) and some voice can stay in it. Mono audio has no side signal: the script says so.
Exit codes: 0 OK, 1 bad input or ffmpeg error, 3 demucs is not installed (the message gives the install line and
the free choices)."""
import json
import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py import DEMUCS_INSTALL, MISSING, demucs_python  # noqa: E402


def run(cmd, what='ffmpeg'):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f'{what} failed:\n' + r.stderr[-800:])
    return r


def mean_db(path):
    e = run(['ffmpeg', '-hide_banner', '-nostats', '-i', path, '-af', 'volumedetect', '-f', 'null', '-']).stderr
    for line in e.splitlines():
        if 'mean_volume' in line:
            return float(line.split(':')[1].split()[0])
    return -99.0


a = sys.argv[1:]
if len(a) < 2 or a[0] in ('-h', '--help'):
    sys.exit(__doc__)
src, out = os.path.expanduser(a[0]), os.path.expanduser(a[1])
secs = a[a.index('--seconds') + 1] if '--seconds' in a else None
if not os.path.exists(src):
    sys.exit(f'not found: {src}')
os.makedirs(out, exist_ok=True)
lim = ['-t', secs] if secs else []
wav = os.path.join(out, f'_orig_{os.getpid()}.wav')
run(['ffmpeg', '-v', 'error', '-y', '-i', src, *lim, '-vn', '-ar', '44100', '-ac', '2', wav])
DP = demucs_python()
has_demucs = os.path.exists(DP) and subprocess.run([DP, '-I', '-B', '-c', 'import demucs'], capture_output=True).returncode == 0

if has_demucs:
    model = ['-n', 'htdemucs_ft', '--shifts', '2', '--overlap', '0.5'] if '--fine' in a else ['-n', 'htdemucs']
    print('demucs:', ' '.join(model), '(the first use downloads the model once, about 80 MB per model; a 30 s ad takes '
          'about 1 minute on a laptop)', flush=True)
    work = os.path.join(out, f'_demucs_{os.getpid()}')
    run([DP, '-I', '-B', '-m', 'demucs', '--two-stems=vocals', *model, '-o', work, wav], 'demucs')
    name = os.path.splitext(os.path.basename(wav))[0]
    folder = os.path.join(work, model[1], name)
    for s in ('vocals.wav', 'no_vocals.wav'):
        shutil.move(os.path.join(folder, s), os.path.join(out, s))
    shutil.rmtree(work, ignore_errors=True)
    how = 'demucs'
    method = 'demucs'
elif '--side' in a:
    ch = run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=channels', '-of', 'csv=p=0', src]).stdout.strip()
    run(['ffmpeg', '-v', 'error', '-y', '-i', wav, '-af', 'pan=stereo|c0=0.5*c0-0.5*c1|c1=0.5*c0-0.5*c1', os.path.join(out, 'no_vocals.wav')])
    run(['ffmpeg', '-v', 'error', '-y', '-i', wav, '-af', 'pan=mono|c0=0.5*c0+0.5*c1', os.path.join(out, 'vocals.wav')])
    side, mid = mean_db(os.path.join(out, 'no_vocals.wav')), mean_db(os.path.join(out, 'vocals.wav'))
    if ch == '1' or side < mid - 30:
        os.remove(wav)
        sys.exit('The original audio is mono (or nearly), so there is no side signal to keep as a bed. Choices: the '
                 "editor's music file, voice only (mixbed.py ... none ...), or install demucs:\n  " + DEMUCS_INSTALL)
    how = f'side signal (free rough split; bed {side - mid:+.0f} dB against the middle)'
    method = 'side'
    print('note: the "vocals" file is the middle of the mix (voice plus anything centred), so use mixbed.py with '
          '--duck, not --ref-vocals, and treat songcheck as a hint only.')
else:
    os.remove(wav)
    sys.stderr.write(
        'demucs is not installed (it splits the old voice from the music). Install it once (about 1 GB with PyTorch, '
        '5-15 minutes):\n  ' + DEMUCS_INSTALL + '\nFree choices without it:\n'
        "  1. the editor's music file or an export without the voice (best, ask for it)\n"
        '  2. stems.py <video> <dir> --side   (rough bed from a stereo mix, thinner sound)\n'
        '  3. no bed: mixbed.py <voice.wav> none <out.wav>  (voice only)\n')
    sys.exit(MISSING)
run(['ffmpeg', '-v', 'error', '-y', '-i', os.path.join(out, 'vocals.wav'), '-ac', '1', '-ar', '16000', os.path.join(out, 'v16.wav')])
json.dump({'method': method, 'source': os.path.abspath(src)}, open(os.path.join(out, 'stems.json'), 'w'))
if os.path.exists(wav):
    os.remove(wav)
print(f'stems ({how}): {out}/vocals.wav, {out}/no_vocals.wav, {out}/v16.wav')
