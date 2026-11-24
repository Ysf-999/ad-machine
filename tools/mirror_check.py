"""Is a selfie take mirrored? Reads on-screen text (logo, packaging, signs, shirts) with Apple Vision OCR on a few frames,
once as shot and once flipped. Real words read better the right way round, so if the FLIPPED frames give clearly more
dictionary words, the take is mirrored and should get hflip. No text in shot = "unknown" (nothing to judge, leave it).

  .venv/bin/python tools/mirror_check.py <video> [--frames 8] [--json]

Added 2026-11-14 (idea from the "DaVinci Resolve + Claude" guide: check every take for backwards text, flip only those).
The agent never looks at the frames; this prints numbers only.
"""
import json, pathlib, re, subprocess, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from brand import BRAND as _B

DICT = pathlib.Path("/usr/share/dict/words")
BRAND = {w for k in ("brand", "product", "product_word", "transcribe_hint") for w in re.findall(r"[a-z]{3,}", str(_B.get(k, "")).lower())} | {"sale"}
_words = None


def words():
    global _words
    if _words is None:
        _words = {w.strip().lower() for w in DICT.read_text().splitlines() if len(w.strip()) >= 3} | BRAND
    return _words


def ocr(png):
    import Quartz, Vision
    url = Quartz.CFURLCreateWithFileSystemPath(None, str(png), Quartz.kCFURLPOSIXPathStyle, False)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(False)   # correction would "fix" backwards text into words and hide the signal
    h = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    ok, err = h.performRequests_error_([req], None)
    out = []
    for o in (req.results() or []):
        c = o.topCandidates_(1)
        if c: out.append((str(c[0].string()), float(c[0].confidence())))
    return out


def score(lines):
    """Confidence-weighted count of dictionary words (3+ letters) in the OCR lines."""
    W = words(); s = 0.0; hits = []
    for text, conf in lines:
        for t in re.findall(r"[A-Za-z]{3,}", text):
            if t.lower() in W: s += conf; hits.append(t)
    return s, hits


def duration(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def check(video, n=8):
    video = pathlib.Path(video); d = duration(video)
    if d <= 0: return {"verdict": "unknown", "reason": "no duration"}
    so = sf = 0.0; ho, hf = [], []
    with tempfile.TemporaryDirectory() as td:
        for k in range(n):
            t = d * (k + 0.5) / n
            for flip, tag in ((False, "o"), (True, "f")):
                png = pathlib.Path(td) / f"{k}{tag}.png"
                vf = "scale=1080:-2" + (",hflip" if flip else "")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-vf", vf, str(png)], check=True)
                s, h = score(ocr(png))
                if flip: sf += s; hf += h
                else: so += s; ho += h
    so, sf = round(so, 2), round(sf, 2)
    if max(so, sf) < 2.0: verdict = "unknown"            # too little readable text to judge
    elif sf >= 2 * so + 1.0: verdict = "mirrored"
    elif so >= 2 * sf + 1.0: verdict = "ok"
    else: verdict = "unclear"
    return {"verdict": verdict, "score_as_shot": so, "score_flipped": sf, "frames": n,
            "words_as_shot": sorted(set(ho))[:12], "words_flipped": sorted(set(hf))[:12]}


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    n = int(a[a.index("--frames") + 1]) if "--frames" in a else 8
    r = check(a[0], n)
    print(json.dumps(r) if "--json" in a else
          f"{pathlib.Path(a[0]).name}: {r['verdict']}  (as shot {r.get('score_as_shot')}, flipped {r.get('score_flipped')})  "
          f"as-shot words {r.get('words_as_shot')}  flipped words {r.get('words_flipped')}")
