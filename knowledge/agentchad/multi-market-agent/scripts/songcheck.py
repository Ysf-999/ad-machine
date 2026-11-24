# Library v2, 2026-11-09 (agentchad.io). Keys only from your own environment; nothing here is account-specific.
# 2026-11-10: hint only (no verdict) when the input is not a clean voice: a stems.py --side "voice" (the middle of the
#             mix, music included) or any file while demucs is not installed. A spoken clip scored 0.70 that way.
"""songcheck.py <vocals.wav> [--side | --clean]
Is the ad sung or spoken? Decide from the audio itself, never from the brief. Give it the separated vocals stem
(stems.py writes it as v16.wav: 16 kHz mono).
It measures the share of voiced frames that hold one pitch for 0.2 s or more.
Sung is usually >= 0.40, spoken <= 0.15; in between, listen. Needs numpy.

The number only means something on a CLEAN voice (demucs stems, or the editor's voice-only file). Music held under
the voice (a chord, a pad, a sine bed) counts as "held notes" too. So it prints "hint only, cannot decide" when:
  - stems.json next to the file says the split was the free --side one, or you pass --side, or
  - there is no stems.json and demucs is not installed (the file is then most likely a mix).
Then decide from the transcript instead: sung lyrics have short lines of similar length, rhymes at the line ends and
a repeated chorus; speech has long sentences, no rhyme scheme and no repeats.
--clean  the file is a clean voice-only track (for example the editor's voice export): decide from the number."""
import json, os, sys, wave
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py import demucs_python, need  # noqa: E402
args = [x for x in sys.argv[1:] if not x.startswith('--')]
if not args:
    sys.exit(__doc__)
need(['numpy'])
import numpy as np  # noqa: E402
path = os.path.expanduser(args[0])


def hint_reason():
    """Why the number cannot decide on its own, or '' when the input is a clean voice."""
    if '--clean' in sys.argv:
        return ''
    if '--side' in sys.argv:
        return 'the input is a --side split (the middle of the mix: voice plus anything centred, music included)'
    meta = os.path.join(os.path.dirname(os.path.abspath(path)), 'stems.json')
    if os.path.exists(meta):
        try:
            method = json.load(open(meta)).get('method', '')
        except (OSError, ValueError):
            method = ''
        if method == 'side':
            return 'stems.json says this is the free --side split (the middle of the mix, music included)'
        if method == 'demucs':
            return ''
    if not os.path.exists(demucs_python()):
        return 'demucs is not installed, so this file is most likely the mix, not a clean voice'
    return ''


r = wave.open(path); sr = r.getframerate()
if r.getnchannels() != 1 or r.getsampwidth() != 2:
    sys.exit('Give a 16-bit mono WAV (ffmpeg -i in.wav -ac 1 -ar 16000 out.wav).')
x = np.frombuffer(r.readframes(r.getnframes()), np.int16).astype(np.float32) / 32768
hop, win = 320, 1024; fr = []; rms = []
for i in range(0, len(x) - win, hop):
    s = x[i:i + win] - x[i:i + win].mean(); rms.append(np.sqrt((s ** 2).mean()))
    ac = np.correlate(s, s, 'full')[win - 1:]; lo, hi = sr // 900, sr // 80
    k = lo + np.argmax(ac[lo:hi]); fr.append(sr / k if ac[0] > 0 and ac[k] / ac[0] > 0.5 else 0)
f = np.array(fr); rms = np.array(rms); voiced = (rms > rms.max() * 0.06) & (f > 0)
c = 1200 * np.log2(np.maximum(f, 1) / 440); n = len(f); held = 0; i = 0
while i < n:
    if voiced[i]:
        j = i
        while j + 1 < n and voiced[j + 1] and abs(c[j + 1] - c[i]) < 70:
            j += 1
        if j - i + 1 >= 10:
            held += j - i + 1
        i = j + 1
    else:
        i += 1
share = held / max(voiced.sum(), 1)
why = hint_reason()
if why:
    print(f"sustained-note share {share:.2f}  (voiced frames {voiced.sum()})  -> hint only, cannot decide: {why}.\n"
          "Decide from the transcript instead: sung = short lines of similar length, rhymes at the line ends, a repeated "
          "chorus; spoken = long sentences, no rhyme scheme, no repeats. Unsure: ask the user, or install demucs and "
          "run stems.py again for a real measurement.")
    sys.exit(0)
verdict = 'SUNG (Suno cover route)' if share >= 0.4 else 'SPOKEN (voice route)' if share <= 0.15 else 'UNCLEAR: listen to it'
print(f"sustained-note share {share:.2f}  (voiced frames {voiced.sum()})  -> {verdict}")
