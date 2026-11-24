"""Measure the editing numbers of reference ads so pacing rules can be written as numbers, not vibes.

Usage: pace_bench.py <set-name> <video-or-json> [...]
  video: local .mp4 files; json: a bf_video_items.json-style list (fields video/brand/format/tier/len) — downloads the mp4s.
  Options: --format "UGC,Talking head" --tier Strong --max 24
Writes taste/_bench/<set>/BENCH.md + bench.json: per ad — length, cuts, cuts/10s, average + median shot, first cut, shots < 1.2 s,
longest shot, words, words/min, words in the first 3 s, longest pause, LUFS. Then medians per format.
Measures only what ffmpeg + Whisper can measure. Caption density and music level need stems or OCR and are not claimed.
"""
import json, pathlib, re, statistics, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).parent))


def sh(*c, **k):
    return subprocess.run([str(x) for x in c], capture_output=True, text=True, errors="replace", **k)


def duration(f):
    return float(sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f).stdout.strip() or 0)


def cuts(f, thresh=0.3):
    r = sh("ffmpeg", "-v", "info", "-i", f, "-vf", f"select='gt(scene,{thresh})',showinfo", "-an", "-f", "null", "-")
    return [float(m) for m in re.findall(r"pts_time:([\d.]+)", r.stderr)]


def lufs(f):
    r = sh("ffmpeg", "-hide_banner", "-nostats", "-i", f, "-af", "loudnorm=I=-14:TP=-1.5:print_format=json", "-f", "null", "-")
    m = re.search(r"\{.*\}", r.stderr, re.S)
    return float(json.loads(m.group(0))["input_i"]) if m else None


def words(f):
    import mlx_whisper
    r = mlx_whisper.transcribe(str(f), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en", word_timestamps=True)
    return [(w["word"].strip(), w["start"], w["end"]) for s in r["segments"] for w in s.get("words", []) if w["word"].strip()]


def measure(f, meta):
    d = duration(f); c = [t for t in cuts(f) if 0.2 < t < d - 0.2]
    bounds = [0.0] + c + [d]; shots = [b - a for a, b in zip(bounds, bounds[1:])]
    w = words(f)
    pauses = [b[1] - a[2] for a, b in zip(w, w[1:])] if len(w) > 1 else [0]
    speech = (w[-1][2] - w[0][1]) if w else 0
    m = {"file": pathlib.Path(f).name, "len": round(d, 1), "cuts": len(c), "cuts_per_10s": round(len(c) / d * 10, 2) if d else 0,
         "avg_shot": round(statistics.mean(shots), 2), "median_shot": round(statistics.median(shots), 2),
         "first_cut": round(c[0], 2) if c else None, "shots_under_1_2": sum(1 for s in shots if s < 1.2), "longest_shot": round(max(shots), 2),
         "words": len(w), "wpm": round(len(w) / speech * 60) if speech > 3 else None, "words_first_3s": sum(1 for x in w if x[1] < 3),
         "longest_pause": round(max(pauses), 2), "lufs": lufs(f), "first_words": " ".join(x[0] for x in w[:12])}
    m.update({k: meta.get(k) for k in ("brand", "format", "tier", "verbalHook", "rank", "variants") if k in meta})
    return m


def main():
    a = sys.argv[1:]; name = a[0]; args = a[1:]
    opt = lambda k, d=None: args[args.index(k) + 1] if k in args else d
    fmts = set(x.strip() for x in opt("--format", "").split(",") if x.strip()); tier = opt("--tier"); mx = int(opt("--max", 24))
    out = ROOT / "taste" / "_bench" / name; out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for x in args:
        if x.startswith("--") or x in (opt("--format"), tier, opt("--max")): continue
        p = pathlib.Path(x)
        if p.suffix == ".json":
            for it in json.loads(p.read_text()):
                if fmts and it.get("format") not in fmts: continue
                if tier and it.get("tier") != tier: continue
                if not it.get("video"): continue
                jobs.append((it["video"], it))
        else:
            jobs.append((str(p), {}))
    jobs = jobs[:mx]; rows = []
    for src, meta in jobs:
        if src.startswith("http"):
            f = out / (re.sub(r"[^A-Za-z0-9]+", "_", meta.get("brand", "ad")) + "_" + str(meta.get("id", len(rows))) + ".mp4")
            if not f.exists() or f.stat().st_size < 1000:
                sh("curl", "-sL", "--retry", "2", "-o", f, src)
            if not f.exists() or f.stat().st_size < 1000: print("skip (download failed)", src[:80]); continue
        else:
            f = pathlib.Path(src)
        print("measure", f.name, flush=True)
        try: rows.append(measure(f, meta))
        except Exception as e: print("  failed:", e)
    (out / "bench.json").write_text(json.dumps(rows, indent=1))
    cols = ["brand", "format", "tier", "len", "cuts", "cuts_per_10s", "avg_shot", "median_shot", "first_cut", "shots_under_1_2", "longest_shot", "words", "wpm", "words_first_3s", "longest_pause", "lufs"]
    L = [f"# Pacing bench — {name}", f"{len(rows)} ads. Cuts = ffmpeg scene change > 0.3 (misses soft dissolves, counts hard flashes). Words = Whisper.", "",
         "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows: L.append("| " + " | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols) + " |")
    L += ["", "## Medians by format", "", "| format | n | len | cuts/10s | median shot | first cut | shots<1.2s | wpm | words first 3s | longest pause | LUFS |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    by = {}
    for r in rows: by.setdefault(r.get("format") or "all", []).append(r)
    def med(rs, k):
        v = [r[k] for r in rs if r.get(k) is not None]
        return f"{statistics.median(v):.2f}" if v else "-"
    for fmt, rs in sorted(by.items(), key=lambda x: -len(x[1])):
        L.append(f"| {fmt} | {len(rs)} | {med(rs,'len')} | {med(rs,'cuts_per_10s')} | {med(rs,'median_shot')} | {med(rs,'first_cut')} | {med(rs,'shots_under_1_2')} | {med(rs,'wpm')} | {med(rs,'words_first_3s')} | {med(rs,'longest_pause')} | {med(rs,'lufs')} |")
    if len(rows) > 1:
        L.append(f"| ALL | {len(rows)} | {med(rows,'len')} | {med(rows,'cuts_per_10s')} | {med(rows,'median_shot')} | {med(rows,'first_cut')} | {med(rows,'shots_under_1_2')} | {med(rows,'wpm')} | {med(rows,'words_first_3s')} | {med(rows,'longest_pause')} | {med(rows,'lufs')} |")
    L += ["", "## Openings (first 12 words)", ""] + [f"- **{r.get('brand','?')}** ({r.get('format','?')}): {r['first_words']}" for r in rows]
    (out / "BENCH.md").write_text("\n".join(L)); print("\n".join(L[:6])); print(f"... wrote {out/'BENCH.md'}")


if __name__ == "__main__":
    main()
