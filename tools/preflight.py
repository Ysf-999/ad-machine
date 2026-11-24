"""Preflight: the last gate before ANY video reaches the owner (Frame.io push, Drive, chat). Added 2026-11-15.

  .venv/bin/python tools/preflight.py <project> [--file X.mp4] [--quick]

Why: the owner kept correcting the same things (962 revisions, the same ~34 problems). Most recent ads were built
with project-local scripts (edit.py, gfx.py) that bypass the shared tools' defaults, so the check has to run on the
FINISHED VIDEO. This script:
  1. runs automatic checks on the master (numbers only, the agent never looks at frames):
       format 9:16 · tilted text (Apple Vision OCR angle, T13) · repeated shots (perceptual hash, T09) · cuts in the
       hook (T24) · freezes/lag (T23) · banned clips referenced anywhere in the project (T06) · loud audio at the very
       end = cut word/song (T19/T22) · av_check (sync, silence holes, black frames) · caption_sync_check when the
       project has EDIT_KIT/captions.ass + VO/vo.mp3 (T17)
  2. writes PREFLIGHT.md with every owner taste rule (feedback/taste_rules.json, most-repeated first) and every earlier
     revision on this ad AND its sibling hooks as a checkbox list. The producer answers each line:
       [x] = checked, holds   [n/a] = not in this video   and adds a few words where it matters.
`frameio.py push` refuses to upload until PREFLIGHT.md matches the current master, has no unanswered box and no
unresolved FAIL (write "override: <reason>" on a FAIL line only if the owner asked for that exact thing).
--quick skips OCR + hashing (re-check after a text-only fix).

Cloud split (2026-11-22, cloud/docs/CONTROLLER.md "Checks in the cloud"):
  --media-json <out.json>   run ONLY the checks that need nothing but the finished video and the project folder (format,
                            repeated shots, hook cuts, freezes, tail, length, caption blocks, av_check, caption sync) and
                            write them as JSON with the file's fingerprint. No PREFLIGHT.md. The cloud worker runs this.
  --media-from <in.json>    use those results instead of measuring again, when they are for this exact file; the checks
                            that need this Mac (Apple Vision tilt, banned list, sibling hooks, moment cards) run as
                            usual and PREFLIGHT.md is written as usual. A file for another render is ignored.
"""
import hashlib, json, math, pathlib, re, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from brand import BRAND
sys.path.insert(0, str(ROOT / "tools"))
PY = str(ROOT / ".venv" / "bin" / "python")
TILT_MAX = 1.5      # degrees (owner: never rotate text; 11/12, again 11/13-11/14)
HOOK_S, HOOK_CUTS = 6.0, 2


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def probe(f):
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
             "-of", "json", str(f)])
    d = json.loads(r.stdout or "{}")
    s = (d.get("streams") or [{}])[0]
    return int(s.get("width", 0)), int(s.get("height", 0)), float(d.get("format", {}).get("duration", 0))


def fingerprint(f):
    """Cheap identity of the master: size + hash of the first and last MB (the gate compares it on push)."""
    f = pathlib.Path(f); h = hashlib.sha1(); n = f.stat().st_size
    with f.open("rb") as fh:
        h.update(fh.read(1 << 20)); fh.seek(max(0, n - (1 << 20))); h.update(fh.read(1 << 20))
    return f"{n}-{h.hexdigest()[:16]}"


def frames(f, fps, width, td):
    run(["ffmpeg", "-v", "error", "-i", str(f), "-vf", f"fps={fps},scale={width}:-2", str(pathlib.Path(td) / "f%05d.png")])
    return sorted(pathlib.Path(td).glob("f*.png"))


# ---------- T13 tilted text ----------
def ocr_boxes(png):
    import Quartz, Vision
    url = Quartz.CFURLCreateWithFileSystemPath(None, str(png), Quartz.kCFURLPOSIXPathStyle, False)
    img = Quartz.CGImageSourceCreateImageAtIndex(Quartz.CGImageSourceCreateWithURL(url, None), 0, None)
    W, H = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate); req.setUsesLanguageCorrection_(True)
    Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None).performRequests_error_([req], None)
    out = []
    for o in (req.results() or []):
        c = o.topCandidates_(1)
        if not c: continue
        tl, tr, bl = o.topLeft(), o.topRight(), o.bottomLeft()
        ang = math.degrees(math.atan2((tr.y - tl.y) * H, (tr.x - tl.x) * W))
        hgt = math.hypot((tl.x - bl.x) * W, (tl.y - bl.y) * H) / H
        out.append((str(c[0].string()), float(c[0].confidence()), ang, hgt))
    return out


def check_tilt(pngs, step):
    """Overlay text (big, confident, 4+ letters) whose baseline is rotated, seen on 2+ samples in a row."""
    hits = []
    for i, p in enumerate(pngs):
        for text, conf, ang, hgt in ocr_boxes(p):
            # 1.5-25 deg = a crooked overlay; ~90 deg is product print (a logo printed sideways on the product)
            if conf >= 0.5 and hgt >= 0.022 and len(re.sub(r"[^A-Za-z]", "", text)) >= 4 and TILT_MAX < abs(ang) < 25:
                hits.append((i * step, text, ang))
    runs, out = {}, []
    for t, text, ang in hits:
        k = re.sub(r"[^a-z]", "", text.lower())[:12]
        runs.setdefault(k, []).append((t, text, ang))
    for k, v in runs.items():
        ts = [x[0] for x in v]
        if len(v) >= 2 and any(abs(a - b) <= step * 1.5 for a, b in zip(ts, ts[1:])):
            out.append(f"FAIL T13 tilted text '{v[0][1][:40]}' at {ts[0]:.1f}-{ts[-1]:.1f}s, {sum(x[2] for x in v) / len(v):+.1f} deg")
    return out


# ---------- T09 repeated shots ----------
def dhash(png):
    from PIL import Image, ImageStat
    im = Image.open(png).convert("L")
    std = ImageStat.Stat(im).stddev[0]
    s = im.resize((9, 8), Image.BILINEAR); px = list(s.getdata())
    bits = 0
    for r in range(8):
        for c in range(8):
            bits = (bits << 1) | (px[r * 9 + c] > px[r * 9 + c + 1])
    return bits, std


def check_repeats(pngs, step, min_gap=4.0, max_ham=5):
    hs = [dhash(p) for p in pngs]
    pairs = []
    for i in range(len(hs)):
        if hs[i][1] < 14: continue                       # flat/black frames match everything
        for j in range(i + int(min_gap / step), len(hs)):
            if hs[j][1] >= 14 and bin(hs[i][0] ^ hs[j][0]).count("1") <= max_ham:
                pairs.append((i, j))
    # group into runs (i, j), (i+1, j+1) ... = a repeated stretch
    seen, out = set(), []
    for i, j in pairs:
        if (i, j) in seen: continue
        k = 0
        while (i + k, j + k) in set(pairs): seen.add((i + k, j + k)); k += 1
        if k >= 2:
            out.append((i * step, (i + k) * step, j * step, (j + k) * step))
    out.sort(key=lambda x: -(x[1] - x[0]))
    kept = []   # one line per repeat: drop runs that overlap a longer one already kept
    for r in out:
        if not any(r[0] < k[1] and k[0] < r[1] and r[2] < k[3] and k[2] < r[3] for k in kept):
            kept.append(r)
    out = kept
    return [f"WARN T09 repeated shot: {b0:.1f}-{b1:.1f}s looks like {a0:.1f}-{a1:.1f}s (fine only if it is the creator's own a-roll)"
            for a0, a1, b0, b1 in out[:8]]


# ---------- T24 hook cuts / T23 freezes ----------
_HOOK_CUTS = {}


def hook_cut_times(f):
    """Scene cuts in the first HOOK_S seconds (one -f null pass, cached per file so T24 and T49 share it)."""
    p = pathlib.Path(f)
    try: k = (str(p.resolve()), p.stat().st_mtime_ns)
    except OSError: return []
    if k not in _HOOK_CUTS:
        r = run(["ffmpeg", "-v", "info", "-t", str(HOOK_S), "-i", str(f), "-vf", "select='gt(scene,0.32)',showinfo", "-f", "null", "-"])
        _HOOK_CUTS[k] = [float(m) for m in re.findall(r"pts_time:([\d.]+)", r.stderr)]
    return _HOOK_CUTS[k]


def check_hook_cuts(f):
    cuts = hook_cut_times(f)
    if len(cuts) > HOOK_CUTS:
        return [f"WARN T24 {len(cuts)} hard cuts in the first {HOOK_S:.0f}s ({', '.join(f'{c:.1f}' for c in cuts)}s): owner wants the hook in one or two takes"]
    return [f"PASS T24 hook cuts in first {HOOK_S:.0f}s: {len(cuts)}"]


def check_freezes(f, dur):
    r = run(["ffmpeg", "-v", "info", "-i", str(f), "-vf", "freezedetect=n=0.002:d=0.6", "-an", "-f", "null", "-"])
    st = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", r.stderr)]
    du = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", r.stderr)]
    out = []
    for s, d in zip(st, du + [dur] * (len(st) - len(du))):
        if s > dur - 4.0 and d < 6:    # end card hold
            continue
        out.append(f"WARN T23 frozen picture {s:.1f}-{s + d:.1f}s ({d:.1f}s): lag/pause unless it is a deliberate hold or card")
    return out or ["PASS T23 no freezes over 0.6 s outside the end card"]


# ---------- T06 banned clips ----------
def project_dirs(proj):
    dirs = [proj]
    rd = proj / "README.txt"
    if rd.exists():
        m = re.search(r"\.\./([\w.-]+)", rd.read_text())
        if m and (proj.parent / m.group(1)).exists():
            dirs.append(proj.parent / m.group(1))
    return dirs


import banned   # tools/banned.py: the one reader of footage/BANNED_CLIPS.json (the file scan moved there 2026-11-22)
SKIP_DIRS, TEXT_EXT, MEDIA_RE, live_files = banned.SKIP_DIRS, banned.TEXT_EXT, banned.MEDIA_RE, banned.live_files


def load_plan(proj):
    try:
        p = json.loads((proj / "plan.json").read_text())
        return p if isinstance(p, dict) else None
    except (OSError, ValueError):
        return None


def check_banned(proj):
    """T06: banned ids / names anywhere in the live build files (as before), plus every clip window the plan shows checked
    against the banned windows and the no-id notes (exact plan data: FAIL; a line-scoped window: WARN)."""
    out = []
    for kind, rel, key, detail in banned.file_hits(project_dirs(proj), ROOT):
        if kind == "id": out.append(f"FAIL T06 banned clip {key[:12]} ({detail[:60]}) referenced in {rel}")
        else: out.append(f"FAIL T06 banned clip name '{key.strip()[:70]}' (rule '{detail}') in {rel}")
    out = sorted(set(out))
    plan = load_plan(proj)
    if plan is not None:
        old = " ".join(out); extra = []
        for h in banned.plan_hits(plan, ROOT):
            if h["kind"] == "clip":
                m = re.search(r"banned clip (\S{12})|rule '([^']+)'|banned name '([^']+)'", h["reason"])
                tag = next((g for g in (m.groups() if m else ()) if g), None)
                if tag and tag in old: continue     # the file scan already reports it
                extra.append(f"FAIL T06 {h['reason'][:110]} used at {h['where']} in plan.json")
            elif h["hard"]:
                extra.append(f"FAIL T06 {h['reason'][:110]}: plan uses {h['in']:.1f}-{h['out']:.1f}s of it at {h['where']}")
            else:
                extra.append(f"WARN T06 {h['reason'][:110]}: plan uses {h['in']:.1f}-{h['out']:.1f}s at {h['where']}; "
                             "fine only if this line is not that kind of line")
        out += sorted(set(extra), key=extra.index)
    return out or ["PASS T06 no banned clips referenced by the live build"]


# ---------- T33 length ----------
MAX_LEN = 120.0


def check_length(dur):
    """T33 exact: the master's duration against the owner's 2-minute ceiling."""
    m, s = divmod(dur, 60)
    if dur > MAX_LEN:
        return [f"FAIL T33 master runs {int(m)}:{s:04.1f} (over 2:00): cut a shorter version unless the owner asked for long form (then 'override: <his words>')"]
    return [f"PASS T33 length {int(m)}:{s:04.1f} (under 2:00)"]


# ---------- T51 banned phrases (brand/brand.json banned_phrases) ----------
BANNED_PHRASES = [(p, re.compile(r"\b" + r"[\s\W_]*".join(re.escape(w) for w in p.split()) + r"\b", re.I))
                  for p in BRAND.get("banned_phrases") or [] if p and p.strip()]
SPOKEN_KEYS = {"vo", "script", "text", "on_screen_text", "lines", "line", "lyric", "lyrics", "script_visual", "hook_card",
               "hook_text", "hook_card_lines", "caption", "captions", "cards", "text_cards", "overlay", "overlays", "endcard",
               "end_card", "cta", "words", "title", "subtitle", "say", "dialogue", "song"}


def _strings(x):
    if isinstance(x, str): yield x
    elif isinstance(x, dict):
        for v in x.values(): yield from _strings(v)
    elif isinstance(x, list):
        for v in x: yield from _strings(v)


def plan_spoken(plan):
    """Every string under a script / caption / card / lyric key of the plan."""
    out = []

    def walk(x, on):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in SPOKEN_KEYS: out.extend(_strings(v))
                else: walk(v, on)
        elif isinstance(x, list):
            for v in x: walk(v, on)
    walk(plan, False)
    return out


def ass_text(f):
    """Caption file -> the caption words in time order as one string (3-word cards split phrases across lines)."""
    rows = []
    for l in pathlib.Path(f).read_text(errors="ignore").splitlines():
        if not l.startswith("Dialogue:"): continue
        p = l.split(",", 9)
        if len(p) < 10: continue
        rows.append((p[1], re.sub(r"\{[^}]*\}", "", p[9]).replace("\\N", " ").replace("\\n", " ")))
    return " ".join(t for _, t in sorted(rows, key=lambda r: r[0].zfill(11)))


def check_sale_line(proj, plan):
    """T51 banned phrases (BRAND banned_phrases) in the plan's script/captions/cards/lyrics or in the burned caption file."""
    if not BANNED_PHRASES: return ["PASS T51 no banned phrases set in brand/brand.json"]
    hits = []
    texts = [("plan.json", s) for s in plan_spoken(plan or {})]
    texts += [(f"EDIT_KIT/{f.name}", ass_text(f)) for f in (sorted((proj / "EDIT_KIT").glob("*.ass")) if (proj / "EDIT_KIT").is_dir() else [])]
    for w, s in texts:
        for p, rx in BANNED_PHRASES:
            m = rx.search(s)
            if m: hits.append((p, w, s[max(0, m.start() - 25):m.end() + 15]))
    if hits:
        return [f"FAIL T51 banned phrase '{p}' in {w}: \"{' '.join(s.split())}\"" for p, w, s in hits[:4]]
    return ["PASS T51 no banned phrase in the script, cards or captions"]


# ---------- shot windows (T49 flashes, T09/T06 reuse) ----------
FLASH_FAIL, FLASH_WARN = 0.4, 0.9    # s on screen. T49: "never a clip shorter than about 1 s (a quarter-second ... glitch)"
REUSE_TOL = 0.3                      # s of the same source shown twice = the same window
DEMO_NOTE = re.compile(r"(product|demo|" + re.escape(BRAND["product_word"]) + r") (one-take|take|clean|swipe|wipe|stroke)|one-take|strand|swipes?\b|roll-?up|rope", re.I)
_CARDS = {}


def _card(fid):
    if not fid: return None
    if fid not in _CARDS:
        d = ROOT / "footage" / "moments" / "cards"
        fs = sorted(d.glob(f"{fid}*.json")) if d.is_dir() else []
        try: _CARDS[fid] = json.loads(fs[0].read_text()) if fs else None
        except ValueError: _CARDS[fid] = None
    return _CARDS[fid]


def _key(src, proj):
    fid = banned.fid_of(src)
    if fid: return "drive:" + fid[:10]
    p = pathlib.Path(str(src)).expanduser()
    if not p.is_absolute(): p = proj / p
    return "path:" + str(p.resolve())


def visual_windows(plan, proj):
    """What the picture shows, in play order: [{key, src, in, out, at, dur, shots, label}]. Voiceover-mode shots with
    contiguous source time from the same clip are one window (a speed change is not a cut); beat-mode b-roll inserts
    (and their split halves) are windows too. The creator's own a-roll is not."""
    out = []
    for w in banned.shot_windows(plan):
        k = _key(w["src"], proj)
        if out and out[-1]["key"] == k and abs(out[-1]["out"] - w["in"]) <= 0.15 and abs(out[-1]["at"] + out[-1]["dur"] - w["at"]) < 0.02:
            o = out[-1]; o["out"] = w["out"]; o["dur"] += w["dur"]; o["shots"].append(w["shot"]); continue
        out.append({"key": k, "src": w["src"], "in": w["in"], "out": w["out"], "at": w["at"], "dur": w["dur"], "shots": [w["shot"]],
                    "label": f"shot at {w['at']:.2f}s"})
    for b in plan.get("beats") or []:
        br = b.get("broll") if isinstance(b, dict) else None
        if not isinstance(br, dict): continue
        try:
            spd = float(br.get("speed") or 1.0) or 1.0; d = float(br.get("dur") or 0); a = float(br.get("in") or 0)
            at = float(b.get("t") or 0) + float(br.get("off") or 0)
        except (TypeError, ValueError):
            continue
        for x, a_, tag in ((br, a, "b-roll"), (br.get("split"), None, "split")):
            if not isinstance(x, dict): continue
            if a_ is None:
                try: a_ = float(x.get("in") or 0)
                except (TypeError, ValueError): a_ = 0.0
            src = x.get("file") or x.get("fid") or ""
            out.append({"key": _key(src, proj), "src": src, "in": a_, "out": a_ + d * spd, "at": at, "dur": d, "shots": [x],
                        "label": f"beat {b.get('n')} {tag} at {at:.2f}s"})
    return out


def _name(w):
    return pathlib.Path(str(w["src"])).name[:34]


def check_flash(proj, plan, f=None):
    """T49. Real-footage plans: the shot timeline is exact, so a window on screen < 0.4 s FAILs and < 0.9 s WARNs
    (a shot may carry "flash_ok": "<owner's words>" when a 1:1 remake copies a reference's flash montage). A hard cut the
    moment card found INSIDE a used source window can leave a sub-second piece: WARN (cut detection is a heuristic).
    Other ads (AI stitches) have no shot timeline here: the hook's scene cuts (already measured for T24) are used."""
    W = visual_windows(plan or {}, proj) if plan else []
    if not W:
        cuts = hook_cut_times(f) if f else []
        pieces = [(a, b) for a, b in zip(cuts, cuts[1:]) if b - a < FLASH_WARN]
        if pieces:
            return [f"WARN T49 hook scene cuts {a:.2f}s and {b:.2f}s are {b - a:.2f}s apart: a sub-second clip? (scene-cut estimate)" for a, b in pieces[:4]]
        return [f"PASS T49 no sub-second piece between the hook's scene cuts (first {HOOK_S:.0f}s; no shot timeline in plan.json, "
                "check the rest by eye)"]
    out, short = [], []
    for w in W:
        if w["dur"] <= 1e-3: continue
        ok = next((s.get("flash_ok") for s in w["shots"] if isinstance(s, dict) and s.get("flash_ok")), None)
        if w["dur"] < FLASH_FAIL and not ok:
            out.append(f"FAIL T49 {_name(w)} is on screen only {w['dur']:.2f}s at {w['at']:.2f}s (flash clip): merge it into a neighbour or drop it")
        elif w["dur"] < FLASH_WARN:
            short.append(w)
        c = _card(banned.fid_of(w["src"]))
        if c and w["dur"] >= FLASH_FAIL:
            spd = (w["out"] - w["in"]) / w["dur"] if w["dur"] else 1.0
            cc = sorted(float(x) for x in c.get("cuts") or [])
            # a burst of "cuts" < 0.8 s apart is fast motion (demo swipes), not edits: keep isolated cuts only
            iso = [x for k, x in enumerate(cc) if (k == 0 or x - cc[k - 1] >= 0.8) and (k + 1 == len(cc) or cc[k + 1] - x >= 0.8)]
            edges = [w["in"]] + [x for x in iso if w["in"] + 0.04 < x < w["out"] - 0.04] + [w["out"]]
            bad = [(a, b) for a, b in zip(edges, edges[1:]) if len(edges) > 2 and (b - a) / (spd or 1.0) < FLASH_WARN]
            if bad:
                a, b = min(bad, key=lambda p: p[1] - p[0])
                out.append(f"WARN T49 {_name(w)} at {w['at']:.2f}s crosses a hard cut in its source: {a:.2f}-{b:.2f}s is a "
                           f"{(b - a) / (spd or 1.0):.2f}s flash of another scene on screen (cut times from the moment card, estimates)")
    for w in short[:6]:
        out.append(f"WARN T49 {_name(w)} is on screen {w['dur']:.2f}s at {w['at']:.2f}s (under ~1 s)"
                   + (" [flash_ok]" if any(isinstance(s, dict) and s.get("flash_ok") for s in w["shots"]) else ""))
    if len(short) > 6: out.append(f"WARN T49 ... and {len(short) - 6} more shots under {FLASH_WARN:.1f}s")
    return out or [f"PASS T49 shortest shot on screen {min(w['dur'] for w in W if w['dur'] > 1e-3):.2f}s (no sub-second flash)"]


def _overlap(a, b):
    return min(a["out"], b["out"]) - max(a["in"], b["in"]) > REUSE_TOL


def _is_demo(w):
    """A product demo window: the shot note says so (and is not about a fake), or its moment card is a demo take."""
    for s in w["shots"]:
        if not isinstance(s, dict): continue
        note = str(s.get("note") or s.get("what") or "")
        if s.get("one_take") or (DEMO_NOTE.search(note) and "fake" not in note.lower()): return True
    c = _card(banned.fid_of(w["src"]))
    for m in (c or {}).get("moments", []):
        if m["start"] < w["out"] - 0.2 and w["in"] < m["end"] - 0.2 and m.get("kind") == "demo-take" and m.get("product_brand") != "other":
            return True
    return False


def _aligned(A, B):
    """Pairs (i, j) of the longest order-preserving match between two window lists: the body two hooks share by design
    (also when its timing drifts because each hook has its own VO take)."""
    n, m = len(A), len(B)
    L = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            L[i][j] = L[i + 1][j + 1] + 1 if A[i]["key"] == B[j]["key"] and _overlap(A[i], B[j]) else max(L[i + 1][j], L[i][j + 1])
    i = j = 0; out = set()
    while i < n and j < m:
        if A[i]["key"] == B[j]["key"] and _overlap(A[i], B[j]) and L[i][j] == L[i + 1][j + 1] + 1: out.add((i, j)); i += 1; j += 1
        elif L[i + 1][j] >= L[i][j + 1]: i += 1
        else: j += 1
    return out


def siblings(proj):
    """Other hook projects of the same family (family() of the folder name) that have a plan.json."""
    fam = family(proj.name)
    return sorted(p for p in proj.parent.iterdir() if p.is_dir() and p != proj and family(p.name) == fam and (p / "plan.json").exists())


def check_reuse(proj, plan):
    """T09 / T06. In this ad, the same source window twice is a repeat (exact plan data: FAIL). Across the batch, a demo
    take that another hook shows OUT of the shared body's order (a hook reusing a sibling's demo take) is a WARN: the
    shared body is found by order, and demo-ness comes from shot notes / moment cards, so it is a heuristic."""
    W = visual_windows(plan or {}, proj) if plan else []
    if not W: return ["PASS T09 no shot timeline in plan.json (perceptual repeat check above covers the master)"]
    out = []
    for i in range(len(W)):
        for j in range(i + 1, len(W)):
            a, b = W[i], W[j]
            if a["key"] == b["key"] and _overlap(a, b):
                out.append(f"FAIL T09 same clip window twice in this ad: {_name(a)} {max(a['in'], b['in']):.1f}-{min(a['out'], b['out']):.1f}s "
                           f"at {a['at']:.2f}s and again at {b['at']:.2f}s (another part of the clip is fine)")
    shared, other, n_sib = [], 0, 0
    for sp in siblings(proj):
        sp_plan = load_plan(sp); SW = visual_windows(sp_plan or {}, sp) if sp_plan else []
        if not SW: continue
        n_sib += 1; body = _aligned(W, SW)
        for i, w in enumerate(W):
            for j, v in enumerate(SW):
                if (i, j) in body or w["key"] != v["key"] or not _overlap(w, v): continue
                if _is_demo(w) or _is_demo(v): shared.append((w, sp.name, v))
                else: other += 1
    for w, s, v in shared[:6]:
        out.append(f"WARN T06/T09 demo take {_name(w)} {w['in']:.1f}-{w['out']:.1f}s at {w['at']:.2f}s is also in {s} at {v['at']:.2f}s, "
                   "outside the body the hooks share: demo clips must be unique across the batch")
    if len(shared) > 6: out.append(f"WARN T06/T09 ... and {len(shared) - 6} more demo takes shared with sibling hooks")
    if not out:
        out.append(f"PASS T09 no clip window twice in this ad; no demo take reused out of order by the {n_sib} sibling hook(s)"
                   + (f" ({other} non-demo clip(s) are shared out of order: allowed)" if other else ""))
    return out


# ---------- T19/T22 tail ----------
def check_tail(f, dur):
    r = run(["ffmpeg", "-v", "info", "-ss", str(max(0, dur - 0.25)), "-i", str(f), "-af", "astats=metadata=0", "-vn", "-f", "null", "-"])
    m = re.findall(r"RMS level dB: (-?[\d.]+|-inf)", r.stderr)
    lvl = max([float(x) for x in m if x != "-inf"] or [-99])
    if lvl > -28:
        return [f"WARN T19/T22 audio still at {lvl:.0f} dB in the last 0.25 s: check the last word and the song finish before the cut"]
    return [f"PASS T19 tail quiet ({lvl:.0f} dB in the last 0.25 s)"]


def _ass_seconds(x):
    h, m, sec = x.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)


def check_caption_events(proj, slack=0.15):
    """T17: two caption blocks on screen at once, or a block that ends before it starts. The sync check compares words
    with the audio and does not see this. Found 2026-11-22 on kids-song hooks 2 and 3: the hook word list also held
    body words, so Verse 1 was captioned twice and both copies were burned in. Blocks of one style must not overlap."""
    out = []
    for f in sorted((pathlib.Path(proj) / "EDIT_KIT").glob("*.ass")):
        by, neg = {}, []
        for l in f.read_text(errors="ignore").splitlines():
            p = l.split(",", 9)
            if not l.startswith("Dialogue:") or len(p) < 10: continue
            try: a, b = _ass_seconds(p[1]), _ass_seconds(p[2])
            except ValueError: continue
            text = re.sub(r"\{[^}]*\}", "", p[9]).replace("\\N", " ").strip()
            if b <= a: neg.append((a, b, text))
            else: by.setdefault(p[3].strip(), []).append((a, b, text))
        over = []
        for rows in by.values():
            rows.sort()
            for i, x in enumerate(rows):
                for y in rows[i + 1:]:
                    if y[0] >= x[1] - slack: break
                    over.append((x, y))
        if neg or over:
            x, y = over[0] if over else (neg[0], neg[0])
            out.append(f"FAIL T17 doubled captions in {f.name}: {len(over)} pairs of blocks on screen together, {len(neg)} ending before they start "
                       f"(first: '{x[2][:30]}' {x[0]:.2f}-{x[1]:.2f}s with '{y[2][:30]}' from {y[0]:.2f}s). Rebuild the captions from one word list.")
        else:
            out.append(f"PASS T17 no doubled captions in {f.name}")
    return out


def check_external(proj, f):
    out = []
    r = run([PY, str(ROOT / "tools" / "av_check.py"), "--check", str(f)], timeout=900)
    for l in (r.stdout + r.stderr).splitlines():
        if re.search(r"\bFAIL\b", l):
            out.append(f"FAIL av_check: {l.strip()[:160]}")
    out.append("PASS av_check" if not out else "")
    if (proj / "EDIT_KIT" / "captions.ass").exists() and (proj / "VO" / "vo.mp3").exists():
        r = run([PY, str(ROOT / "tools" / "caption_sync_check.py"), str(proj)], timeout=900)
        line = next((l for l in (r.stdout + r.stderr).splitlines() if "CAPTION SYNC" in l), "caption sync: no result line")
        out.append(("PASS " if "PASS" in line else "FAIL ") + "T17 " + line.strip()[:160])
    else:
        out.append("INFO T17 no EDIT_KIT/captions.ass + VO/vo.mp3 here: confirm captions by ear on the last third")
    return [o for o in out if o]


# ---------- earlier revisions on this ad + its batch ----------
def family(name):
    return re.sub(r"(-h\d+|-v\d+(-h\d+)?)$", "", name)


def earlier_notes(proj):
    import feedback
    fam = {family(d.name) for d in project_dirs(proj)}
    rows = [r for r in feedback.read_log() if family(r["ad"]) in fam and r["status"] in ("learned", "promoted", "open", "dismissed")
            and r.get("kind") != "like"]
    seen, out = set(), []
    for r in rows:
        k = re.sub(r"\[frame\.io[^\]]*\]", "", r["text"]).strip()[:140]
        if k in seen: continue
        seen.add(k); out.append((r, k))
    return out


# ---------- cloud split: the checks that need only the finished video ----------
def format_line(W, H):
    return f"PASS format {W}x{H}" if W and abs(W / H - 9 / 16) < 0.01 else f"FAIL format {W}x{H}: masters are always 9:16"


def media_lines(proj, f, W, H, dur, quick=False):
    """Every check that reads nothing but the finished video and the project folder, so a cloud worker can run it:
    format, T09 repeated shots, T24 hook cuts, T23 freezes, T19 tail, T33 length, T17 caption blocks, av_check and
    caption sync. Not here (they need this Mac): T13 tilt (Apple Vision), T06 banned list, T51 sale line and T49/T09
    plan checks (moment cards, sibling hooks)."""
    out = [format_line(W, H)]
    if not quick:
        with tempfile.TemporaryDirectory() as td:
            out += check_repeats(frames(f, 2, 160, td), 0.5) or ["PASS T09 no repeated shots found"]
    out += check_hook_cuts(f) + check_freezes(f, dur) + check_tail(f, dur) + check_length(dur) + check_caption_events(proj)
    return out + check_external(proj, f)


def load_media(path, f):
    """Media check lines measured elsewhere (the cloud worker) for THIS exact file, or None."""
    try:
        d = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return None
    lines = d.get("lines") if isinstance(d, dict) else None
    if not isinstance(lines, list) or not lines or d.get("fingerprint") != fingerprint(f) or d.get("master") != pathlib.Path(f).name:
        return None
    return d


def main():
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    proj = pathlib.Path(a[0]) if pathlib.Path(a[0]).exists() else ROOT / "projects" / a[0]
    proj = proj.resolve()
    f = proj / (a[a.index("--file") + 1] if "--file" in a else "MASTER.mp4")
    if not f.exists(): sys.exit(f"{f} not found")
    quick = "--quick" in a
    W, H, dur = probe(f)
    if "--media-json" in a:   # cloud worker: the video-only checks, as data (no PREFLIGHT.md, no taste rules needed)
        out = pathlib.Path(a[a.index("--media-json") + 1])
        print(f"preflight (video checks only) {proj.name}: {f.name} {W}x{H} {dur:.1f}s", flush=True)
        lines = media_lines(proj, f, W, H, dur, quick)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"master": f.name, "fingerprint": fingerprint(f), "duration": dur, "quick": quick, "lines": lines,
                                   "checked": f"{__import__('datetime').datetime.now():%Y-%m-%d %H:%M}"}, indent=1) + "\n")
        print("\n".join("  " + x for x in lines))
        fails = [x for x in lines if x.startswith("FAIL")]
        print(f"\nwrote {out}: {len(fails)} FAIL of {len(lines)} video checks (the Mac adds the tilt, banned-clip and plan checks)")
        sys.exit(1 if fails else 0)
    carried = load_media(a[a.index("--media-from") + 1], f) if "--media-from" in a else None
    if "--media-from" in a and carried is None:
        print("  (the cloud's video checks are missing or for another render: measuring everything here)")
    auto = [format_line(W, H)]
    print(f"preflight {proj.name}: {f.name} {W}x{H} {dur:.1f}s")
    plan = load_plan(proj)   # 2026-11-22: exact plan checks (T33 length, T51 sale line, T49 flash clips, T09/T06 reuse)
    if carried is not None:   # the video checks were measured in the cloud on this exact file: only this Mac's part runs
        if not quick:
            with tempfile.TemporaryDirectory() as td:
                pngs = frames(f, 1, 720, td); print(f"  OCR on {len(pngs)} frames ...", flush=True)
                auto += check_tilt(pngs, 1.0) or ["PASS T13 no tilted text found"]
        auto += [str(x) for x in carried["lines"][1:]]
        auto += check_banned(proj) + check_sale_line(proj, plan) + check_flash(proj, plan, f) + check_reuse(proj, plan)
        auto.append(f"INFO video and audio checks (repeats, hook cuts, freezes, tail, length, caption blocks, av_check, caption sync) "
                    f"were measured in the cloud on this exact file ({carried.get('checked')})")
    else:
        if not quick:
            with tempfile.TemporaryDirectory() as td:
                pngs = frames(f, 1, 720, td); print(f"  OCR on {len(pngs)} frames ...", flush=True)
                auto += check_tilt(pngs, 1.0) or ["PASS T13 no tilted text found"]
            with tempfile.TemporaryDirectory() as td:
                pngs = frames(f, 2, 160, td)
                auto += check_repeats(pngs, 0.5) or ["PASS T09 no repeated shots found"]
        auto += check_hook_cuts(f) + check_freezes(f, dur) + check_banned(proj) + check_tail(f, dur)
        auto += check_length(dur) + check_sale_line(proj, plan) + check_flash(proj, plan, f) + check_reuse(proj, plan) + check_caption_events(proj)
        print("  av_check / caption sync ...", flush=True)
        auto += check_external(proj, f)

    import taste_tags, feedback
    st = feedback.taste_stats(); R = taste_tags.rules()
    R = sorted(R, key=lambda r: -feedback.score(st[r["id"]]) if r["id"] in st else 0)
    L = [f"# PREFLIGHT {proj.name}", "", f"master: {f.name}", f"fingerprint: {fingerprint(f)}", f"checked: {__import__('datetime').datetime.now():%Y-%m-%d %H:%M}", "",
         "Answer every box: [x] = checked and it holds, [n/a] = not in this video. Add a few words where it matters.",
         "A FAIL blocks the Frame.io push until fixed (or 'override: <reason>' when the owner asked for exactly that).", "",
         "## Automatic checks", ""] + [f"- {x}" for x in auto] + ["", "## Owner taste rules (most repeated first)", ""]
    for r in R:
        s = st.get(r["id"])
        n_ads = len(s["ads"]) if s else 0
        L.append(f"- [ ] **{r['id']} {r['title']}** (raised on {n_ads} ads): {r['rule']}")
    notes = earlier_notes(proj)
    L += ["", f"## Earlier revisions on this ad and its batch ({len(notes)}): each must still be applied", ""]
    for r, k in notes:
        L.append(f"- [ ] #{r['id']} {r['ad']} ({r['ts'][:10]}): {k}")
    (proj / "PREFLIGHT.md").write_text("\n".join(L) + "\n")
    fails = [x for x in auto if x.startswith("FAIL")]
    warns = [x for x in auto if x.startswith("WARN")]
    print("\n".join("  " + x for x in auto))
    print(f"\nwrote {proj / 'PREFLIGHT.md'}: {len(fails)} FAIL, {len(warns)} WARN, {len(R)} taste rules + {len(notes)} earlier revisions to answer")
    print("Read the taste rules in feedback/OWNER_TASTE.md, answer every box, fix every FAIL, then push.")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
