"""Online b-roll for rawedit.py: free stock + TikTok, every clip described by Haiku (the agent never looks at frames).

Usage (.venv/bin/python -I tools/broll_web.py ...):
  mixkit <dir> <slot> "<query>" [--max 6]       free Mixkit stock (largest file available) -> <dir>/<slot>_mk<id>.mp4
  tiktok <dir> <slot> <url> [<url> ...]         TikTok through SnapTik (headless, no watermark) -> <dir>/<slot>_tt<id>.mp4
  file   <dir> <slot> <path|url>                any local file or direct mp4 URL
  describe <dir> [--force]                      Haiku reads 4 frames per clip -> CLIPS.json {what, good, best_in, issues}
  list <dir>
  sheet <file> <out.jpg> [--every 0.5] [--from s] [--to s]   timestamped contact sheet (for a reviewer, not the main session)
  cuts <file>                                   hard cuts inside a clip (edited footage is not one take)
  speech <file>                                 Whisper words in the clip audio (ASMR audio only where nobody talks)
Clips stay in their own folder (downloaded data); this script lives in tools/.
"""
import base64, hashlib, json, os, pathlib, re, subprocess, sys, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
PW_PY = os.environ.get("PLAYWRIGHT_PYTHON") or sys.executable   # a python with Playwright + Chromium installed


def env():
    for l in ((ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []):
        if "=" in l and not l.lstrip().startswith("#"):
            k, v = l.split("=", 1); os.environ.setdefault(k.strip(), v.strip())


def probe(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                        "-of", "json", str(f)], capture_output=True, text=True)
    j = json.loads(r.stdout or "{}"); s = (j.get("streams") or [{}])[0]
    return float(j.get("format", {}).get("duration", 0)), s.get("width", 0), s.get("height", 0)


def meta(d):
    f = d / "CLIPS.json"; return json.loads(f.read_text()) if f.exists() else {}


def put(d, name, row):
    m = meta(d); m[name] = {**m.get(name, {}), **row}; (d / "CLIPS.json").write_text(json.dumps(m, indent=1))


def get(url, out):
    out.write_bytes(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read())


def mixkit(d, slot, query, mx=6):
    q = re.sub(r"\s+", "-", query.strip().lower())
    h = urllib.request.urlopen(urllib.request.Request(f"https://mixkit.co/free-stock-video/{q}/", headers=UA)).read().decode("utf8", "ignore")
    ids = list(dict.fromkeys(re.findall(r"assets\.mixkit\.co/videos/(\d+)/\1-360\.mp4", h)))
    have = {v.get("source_url") for v in meta(d).values()}
    n = 0
    for i in ids:
        if n >= mx: break
        src = f"https://mixkit.co/free-stock-video/{q}/#{i}"
        if src in have or any(f"_mk{i}." in p.name for p in d.glob("*.mp4")): continue
        out = d / f"{slot}_mk{i}.mp4"
        for res in ("2160", "1080", "720"):
            try: get(f"https://assets.mixkit.co/videos/{i}/{i}-{res}.mp4", out); break
            except Exception: continue
        if not out.exists() or out.stat().st_size < 50000: out.unlink(missing_ok=True); continue
        dur, w, hh = probe(out)
        put(d, out.name, {"slot": slot, "source": "mixkit", "source_url": src, "seconds": round(dur, 1), "width": w, "height": hh, "query": query})
        print(f"  {out.name} {w}x{hh} {dur:.1f}s"); n += 1
    print(f"mixkit '{query}': {n} new of {len(ids)} results")


SNAPTIK = r'''
import sys
from playwright.sync_api import sync_playwright
url, out = sys.argv[1], sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch(headless=True); c = b.new_context(accept_downloads=True); pg = c.new_page()
    pg.goto("https://snaptik.app/en2", wait_until="domcontentloaded", timeout=60000)
    pg.fill("#url-input", url); pg.keyboard.press("Enter")
    btn = pg.get_by_role("link", name="Download (No Watermark)", exact=True).or_(pg.get_by_role("button", name="Download (No Watermark)", exact=True)).first
    btn.wait_for(timeout=60000)
    with pg.expect_download(timeout=120000) as dl: btn.click()
    dl.value.save_as(out); b.close()
'''


def tiktok(d, slot, urls):
    sc = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "snaptik_dl.py"; sc.write_text(SNAPTIK)
    for u in urls:
        vid = (re.search(r"/video/(\d+)", u) or re.search(r"(\d{15,})", u))
        vid = vid.group(1) if vid else hashlib.md5(u.encode()).hexdigest()[:10]
        out = d / f"{slot}_tt{vid[-8:]}.mp4"
        if out.exists(): print(f"  have {out.name}"); continue
        r = subprocess.run([PW_PY, "-I", str(sc), u, str(out)], capture_output=True, text=True)
        if r.returncode or not out.exists():
            print(f"  FAILED {u}: {(r.stderr or '')[-200:]}"); continue
        dur, w, h = probe(out)
        put(d, out.name, {"slot": slot, "source": "tiktok", "source_url": u, "seconds": round(dur, 1), "width": w, "height": h})
        print(f"  {out.name} {w}x{h} {dur:.1f}s"); time.sleep(3)


def file_(d, slot, src):
    name = pathlib.Path(src.split("?")[0]).name; out = d / f"{slot}_{name if name.endswith('.mp4') else name + '.mp4'}"
    if src.startswith("http"): get(src, out)
    else: subprocess.run(["cp", src, str(out)], check=True)
    dur, w, h = probe(out); put(d, out.name, {"slot": slot, "source": "file", "source_url": src, "seconds": round(dur, 1), "width": w, "height": h})
    print(f"  {out.name} {w}x{h} {dur:.1f}s")


def describe(d, force=False, brief=""):
    env(); import sys as _sys, os as _os; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import claude_client as anthropic
    from brand import BRAND
    cl = anthropic.Anthropic()
    for f in sorted(d.glob("*.mp4")):   # files dropped in by hand or lost from CLIPS.json get a row
        if f.name not in meta(d):
            dur, w, h = probe(f); put(d, f.name, {"slot": f.name.split("_")[0], "source": "file", "seconds": round(dur, 1), "width": w, "height": h})
    for name, row in meta(d).items():
        if row.get("what") and not force: continue
        f = d / name
        if not f.exists(): continue
        dur = row.get("seconds") or probe(f)[0]
        k = 6 if dur <= 30 else 10
        ts = [round(dur * (i + 0.5) / k, 2) for i in range(k)]; content = []
        for t in ts:
            jpg = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(f), "-frames:v", "1", "-vf", "scale=360:-2", "-f", "image2", "-c:v", "mjpeg", "-"], capture_output=True).stdout
            if jpg: content += [{"type": "text", "text": f"t={t}s"}, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpg).decode()}}]
        content.append({"type": "text", "text": (
            f"Four frames from a {dur:.0f}s clip ({row.get('width')}x{row.get('height')}), wanted as b-roll for slot '{row['slot']}' "
            f"in a 9:16 ad for {BRAND['product']} (problem: {BRAND['problem']}). {brief} Reply JSON only: {{\"what\": \"what is visible, 15 words\", "
            "\"fits_slot\": true/false, \"good\": 1-3 (3 = real, clean, on-topic), \"best_in\": second where the best 2-4 s starts, "
            "\"issues\": \"burned-in text / watermark / logo / blur / off-topic / none\", \"crop_ok_9x16\": true/false, "
            "\"moments\": [{\"t\": second, \"what\": \"8 words\", \"clean\": true if no text/logo on screen}] one per frame}")})
        r = cl.messages.create(model="claude-haiku-5-5", max_tokens=8000, messages=[{"role": "user", "content": content}])
        t = "".join(getattr(b, "text", "") for b in r.content); j = re.search(r"\{.*\}", t, re.S)
        try: row.update(json.loads(j.group(0)))
        except Exception: row["what"] = "(unparsed) " + t[:120]
        put(d, name, row)
        print(f"  {name:28s} g{row.get('good')} fit={row.get('fits_slot')} in={row.get('best_in')}  {row.get('what','')[:70]} | {row.get('issues','')}")


def sheet(f, out, every=0.5, a=0.0, b=None, cols=6, w=240):
    from PIL import Image, ImageDraw, ImageFont
    dur = probe(f)[0]; b = min(b or dur, dur); ts = []; t = a
    while t < b - 0.05: ts.append(round(t, 2)); t += every
    tiles = []
    for t in ts:
        jpg = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(f), "-frames:v", "1", "-vf", f"scale={w}:-2",
                              "-f", "image2", "-c:v", "mjpeg", "-"], capture_output=True).stdout
        if not jpg: continue
        import io; im = Image.open(io.BytesIO(jpg)).convert("RGB"); d = ImageDraw.Draw(im)
        d.rectangle([0, 0, 64, 22], fill=(0, 0, 0)); d.text((4, 4), f"{t:.1f}s", fill=(255, 255, 0), font=ImageFont.load_default())
        tiles.append(im)
    if not tiles: sys.exit("no frames")
    tw, th = tiles[0].size; rows = -(-len(tiles) // cols)
    S = Image.new("RGB", (cols * tw, rows * th), (30, 30, 30))
    for i, im in enumerate(tiles): S.paste(im, ((i % cols) * tw, (i // cols) * th))
    S.save(out, quality=82); print(f"{out} {len(tiles)} frames {a:.1f}-{b:.1f}s")


def cuts(f, thr=0.12, a=0.0, b=None):
    """Per-frame scene score; an isolated spike above thr is a hard cut (0.12 catches edits the 0.35 rule missed; steady
    camera motion stays below ~0.1). Run it on every window you plan to call one take (R006)."""
    args = ["ffmpeg", "-hide_banner", "-ss", str(a)] + (["-to", str(b)] if b else []) + ["-i", str(f), "-vf",
            "scale=320:-2,select='gte(scene,0)',metadata=print", "-an", "-f", "null", "-"]
    r = subprocess.run(args, capture_output=True, text=True)
    ts = [float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)]; sc = [float(x) for x in re.findall(r"lavfi\.scene_score=([\d.]+)", r.stderr)]
    pk = [round(t_ + a, 2) for t_, s_ in zip(ts, sc) if s_ > thr and t_ > 0.15]   # the first frames after a seek score high by themselves
    print(f"{pathlib.Path(f).name}: {len(pk)} cut(s) {pk} (max score {max(sc) if sc else 0:.2f})"); return pk


def speech(f):
    import mlx_whisper
    wav = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "_speech.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(f), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    r = mlx_whisper.transcribe(str(wav), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en", word_timestamps=True,
                               no_speech_threshold=0.5, condition_on_previous_text=False, hallucination_silence_threshold=1.0)
    ws = [(round(w["start"], 1), w["word"].strip()) for s_ in r["segments"] for w in s_.get("words", []) if s_.get("no_speech_prob", 0) < 0.6]
    print(f"{pathlib.Path(f).name}: {len(ws)} spoken words " + " ".join(f"{t}:{x}" for t, x in ws[:40])); return ws


def show(d):
    for name, r in sorted(meta(d).items()):
        print(f"{name:30s} {r.get('seconds',0):5.1f}s {r.get('width')}x{r.get('height')} g{r.get('good','?')} fit={r.get('fits_slot','?')} in={r.get('best_in','?')}  {r.get('what','')[:80]} | {r.get('issues','')}")


def main():
    a = sys.argv[1:]
    if len(a) < 2: sys.exit(__doc__)
    c, d = a[0], pathlib.Path(a[1]).resolve()
    if c not in ("sheet", "cuts", "speech"): d.mkdir(parents=True, exist_ok=True)
    opt = lambda n, v=None: a[a.index(n) + 1] if n in a else v
    if c == "mixkit": mixkit(d, a[2], a[3], int(opt("--max", 6)))
    elif c == "tiktok": tiktok(d, a[2], [x for x in a[3:] if x.startswith("http")])
    elif c == "file": file_(d, a[2], a[3])
    elif c == "describe": describe(d, "--force" in a, opt("--brief", ""))
    elif c == "list": show(d)
    elif c == "sheet": sheet(pathlib.Path(a[1]), a[2], float(opt("--every", 0.5)), float(opt("--from", 0)), float(opt("--to")) if opt("--to") else None)
    elif c == "cuts": cuts(pathlib.Path(a[1]), float(opt("--thr", 0.12)), float(opt("--from", 0)), float(opt("--to")) if opt("--to") else None)
    elif c == "speech": speech(pathlib.Path(a[1]))
    else: sys.exit(__doc__)


if __name__ == "__main__":
    main()
