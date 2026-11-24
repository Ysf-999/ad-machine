# Library v2, 2026-11-09 (agentchad.io). Keys only from your own environment; nothing here is account-specific.
"""envmatch.py <tts.wav> <reference_vocals.wav> <out.wav> [wet=0.18] [rt60=0.13] [clamp_db=8] [octaves=1.0]
Makes a clean studio TTS voice sound like the original recording (a phone in a room or a car): matches the long-term
tone of the reference vocals (smoothed over <octaves>, limited to +-<clamp_db> dB so it copies the room, not the person),
then adds a short cabin-style reflection pattern mixed in at <wet> (0 = no echo, for outdoor speakers).
Needs numpy and soundfile. Level-match the result to the original vocals afterwards."""
import os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py import need  # noqa: E402
if len(sys.argv) < 4:
    sys.exit(__doc__)
need(['numpy', 'soundfile'])
import numpy as np, soundfile as sf  # noqa: E402,E401
tts_p, ref_p, out_p = sys.argv[1:4]; WET = float(sys.argv[4]) if len(sys.argv) > 4 else 0.18; RT60 = float(sys.argv[5]) if len(sys.argv) > 5 else 0.13
CLAMP = float(sys.argv[6]) if len(sys.argv) > 6 else 8.0; OCT = float(sys.argv[7]) if len(sys.argv) > 7 else 1.0
def load(p):
    x, sr = sf.read(p, always_2d=True); return x.mean(axis=1), sr
x, sr = load(tts_p); r, sr2 = load(ref_p)
if sr2 != sr:  # crude resample of the reference to the voice's sample rate
    t = np.arange(0, len(r) / sr2, 1 / sr); r = np.interp(t, np.arange(len(r)) / sr2, r)
N = 4096; H = 1024; win = np.hanning(N)
def ltas(s):
    fr = [s[i:i + N] * win for i in range(0, len(s) - N, H)]; F = np.abs(np.fft.rfft(np.array(fr), axis=1)) ** 2
    e = F.sum(axis=1); keep = e > np.percentile(e, 40)  # speech frames only
    return F[keep].mean(axis=0)
A = ltas(r); B = ltas(x); f = np.fft.rfftfreq(N, 1 / sr)
EPS = 1 / 10 ** 12; TINY = 1 / 10 ** 9
ratio = np.sqrt((A + EPS) / (B + EPS))
sm = np.empty_like(ratio)
for i, fi in enumerate(f):
    lo, hi = fi / 2 ** (OCT / 2), fi * 2 ** (OCT / 2); m = (f >= lo) & (f <= hi); sm[i] = np.exp(np.mean(np.log(ratio[m]))) if m.any() else ratio[i]
ref_bin = np.argmin(np.abs(f - 1000)); sm = sm / sm[ref_bin]
db = 20 * np.log10(sm); db = np.clip(db, -CLAMP, CLAMP); sm = 10 ** (db / 20)
h = np.fft.irfft(sm, n=N); h = np.roll(h, N // 2) * np.hanning(N)
def fftconv(a, b):
    n = len(a) + len(b) - 1; L = 1 << (n - 1).bit_length(); return np.fft.irfft(np.fft.rfft(a, L) * np.fft.rfft(b, L), L)[:n]
y = fftconv(x, h)[N // 2:N // 2 + len(x)]
rng = np.random.default_rng(7); L = int(sr * 0.3); t = np.arange(L) / sr
tail = rng.standard_normal(L) * np.exp(-6.91 * t / RT60)
a = np.exp(-2 * np.pi * 3500 / sr); lp = np.zeros(L); acc = 0.0
for i in range(L):
    acc = (1 - a) * tail[i] + a * acc; lp[i] = acc   # a cabin absorbs the highs
ir = lp / np.sqrt((lp ** 2).sum()) * 0.6
for ms, g in [(2.7, 0.35), (4.1, 0.28), (6.3, 0.22), (8.8, 0.15), (12.5, 0.1)]:
    ir[int(sr * ms / 1000)] += g
ir[0] = 0
wet = fftconv(y, ir)[:len(y)]
z = (1 - WET) * y + WET * wet / (np.abs(wet).max() / max(np.abs(y).max(), TINY) + TINY)
z = z / np.abs(z).max() * 0.9
sf.write(out_p, z, sr)
print('EQ dB at 100/300/1k/3k/6k/10k/14k Hz:', [round(float(db[np.argmin(np.abs(f - q))]), 1) for q in (100, 300, 1000, 3000, 6000, 10000, 14000)])
