"""Assemble talking clips into MASTER.mp4 + EDIT_KIT.

Usage: assemble_ugc.py <project-dir> <key1> <key2> ... [--speed 1.0] [--no-grade] [--pad 0.15]
- Uses the highest version of each key in TAKES/ (key.mp4, key_v2.mp4, ...).
- Trims each clip to its speech span from <clip>_qc.json (+pad), so there is no dead air between lines.
- Normalizes to 1080x1920, 30 fps, 48 kHz; optional light iPhone grade + grain; loudnorm I=-14:TP=-1.5.
- Sync-safe joins (2026-11-12): each EDIT_KIT piece is a whole number of frames with PCM sound cut to exactly that
  length (.mkv); AAC is encoded once on MASTER.mp4. Check any master with `tools/av_check.py --check MASTER.mp4`.
"""
import json, re, subprocess, sys, pathlib

GRADE = ("unsharp=5:5:0.5:5:5:0.0,eq=contrast=0.95:saturation=1.02,"
         "colortemperature=temperature=6800:mix=0.12,noise=c0s=5:c0f=t+u")


def latest(takes, key):
    cands = [p for p in takes.glob(f"{key}*.mp4") if re.fullmatch(rf"{re.escape(key)}(_v\d+)?", p.stem)]
    ver = lambda p: int(p.stem.rsplit("_v", 1)[1]) if re.search(r"_v\d+$", p.stem) else 1
    return max(cands, key=ver) if cands else None


def run(cmd):
    subprocess.run(cmd, check=True)


def main():
    a = sys.argv[1:]
    def opt(name, default, cast=float):
        if name in a:
            i = a.index(name); v = cast(a[i + 1]); del a[i:i + 2]; return v
        return default
    speed = opt("--speed", 1.0); pad = opt("--pad", 0.15)
    grade = "--no-grade" not in a
    a = [x for x in a if x != "--no-grade"]
    proj = pathlib.Path(a[0]).resolve(); keys = a[1:]
    takes, kit = proj / "TAKES", proj / "EDIT_KIT"
    kit.mkdir(exist_ok=True)
    parts, order, report = [], [], []
    for n, key in enumerate(keys, 1):
        clip = latest(takes, key)
        if not clip:
            sys.exit(f"missing clip for {key}")
        qcf = clip.with_name(clip.stem + "_qc.json")
        qc = json.loads(qcf.read_text()) if qcf.exists() else {}
        dur = qc.get("duration_s") or float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)], capture_output=True, text=True).stdout)
        start = max(0.0, (qc.get("speech_start_s") or 0) - pad)
        end = min(dur, (qc.get("speech_end_s") or dur) + pad + 0.25)
        # 2026-11-12 sync fix (from the agentchad drama-engine assembler): every piece is cut to a whole number of
        # frames and its sound is padded/trimmed to exactly that length, kept as PCM (no per-piece AAC), and AAC is
        # encoded once on the master. Per-piece AAC + concat copy drifted ~10-30 ms per join (+52 ms on 4 clips).
        nfr = max(1, round((end - start) / speed * 30)); seg = nfr / 30
        vf = f"scale=1080:1920:flags=lanczos,setsar=1,fps=30" + (f",{GRADE}" if grade else "") + (f",setpts=PTS/{speed}" if speed != 1 else "")
        vf += f",tpad=stop_mode=clone:stop_duration=1,trim=end_frame={nfr},setpts=PTS-STARTPTS"
        af = "aresample=48000" + (f",atempo={speed}" if speed != 1 else "") + f",apad,atrim=end_sample={round(seg * 48000)},asetpts=PTS-STARTPTS"
        out = kit / f"{n:02d}_{key}.mkv"
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(clip), "-vf", vf, "-af", af,
             "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(out)])
        parts.append(out); order.append(f"{n:02d}_{key}.mkv  <- {clip.name}  [{start:.2f}-{end:.2f}s]")
        report.append({"key": key, "source": clip.name, "trim": [round(start, 2), round(end, 2)], "word_match": qc.get("word_match"), "differences": qc.get("differences")})
    lst = kit / "concat.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    raw = kit / "_concat.mkv"
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(raw)])
    master = proj / "MASTER.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(master)])
    raw.unlink(); lst.unlink()
    (kit / "ORDER.txt").write_text("\n".join(order) + "\n")
    (proj / "QC_REPORT.txt").write_text(json.dumps(report, indent=2))
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(master)], capture_output=True, text=True).stdout.strip()
    print(f"MASTER {master} {float(d):.2f}s"); print("\n".join(order))


if __name__ == "__main__":
    main()
