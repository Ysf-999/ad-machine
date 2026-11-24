"""Voice onsets from the audio itself (PCM energy), for caption timing.
onset_after(db, win, t_from, t_to): inside [t_from, t_to] find the LAST quiet run (>= 60 ms under -36 dBFS) and return the
first speech-level frame (>= 30 ms over -27 dBFS) after it, or None when there is no quiet run (words run together)."""
import subprocess, numpy as np

def load(path, sr=16000):
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ar", str(sr), "-ac", "1", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(pcm, dtype=np.float32), sr

def rms_track(x, sr, win=0.01):
    n = int(sr * win); m = len(x) // n
    r = np.sqrt((x[:m * n].reshape(m, n) ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(r), win

def onset_after(db, win, t_from, t_to, speech=-27.0, quiet=-36.0, quiet_frames=6):
    i0, i1 = max(0, int(t_from / win)), min(len(db) - 3, int(t_to / win) + 1)
    if i1 <= i0: return None
    seg = db[i0:i1]; q = seg < quiet
    last_run_end = None; run = 0
    for i, v in enumerate(q):
        run = run + 1 if v else 0
        if run >= quiet_frames: last_run_end = i
    if last_run_end is None: return None
    for i in range(last_run_end + 1, len(seg)):
        if seg[i] > speech and db[i0 + i:i0 + i + 3].mean() > speech:
            return round((i0 + i) * win, 3)
    return None


def levels(db):
    """Relative thresholds for this file: speech = 70th percentile of active frames - 14 dB, quiet = speech - 10 dB."""
    act = db[db > -60]
    sp = float(np.percentile(act, 70)) - 14 if len(act) else -27.0
    return sp, sp - 10


def phrase_onset(db, win, t_guess, sp, qt, before=0.25, after=0.8, min_quiet=0.06):
    """Onset of a phrase that follows a pause: inside [t_guess-before, t_guess+after] take the FIRST quiet run
    (>= min_quiet) and return the first speech frame after it. None when there is no pause (keep the estimate)."""
    i0, i1 = max(0, int((t_guess - before) / win)), min(len(db) - 3, int((t_guess + after) / win))
    # the FIRST qualifying pause in the window (not the longest): a short word right after a pause ("a", "I") is
    # followed by its own gap, and the longest gap would skip past it
    best, run, start = None, 0, None
    for i in range(i0, i1 + 1):
        if i < i1 and db[i] < qt:
            if run == 0: start = i
            run += 1
        else:
            if run * win >= min_quiet:
                best = (start, run); break
            run = 0
    if best is None: return None
    for i in range(best[0] + best[1], i1 + 3):
        if i + 3 <= len(db) and db[i] > sp and db[i:i + 3].mean() > sp:
            return round(i * win, 3)
    return None


def refine_starts(words, db, win, sp, qt):
    """Shared by realign_vo and caption_sync_check so both use the SAME physics. words = list of [start, end, text]
    (text keeps punctuation); starts are modified in place.
    1. Phrase starts (after . , ! ? …) snap to the voice onset after the first pause near the estimate, but only if
       that onset falls between the neighbouring words (a run-on phrase's first gap can be a later pause).
    2. No spoken word contains >= 120 ms of silence: if a word's span does (Whisper handing it the pause before it),
       the word starts where the voice comes back after that silence."""
    for i, w in enumerate(words):
        if i == 0 or words[i - 1][2][-1:] in ".,!?…":
            o = phrase_onset(db, win, w[0], sp, qt)
            nxt = words[i + 1][0] if i + 1 < len(words) else None
            prv = words[i - 1][1] if i else None
            if o is not None and (nxt is None or o < nxt) and (prv is None or o >= prv - 0.05):
                w[0] = o
        j0, j1 = int(w[0] / win), int((w[1] - 0.05) / win); run = 0; last = None
        for j in range(j0, min(j1, len(db))):
            run = run + 1 if db[j] < qt else 0
            if run * win >= 0.12: last = j
        if last is not None:
            for j in range(last + 1, min(j1 + 3, len(db) - 3)):
                if db[j] > sp and db[j:j + 3].mean() > sp:
                    w[0] = round(j * win, 3); break
    return words
