"""Audio levels check for a finished master — the ear the frame checkers don't have.

Usage: audio_check.py <master.mp4> [--voice <voice-only file>] [--json]
Reports integrated loudness (LUFS), loudness range, true peak, and — when a voice-only reference on the same timeline
is given — how far the music bed sits under the voice: RMS of the master inside the voice's silences (= music alone)
against RMS inside speech (= voice + music). Targets: master -14 LUFS ±1, TP <= -1.5 dBTP, music 6-12 dB under voice.
Used by rawedit.py verify and master_qc.py.
"""
import json, re, subprocess, sys


def sh(*c):
    return subprocess.run([str(x) for x in c], capture_output=True, text=True, errors="replace")


def loud(f):
    r = sh("ffmpeg", "-hide_banner", "-nostats", "-i", f, "-af", "loudnorm=I=-14:TP=-1.5:print_format=json", "-f", "null", "-")
    m = re.search(r"\{.*\}", r.stderr, re.S)
    j = json.loads(m.group(0)) if m else {}
    return {k: float(j[k]) for k in ("input_i", "input_tp", "input_lra") if k in j}


def silences(f, noise="-35dB", mind=0.4):
    r = sh("ffmpeg", "-hide_banner", "-nostats", "-i", f, "-af", f"silencedetect=noise={noise}:d={mind}", "-f", "null", "-")
    st = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", r.stderr)]
    en = [float(x) for x in re.findall(r"silence_end:\s*(-?[\d.]+)", r.stderr)]
    return [(s, en[i]) for i, s in enumerate(st) if i < len(en) and en[i] > s]


def rms(f, t0, d):
    r = sh("ffmpeg", "-v", "info", "-ss", f"{t0:.3f}", "-t", f"{d:.3f}", "-i", f, "-af", "astats=measure_overall=RMS_level:measure_perchannel=0", "-f", "null", "-")
    m = re.search(r"RMS level dB:\s*(-?[\d.]+|-inf)", r.stderr)
    return float(m.group(1)) if m and m.group(1) != "-inf" else -90.0


def dur(f):
    return float(sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f).stdout.strip() or 0)


def main():
    a = sys.argv[1:]
    master = a[0]; voice = a[a.index("--voice") + 1] if "--voice" in a else None
    out = {"master": loud(master)}
    L = [f"master: {out['master'].get('input_i', float('nan')):.1f} LUFS, LRA {out['master'].get('input_lra', 0):.1f}, true peak {out['master'].get('input_tp', 0):.1f} dBTP"]
    i, tp = out["master"].get("input_i", -14), out["master"].get("input_tp", -1.5)
    flags = []
    if abs(i + 14) > 1.0: flags.append(f"loudness off target (-14): {i:.1f}")
    if tp > -1.0: flags.append(f"true peak too hot: {tp:.1f}")
    if voice:
        D = dur(master); gaps = [(s, e) for s, e in silences(voice, mind=0.3) if e - s >= 0.3 and s > 0.3 and e < D - 0.3]
        gaps = [(s + 0.06, min(e - s - 0.12, 2.0)) for s, e in gaps]
        if gaps:
            bed = sorted(rms(master, s, d) for s, d in gaps)
            bed_db = bed[len(bed) // 2]
            # speech windows: 1 s slices not overlapping gaps
            sp = []
            t = 0.5
            while t < D - 1.5 and len(sp) < 12:
                if not any(s - 0.2 <= t <= s + d + 0.2 for s, d in gaps): sp.append(rms(master, t, 1.0))
                t += max((D - 2) / 12, 1.0)
            sp_db = sorted(sp)[len(sp) // 2] if sp else -90
            under = sp_db - bed_db
            out["music_bed_db"], out["speech_db"], out["music_under_voice_db"], out["gaps_measured"] = bed_db, sp_db, under, len(gaps)
            L.append(f"music bed (inside {len(gaps)} voice pauses): {bed_db:.1f} dB RMS; speech: {sp_db:.1f} dB RMS; music sits {under:.1f} dB under the voice")
            if under > 20: L.append("no music bed detected (pauses hold only room noise)")
            elif under < 6: flags.append(f"music only {under:.1f} dB under the voice (want 6-12)")
            elif under > 14: flags.append(f"music {under:.1f} dB under the voice — close to inaudible")
        else:
            L.append("voice has no pauses >= 0.5 s, music-under-voice not measured")
        out["voice"] = loud(voice)
    out["flags"] = flags
    L.append("FLAGS: " + ("; ".join(flags) if flags else "none"))
    print(json.dumps(out) if "--json" in a else "\n".join(L))


if __name__ == "__main__":
    main()
