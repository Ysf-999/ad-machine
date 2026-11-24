"""QC one generated clip: transcript vs expected words, speech rate, and a frame strip.

Usage: qc.py <clip.mp4> "<expected words>" [frames=5]
Writes <clip>_qc.json and <clip>_strip.jpg next to the clip and prints a short report.
"""
import difflib, json, re, subprocess, sys, pathlib
import mlx_whisper
from PIL import Image


def norm(t):
    return re.sub(r"[^a-z0-9' ]+", " ", t.lower().replace("’", "'")).split()


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def strip(path, dur, n, dest):
    frames = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        f = dest.with_name(f"{dest.stem}_{i}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=360:-2", str(f)], check=True)
        frames.append(Image.open(f))
    w, h = frames[0].size
    sheet = Image.new("RGB", (w * n, h), "white")
    for i, fr in enumerate(frames):
        sheet.paste(fr, (i * w, 0))
    sheet.save(dest, quality=88)
    for i in range(n):
        dest.with_name(f"{dest.stem}_{i}.jpg").unlink()


def main():
    clip = pathlib.Path(sys.argv[1]).resolve()
    expected = sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    info = probe(clip)
    dur = float(info["format"]["duration"])
    r = mlx_whisper.transcribe(str(clip), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en", word_timestamps=True)
    heard = r["text"].strip()
    words = [w for s in r["segments"] for w in s.get("words", [])]
    speech = (words[-1]["end"] - words[0]["start"]) if words else 0
    exp_n, got_n = norm(expected), norm(heard)
    sm = difflib.SequenceMatcher(None, exp_n, got_n)
    diffs = [f"{op}: expected '{' '.join(exp_n[a:b])}' heard '{' '.join(got_n[c:d])}'"
             for op, a, b, c, d in sm.get_opcodes() if op != "equal"]
    report = {
        "clip": clip.name, "duration_s": round(dur, 2),
        "video": [s for s in info["streams"] if s["codec_type"] == "video"][0],
        "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]),
        "expected": expected, "heard": heard,
        "word_match": round(sm.ratio(), 3), "differences": diffs,
        "speech_start_s": round(words[0]["start"], 2) if words else None,
        "speech_end_s": round(words[-1]["end"], 2) if words else None,
        "words_per_s": round(len(got_n) / speech, 2) if speech else None,
    }
    clip.with_name(clip.stem + "_qc.json").write_text(json.dumps(report, indent=2))
    strip(clip, dur, n, clip.with_name(clip.stem + "_strip.jpg"))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
