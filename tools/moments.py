"""Moment cards: every clip in the BRoll / Footage library split into described moments, searchable by meaning.

Why: INDEX.csv has ONE line per clip, so rawedit's b-roll pick was a keyword match on a whole clip and the in-point was a
guess. Here each clip is cut into moments (start/end inside the clip, never across a hard cut), each moment gets a card
written by Claude Haiku from timestamped frame sheets (this session never sees frames), and the cards are embedded for
semantic search. Demo moments carry T05 take data: swipes_from (demo starts) / flip_at (result turned to camera) /
strand_at (result visible) / strand (result size) / complete.

Usage (PY = .venv/bin/python, from the repo root):
  moments.py build [--only <substr>] [--limit N] [--workers 6] [--force]   cuts + frame sheets + Haiku cards (resumable), then embed
  moments.py embed                                                       rebuild the vector index from the cards
  moments.py search "<what you need to see>" [--kind demo-take] [--product|--no-product] [--take] [--surface couch]
                    [--fits problem] [--no-face] [--n 12] [--json]
  moments.py show <moment id>                                            one card in full
  moments.py stats                                                       coverage, counts by kind, complete demo takes
  moments.py pick <project>                                              what `rawedit.py <project> broll` runs: beat intent
                                                                         (meaning + literal must-show) -> retrieve -> rerank

Moment id = "m:<first 10 chars of the Drive id>@<start s>", e.g. m:1QqNxFPXFg@17.0 . rawedit takes it anywhere a clip key
goes: `set-broll 3 m:1QqNxFPXFg@17.0` sets the clip, in-point (swipes_from for a demo take) and duration.

Data: footage/moments/cards/<fid>.json (one per clip), footage/moments/index.npz + index.json (vectors + flat cards).
Hard filters on every search: footage/BANNED_CLIPS.json ids and name patterns. Owner favourites (T06 ids in
feedback/OWNER_TASTE.md) get a boost; clips already used in many projects get a small fatigue penalty.
"""
import argparse, base64, math, concurrent.futures as cf, io, json, os, pathlib, re, subprocess, sys, tempfile, threading, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
from brand import BRAND
MD = ROOT / "footage" / "moments"
CARDS = MD / "cards"
BANNED = ROOT / "footage" / "BANNED_CLIPS.json"
TASTE = ROOT / "feedback" / "OWNER_TASTE.md"
EMB_MODEL = "BAAI/bge-base-en-v1.5"
QPFX = "Represent this sentence for searching relevant passages: "
VISION = "claude-haiku-5-5"
PLANNER = "claude-sonnet-5-5"
KINDS = ["demo-take", "product-other", "problem-mess", "failed-tool", "pet", "person-struggle", "person-talking",
         "product", "unboxing", "result-clean", "other"]
FITS = ["hook", "problem", "frustration", "failed-tool", "mechanism", "demo", "reveal", "result", "pet-love", "unboxing", "cta"]


def env():
    f = ROOT / ".env"
    if f.exists():
        for l in f.read_text().splitlines():
            if "=" in l and not l.startswith("#"):
                k, v = l.split("=", 1); os.environ.setdefault(k.strip(), v.strip())


def rawedit():
    import rawedit as r
    return r


def mid_of(fid, start): return f"m:{fid[:10]}@{float(start):.1f}"


# ---------------------------------------------------------------- model backends
# api = Anthropic API key in .env; cli = headless `claude -p` on the owner's Claude login (used when the API key has no
# credit). Images go to that subprocess only, never into the calling agent's context. MOMENTS_BACKEND=api|cli|auto.
# CLOUD 5.2/5.8: also local-cli|callback|token-cli|skip; optional CLAUDE_CALL_LOG metadata only.
BACKEND = {"use": os.environ.get("MOMENTS_BACKEND", "auto")}
CLI_MODEL = {VISION: "haiku", PLANNER: "sonnet"}


def _api_call(model_id, system, text, images=(), max_tokens=8000):
    env(); import anthropic
    content = []
    for k, jpg in enumerate(images):
        content += [{"type": "text", "text": f"image {k+1}"}, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpg).decode()}}]
    content.append({"type": "text", "text": text})
    r = anthropic.Anthropic().messages.create(model=model_id, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": content}])
    return "".join(getattr(b, "text", "") for b in r.content), r.usage.input_tokens, r.usage.output_tokens


def _cli_call(model_id, system, text, images=(), max_tokens=8000):
    with tempfile.TemporaryDirectory(prefix="moments_") as td:
        paths = []
        for k, jpg in enumerate(images):
            q = pathlib.Path(td) / f"image_{k+1}.jpg"; q.write_bytes(jpg); paths.append(str(q))
        prompt = system + "\n\n"
        if paths:
            prompt += ("First use the Read tool on each of these image files, in order (image 1 = the first):\n" + "\n".join(paths) + "\n\n")
        prompt += text + "\n\nAnswer with the JSON only, no other text."
        e = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_SIMPLE")}
        cmd = ["claude", "-p", prompt, "--model", CLI_MODEL.get(model_id, model_id), "--output-format", "json",
               "--allowedTools", "Read", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "",
               "--disable-slash-commands", "--no-session-persistence", "--max-turns", str(len(paths) + 4)]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=td, env=e, timeout=900)
        try: j = json.loads(r.stdout)
        except Exception: raise RuntimeError(f"claude cli failed ({r.returncode}): {(r.stderr or r.stdout)[-300:]}")
        if j.get("is_error"): raise RuntimeError(f"claude cli error: {str(j.get('result'))[:300]}")
        u = j.get("usage") or {}
        return j.get("result") or "", int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0)), int(u.get("output_tokens", 0))


def _legacy_llm(model_id, system, text, images=(), max_tokens=8000):
    """One model call with retries; returns (text, input tokens, output tokens). auto = API first, CLI once the key is dry."""
    last = None
    for attempt in range(5):
        use = BACKEND["use"]
        try:
            if use == "cli": return _cli_call(model_id, system, text, images, max_tokens)
            return _api_call(model_id, system, text, images, max_tokens)
        except Exception as ex:
            last = ex; msg = str(ex).lower()
            if use != "cli" and ("credit balance" in msg or "authentication" in msg or "api key" in msg):
                if os.environ.get("MOMENTS_BACKEND", "auto") == "api": raise
                if BACKEND["use"] != "cli":     # several threads can hit this at once: every one of them retries on the CLI
                    BACKEND["use"] = "cli"; print("  (Anthropic API key unusable: switching to the claude CLI backend)", flush=True)
                continue
            time.sleep(4 * (attempt + 1) + (20 if "rate" in msg or "overload" in msg else 0))
    raise last


def llm(model_id, system, text, images=(), max_tokens=8000):
    """Preserve legacy retries; new cloud modes fail closed with typed not_checked."""
    use = BACKEND["use"]
    log_path = os.environ.get("CLAUDE_CALL_LOG")
    extended = use in {"local-cli", "callback", "token-cli", "skip"}
    if not extended and not log_path:
        return _legacy_llm(model_id, system, text, images, max_tokens)
    # CLOUD 5.2/5.8: lazy import only; legacy defaults do not read cloud source.
    import claude_client as client
    started, status = time.monotonic(), "error"
    try:
        if not extended:
            result = _legacy_llm(model_id, system, text, images, max_tokens)
        else:
            content = []
            for k, jpg in enumerate(images):
                content += [{"type": "text", "text": f"image {k+1}"}, {"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpg).decode()}}]
            content.append({"type": "text", "text": text})

            def cli(**request):
                if request.pop("_token_cli", False):
                    return client._cli(**request, _token_cli=True)
                answer, i, o = _cli_call(model_id, system, text, images, max_tokens)
                return client._Resp(answer, i, o, "end_turn")

            r = client._cloud_llm().create(backend=use, cli=cli, model=model_id, max_tokens=max_tokens,
                                          system=system, messages=[{"role": "user", "content": content}])
            result = ("".join(getattr(b, "text", "") for b in r.content), r.usage.input_tokens, r.usage.output_tokens)
        status = "ok"
        return result
    except Exception as ex:
        if getattr(ex, "check_status", None) == "not_checked": status = "not_checked"
        raise
    finally:
        if log_path:
            active = use if extended else ("api" if BACKEND["use"] == "auto" else BACKEND["use"])
            client._log_call(log_path, {
                "model": client._log_label(model_id, "unspecified"), "purpose": "moments",
                "prompt_size": len(system) + len(text) + sum(len(f"image {k+1}") for k in range(len(images))),
                "image_count": len(images), "duration": round(time.monotonic() - started, 6),
                "backend": client._log_label(active, "unknown"), "status": status,
            })


def parse_json(txt):
    m = re.search(r"\{.*\}", txt, re.S)
    if not m: raise ValueError("no JSON in reply: " + txt[:200])
    return json.loads(m.group(0))


# ---------------------------------------------------------------- segmentation helpers
def scene_scores(f):
    """(times, scores) per frame at 320 px. A hard cut is an isolated spike; steady handheld motion stays < ~0.1."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(f), "-vf", "scale=320:-2,select='gte(scene,0)',metadata=print",
                        "-an", "-f", "null", "-"], capture_output=True, text=True)
    ts = [float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)]
    sc = [float(x) for x in re.findall(r"lavfi\.scene_score=([\d.]+)", r.stderr)]
    n = min(len(ts), len(sc)); return ts[:n], sc[:n]


def hard_cuts(ts, sc, thr=0.18):
    out = []
    for i, (t, s) in enumerate(zip(ts, sc)):
        if s <= thr or t < 0.15: continue
        nb = [x for x in sc[max(0, i - 3):i] + sc[i + 1:i + 4]]
        if not nb or s > 2.5 * (sorted(nb)[len(nb) // 2] + 0.01):
            if not out or t - out[-1] > 0.4: out.append(round(t, 2))
    return out


def motion(ts, sc, a, b):
    v = [s for t, s in zip(ts, sc) if a <= t < b]
    return round(sum(v) / len(v), 4) if v else 0.0


def step_for(dur): return 0.5 if dur <= 24 else 1.0 if dur <= 90 else 2.0


def sheets(f, dur, step, tile_w=200, cols=6, rows=4):
    """Frame every `step` s, tiled 6x4 with the time burned top-left. Returns list of (jpeg bytes, [times])."""
    from PIL import Image, ImageDraw, ImageFont
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-vf", f"fps={1/step},scale={tile_w}:-2", "-q:v", "4",
                        f"{td}/f_%05d.jpg"], check=True)
        frames = sorted(pathlib.Path(td).glob("f_*.jpg"))
        ims = []
        for k, p in enumerate(frames):
            t = round(k * step, 2)
            if t > dur: break
            im = Image.open(p).convert("RGB"); im.load(); ims.append((t, im))
    font = ImageFont.load_default()
    try: font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 18)
    except Exception: pass
    out, per = [], cols * rows
    for i in range(0, len(ims), per):
        chunk = ims[i:i + per]; tw, th = chunk[0][1].size
        S = Image.new("RGB", (cols * tw, -(-len(chunk) // cols) * th), (20, 20, 20)); d = ImageDraw.Draw(S)
        for j, (t, im) in enumerate(chunk):
            x, y = (j % cols) * tw, (j // cols) * th; S.paste(im, (x, y))
            d.rectangle([x, y, x + 62, y + 24], fill=(0, 0, 0)); d.text((x + 4, y + 3), f"{t:.1f}s", fill=(255, 230, 0), font=font)
        b = io.BytesIO(); S.save(b, "JPEG", quality=80); out.append((b.getvalue(), [t for t, _ in chunk]))
    return out


def speech_for(fid):
    """Words from an existing rawedit transcript, if this clip was ever an a-roll: [(start, end, word)]."""
    p = ROOT / "footage" / "transcripts" / f"{fid}.words.json"
    if not p.exists(): return []
    try:
        j = json.loads(p.read_text()); ws = j.get("words") or []
        return [(float(w.get("start", 0)), float(w.get("end", 0)), str(w.get("word", "")).strip()) for w in ws]
    except Exception: return []


# ---------------------------------------------------------------- Haiku card writer
CARD_SYS = f"""You log raw creator footage for an ad library for {BRAND['product']} ({BRAND['product_word']}: {BRAND['product_look']}).
How it really works: {BRAND['how_it_works']} A complete demo: {BRAND['complete_demo']} The problem the ads show: {BRAND['problem']}

You get timestamped frame sheets of ONE clip (the time is burned top-left of each tile) plus the list of hard cuts.
Split the clip into the MOMENTS an editor would use, and describe each one precisely. You only report what is visible."""

CARD_ASK = """Clip: {name}
Library note: {what}
Folder: {folder} | creator: {creator} | pet: {pet} | flags: {flags} | {dur:.1f}s, frame every {step}s
Hard cuts at: {cuts}
{speech}
Rules for moments:
- Cover every usable stretch; skip dead frames (camera on the floor, fumbling, black, blurred whip pans).
- A moment never crosses a hard cut. Length 1-8 s; a demo-take may run up to 14 s because it must stay ONE uncut take.
- start = the first tile where the moment's subject is ALREADY on screen (no lead-in). end = the last tile it still holds.
- demo-take = the product being used on camera. Fill "take": swipes_from (first tile of the demo action), flip_at (the product
  or result turned/shown to camera, or null), strand_at (the result clearly visible, or null), strand = how clear the result
  is: big|medium|thin|none, complete = true ONLY if the action, the show-to-camera and a visible result all happen inside this one moment.
- kind: one of {kinds}.
- fits: which ad beats it could illustrate, from {fits}. "problem" = the problem with no product; "failed-tool" = another
  tool or method failing; "reveal" = the product first shown; "result" = the visible result payoff.
- quality 3 = sharp, well lit, clearly readable at phone size; 2 = usable; 1 = poor.
Reply with JSON only:
{{"clip": "one line: what the whole clip is", "moments": [{{"start": s, "end": s, "kind": "...",
 "action": "12-25 words, concrete: who does what to what, where",
 "surface": "what the action happens on, e.g. couch | carpet | bed | car seat | clothes | table | product only | hand | floor | none ...",
 "colour": "main surface colour", "room": "living room|bedroom|car|stairs|kitchen|bathroom|outdoor|studio|unknown",
 "hair": "none|light|medium|heavy" (how much of the problem is visible), "product_visible": true, "pet_visible": false, "pet": "dog breed / cat colour / none",
 "person": "none|hands|body|face", "looks_at_camera": false, "talking": false,
 "shot": "extreme-close|close|medium|wide", "camera": "static|handheld|moving|shaky",
 "product_brand": "ours|other|unreadable|none" (ours = the product above; other = a competitor's product),
 "on_screen_text": false, "other_tool": "none | the other tool or method shown",
 "take": {{"swipes_from": s, "flip_at": s, "strand_at": s, "strand": "big", "complete": true}} or null,
 "mood": "2-4 words", "fits": ["demo"], "quality": 3, "issues": "none | blur | shaky | dark | text on screen | ..."}}]}}"""


def describe(row, f, force=False):
    out = CARDS / f"{row['fid']}.json"
    if out.exists() and not force: return json.loads(out.read_text()), 0, 0
    r = rawedit(); dur, w, h = r.probe(f)
    ts, sc = scene_scores(f); cuts = hard_cuts(ts, sc); step = step_for(dur)
    sh = sheets(f, dur, step)
    sp = speech_for(row["fid"])
    speech = ("Creator says (time: words): " + " ".join(f"{a:.1f}:{x}" for a, _, x in sp)[:2500]) if sp else ""
    labels = "\n".join(f"image {k+1}: frame sheet {k+1}/{len(sh)}, tiles {tl[0]:.1f}s-{tl[-1]:.1f}s" for k, (_, tl) in enumerate(sh))
    ask = labels + "\n\n" + CARD_ASK.format(name=row["New file name"], what=row["What you see"], folder=row["Folder"],
                    creator=row["Creator"], pet=row["Pet"], flags=row["Flags"] or "none", dur=dur, step=step,
                    cuts=", ".join(f"{c:.1f}s" for c in cuts) or "none", speech=speech, kinds=", ".join(KINDS), fits=", ".join(FITS))
    txt, ti, to = llm(VISION, CARD_SYS, ask, [jpg for jpg, _ in sh], 12000)
    j = parse_json(txt)
    ms = []
    for x in j.get("moments", []):
        try: a, b = max(0.0, float(x["start"])), min(dur, float(x["end"]))
        except Exception: continue
        b = max(b, min(dur, a + step))          # end is the last tile that holds; it lasts one more step
        if b - a < 0.6: continue
        for c in cuts:                           # never across a hard cut: clip to the side holding most of it
            if a + 0.1 < c < b - 0.1: a, b = (a, c) if c - a >= b - c else (c, b)
        x["start"], x["end"] = round(a, 2), round(b, 2)
        x["motion"] = motion(ts, sc, a, b)
        if sp: x["says"] = " ".join(wd for s0, s1, wd in sp if s0 < b and s1 > a)[:300]
        x["id"] = mid_of(row["fid"], a); ms.append(x)
    card = {"fid": row["fid"], "name": row["New file name"], "folder": row["Folder"], "creator": row["Creator"], "type": row["Type"],
            "index_what": row["What you see"], "index_quality": row["Quality (1-3)"], "flags": row["Flags"], "dur": round(dur, 2),
            "w": w, "h": h, "cuts": cuts, "step": step, "clip": j.get("clip", ""), "moments": ms, "model": VISION,
            "built": time.strftime("%Y-%m-%d %H:%M")}
    card["backend"] = BACKEND["use"]
    out.write_text(json.dumps(card, indent=1))
    return card, ti, to


# ---------------------------------------------------------------- banned / favourites / usage
import banned as _banned   # tools/banned.py: one ban list reader for moments, rawedit, preflight and cloud/ctl.py


def banned():
    return _banned.ids_and_patterns(ROOT)


def is_banned(fid, name, ids=None, pats=None):
    return _banned.basic(fid, name, ids, pats, ROOT)


def window_ban(m, query=""):
    """(drop, note) for a moment vs footage/BANNED_CLIPS.json banned windows. A hard window drops it. A line-scoped one
    ("banned for 'embedded hair' lines") drops it when the query names that kind of line, else it only ranks lower."""
    note = ""
    for h in _banned.window_hits(m["fid"], m["start"], m["end"], ROOT):
        if h["hard"]: return True, h["reason"]
        words = re.findall(r"[a-z]+", " ".join(re.findall(r"'([^']+)'", h["scope"] or "")) or (h["scope"] or "").lower())
        words = [w for w in words if w not in ("for", "as", "a", "an", "the", "lines", "line", "shot", "shots", "on", "in")]
        if words and all(w in query.lower() for w in words): return True, h["reason"]
        note = f"window banned {h['scope']}"
    return False, note


FAV_T06, FAV_PICKED, FAV_APPROVED, FAV_CAP = 0.06, 0.04, 0.03, 0.06   # score boosts (sims are ~0.6-0.85)
LOG = ROOT / "feedback" / "log.jsonl"
_LINK = re.compile(r"drive\.google\.com/(?:file/d/|open\?id=)(1[A-Za-z0-9_-]{24,})")
_NEG = re.compile(r"\b(never|don'?t|do not|not good|bad|banned?|weak|remove|instead of)\b", re.I)


def t06_favourites():
    """Drive-id prefixes the owner named as his strongest clips in T06 (read live, so his edits flow in)."""
    if not TASTE.exists(): return []
    line = next((l for l in TASTE.read_text().splitlines() if "**T06" in l), "")
    return re.findall(r"\b(1[A-Za-z0-9_-]{8,})\b", line)


def owner_picks(log=None):
    """{fid: [note ids]}: Drive FILE links the owner pasted in his notes as the clip to use ("change this clip to this <link>"),
    plus any Drive id in a like-row. Folder links and links right after a negative word ("never", "don't") are left out."""
    out = {}
    f = pathlib.Path(log) if log else LOG
    if not f.exists(): return out
    for ln in f.read_text().splitlines():
        try: r = json.loads(ln)
        except ValueError: continue
        t = str(r.get("text") or "")
        like = r.get("kind") == "like" or r.get("status") == "like"
        hits = [(m.group(1), m.start()) for m in _LINK.finditer(t)]
        if like: hits += [(m.group(0), m.start()) for m in re.finditer(r"\b1[A-Za-z0-9_-]{24,}\b", t)]
        for fid, at in hits:
            if _NEG.search(t[max(0, at - 60):at]): continue
            out.setdefault(fid, []).append(r.get("id"))
    return out


def approved_projects(log=None):
    """Projects the owner approved: plan.json "locked": true, an approval row in feedback/log.jsonl (status approved or
    decision approve), or a Frame.io folder cleaned (frameio.py clean runs once the ad is approved, FEEDBACK_LOOP.md)."""
    ok = set()
    f = pathlib.Path(log) if log else LOG
    if f.exists():
        for ln in f.read_text().splitlines():
            try: r = json.loads(ln)
            except ValueError: continue
            if r.get("status") == "approved" or r.get("decision") == "approve": ok.add(str(r.get("ad")))
    for p in (ROOT / "projects").glob("*/plan.json"):
        try:
            if json.loads(p.read_text()).get("locked"): ok.add(p.parent.name)
        except (ValueError, OSError): pass
    for p in (ROOT / "projects").glob("*/frameio.json"):
        try:
            if json.loads(p.read_text()).get("cleaned"): ok.add(p.parent.name)
        except (ValueError, OSError): pass
    return ok


def plan_windows(plan):
    """[(fid or fid10 prefix, in, out)] of every library clip window a rawedit plan shows (shots + b-roll + split)."""
    out = []
    for w in _banned.shot_windows(plan):
        fid = _banned.fid_of(w["src"])
        if fid: out.append((fid, w["in"], w["out"]))
    for b in plan.get("beats") or []:
        br = b.get("broll") if isinstance(b, dict) else None
        if not isinstance(br, dict): continue
        try: a = float(br.get("in") or 0); d = float(br.get("dur") or 0) * float(br.get("speed") or 1.0)
        except (TypeError, ValueError): continue
        for x, a_ in ((br, a), (br.get("split"), None)):
            if not isinstance(x, dict): continue
            fid = _banned.fid_of(x.get("fid") or x.get("file") or "")
            if a_ is None:
                try: a_ = float(x.get("in") or 0)
                except (TypeError, ValueError): a_ = 0.0
            if fid: out.append((fid, a_, a_ + d))
    return out


def approved_windows(log=None):
    """{fid prefix (10): [(in, out, ad)]} clip windows inside owner-approved ads (see approved_projects)."""
    out = {}
    for ad in sorted(approved_projects(log)):
        p = ROOT / "projects" / ad / "plan.json"
        if not p.exists(): continue
        try: plan = json.loads(p.read_text())
        except ValueError: continue
        for fid, a, b in plan_windows(plan):
            out.setdefault(fid[:10], []).append((a, b, ad))
    return out


def favourites(log=None):
    """Every positive-taste source for search: t06 = Drive-id prefixes typed into the T06 rule; picked = {fid: note ids}
    the owner pasted as the replacement to use; approved = {fid10: [(in, out, ad)]} windows in approved ads."""
    return {"t06": t06_favourites(), "picked": owner_picks(log), "approved": approved_windows(log)}


def fav_boost(m, fav, uses=0):
    """(boost, why) for one moment. T06 keeps its +0.06. The newer sources (owner-pasted clip +0.04, a window from an
    approved ad +0.03) fade to 0 by the clip's 3rd use, so they never outweigh the fatigue penalty, and the total is capped
    at the T06 boost. Bans are filtered before scoring, so no boost can bring a banned clip or window back."""
    fid = m["fid"]; why = []
    t06 = any(fid.startswith(f) for f in fav.get("t06") or [])
    if t06: why.append("T06")
    extra = 0.0
    if fid in (fav.get("picked") or {}): extra += FAV_PICKED; why.append("picked")
    if any(a < m["end"] - 0.3 and m["start"] < b - 0.3 for a, b, _ in (fav.get("approved") or {}).get(fid[:10], [])):
        extra += FAV_APPROVED; why.append("approved")
    extra *= max(0.0, 1 - uses / 3)
    return min(FAV_CAP, (FAV_T06 if t06 else 0.0) + extra), why


def _plan_fids(plan, known=()):
    """Full Drive ids a plan really shows: every "fid" key (outside suggest/intent, which are only candidates) plus
    voiceover-mode shots[].src / hook_src paths and m:<fid10> moment ids (resolved against the known card ids)."""
    out = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("suggest", "intent"): continue
                if k == "fid" and isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]{20,}", v): out.add(v)
                else: walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(plan)
    for s in plan.get("shots") or []:
        if not isinstance(s, dict): continue
        for key in ("src", "hook_src"):
            fid = _banned.fid_of(s.get(key) or "")
            if not fid: continue
            if len(fid) < 20: fid = next((k for k in known if k.startswith(fid)), None)
            if fid: out.add(fid)
    return out


def usage():
    """fid -> number of distinct ads (hook variants -h2/-h3 count once) whose plan.json uses the clip, as a-roll, b-roll
    (fid keys) or a voiceover-mode shot (src path / moment id). Suggestions a plan did not use are not counted."""
    cnt = {}
    known = [p.stem for p in CARDS.glob("*.json")] if CARDS.exists() else []
    for p in (ROOT / "projects").glob("*/plan.json"):
        base = re.sub(r"-h\d+$", "", p.parent.name)
        try: plan = json.loads(p.read_text())
        except Exception: continue
        if not isinstance(plan, dict): continue
        for fid in _plan_fids(plan, known):
            cnt.setdefault(fid, set()).add(base)
    return {k: len(v) for k, v in cnt.items()}


# ---------------------------------------------------------------- index
def card_text(c, m):
    tk = m.get("take") or {}
    parts = [m.get("kind", ""), m.get("action", ""), f"surface {m.get('colour','')} {m.get('surface','')} in the {m.get('room','')}",
             f"hair {m.get('hair','')}", "product visible" if m.get("product_visible") else "no product",
             f"pet {m.get('pet','')}" if m.get("pet_visible") else "", f"other tool {m['other_tool']}" if m.get("other_tool") not in (None, "", "none") else "",
             f"strand {tk.get('strand')}" if tk else "", "competitor product" if m.get("product_brand") == "other" else "", f"mood {m.get('mood','')}", "fits " + " ".join(m.get("fits", [])),
             f"{m.get('shot','')} shot", c.get("index_what", ""), (m.get("says") or "")[:120]]
    return ". ".join(p for p in parts if p and p.strip())


_model = None
_lock = threading.Lock()


def model():
    global _model
    with _lock:
        if _model is None:
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(EMB_MODEL)
    return _model


def embed_all():
    import numpy as np
    flat = []
    for p in sorted(CARDS.glob("*.json")):
        c = json.loads(p.read_text())
        for m in c["moments"]:
            flat.append({**{k: c[k] for k in ("fid", "name", "folder", "creator", "type", "flags", "dur", "w", "h")}, **m,
                         "text": card_text(c, m)})
    if not flat: sys.exit("no cards yet: run `moments.py build`")
    v = model().encode([x["text"] for x in flat], batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    np.savez_compressed(MD / "index.npz", v=v.astype("float32"))
    (MD / "index.json").write_text(json.dumps({"model": EMB_MODEL, "built": time.strftime("%Y-%m-%d %H:%M"), "moments": flat}))
    print(f"indexed {len(flat)} moments from {len(list(CARDS.glob('*.json')))} clips -> {MD/'index.npz'}")


def load_index():
    import numpy as np
    if not (MD / "index.json").exists(): return None, None
    j = json.loads((MD / "index.json").read_text()); v = np.load(MD / "index.npz")["v"]
    return j["moments"], v


def get_moment(mid):
    ms, _ = load_index()
    if ms is None: sys.exit("no moment index: run `moments.py build`")
    mid = mid if mid.startswith("m:") else "m:" + mid
    hit = [m for m in ms if m["id"] == mid]
    if not hit:   # tolerate a rounded start
        fp, _, st = mid[2:].partition("@")
        cand = [m for m in ms if m["fid"].startswith(fp)]
        if st: cand.sort(key=lambda m: abs(m["start"] - float(st)))
        hit = cand[:1]
    if not hit: sys.exit(f"no moment {mid}")
    return hit[0]


def search(query, n=12, kind=None, product=None, take=False, surface=None, fits=None, no_face=False, exclude=(),
           min_quality=2, min_len=0.0, _cache={}):
    """Semantic search + owner-rule scoring. product: True = must show the product, False = must not (T31 before the reveal)."""
    import numpy as np
    if "ms" not in _cache:
        _cache["ms"], _cache["v"] = load_index()
        _cache["ban"] = banned(); _cache["fav"] = favourites(); _cache["use"] = usage()
        cr = MD / "clip_results.json"   # tools/results.py: spend of our live ads that used each clip
        _cache["mkt"] = json.loads(cr.read_text()) if cr.exists() else {}
        _cache["flags"] = shot_flags()
    ms, V = _cache["ms"], _cache["v"]
    if ms is None: sys.exit("no moment index: run `moments.py build`")
    ids, pats = _cache["ban"]; fav = _cache["fav"]; use = _cache["use"]
    q = model().encode([QPFX + query], normalize_embeddings=True)[0]
    sims = V @ q; out = []
    for i in np.argsort(-sims)[:600]:
        m = ms[int(i)]
        if is_banned(m["fid"], m["name"], ids, pats) or m["fid"] in exclude: continue
        wdrop, wnote = window_ban(m, query)
        if wdrop: continue                                           # owner-banned stretch of this clip (BANNED_CLIPS windows)
        if int(m.get("quality") or 2) < min_quality: continue
        if m["end"] - m["start"] < min_len: continue
        if kind and m.get("kind") != kind: continue
        if product is True and not m.get("product_visible"): continue
        if product is False and m.get("product_visible"): continue
        if take and not (m.get("take") or {}).get("complete"): continue
        if surface and surface.lower() not in (m.get("surface") or "").lower(): continue
        if fits and fits not in (m.get("fits") or []): continue
        if no_face and m.get("person") == "face": continue
        s = float(sims[i]) + 0.03 * (int(m.get("quality") or 2) - 2)
        tk = m.get("take") or {}
        if tk.get("complete"): s += 0.03 + (0.03 if tk.get("strand") == "big" else 0)
        if tk and tk.get("strand") == "thin": s -= 0.06            # owner bans thin-strand clips on sight (T06)
        fb, fwhy = fav_boost(m, fav, use.get(m["fid"], 0)); s += fb   # T06 +0.06; owner-pasted / approved-ad clips (fade with use)
        if wnote: s -= 0.06                                          # banned only for another kind of line
        if m.get("on_screen_text"): s -= 0.1
        if m.get("product_brand") == "other": s -= 0.03              # competitor product on screen: usable, needs a blur
        if m.get("camera") == "shaky": s -= 0.05
        if m.get("looks_at_camera") and "problem" in (m.get("fits") or []): s -= 0.04   # T38
        if m["w"] > m["h"]: s -= 0.04                                # landscape gets cropped hard
        s -= 0.02 * min(use.get(m["fid"], 0), 5)                     # fatigue: used in many ads already
        fl = [f for f in _cache["flags"].get(m["fid"], ()) if f["t"] is None or m["start"] <= f["t"] <= m["end"]]
        if fl: s -= 0.12                                             # shot_check.py found this window wrong for its card
        mk = _cache["mkt"].get(m["fid"])
        if mk and mk.get("spend", 0) >= 300: s += min(0.05, 0.015 * math.log10(1 + mk["spend"] / 100))   # in an ad Meta spent on
        out.append({**m, "score": round(s, 4), "sim": round(float(sims[i]), 4), "uses": use.get(m["fid"], 0),
                    "market_spend": (mk or {}).get("spend", 0),
                    "fav": bool(fwhy), "fav_why": fwhy, "flagged": "; ".join([f["issue"] for f in fl] + ([wnote] if wnote else []))[:160]})
    out.sort(key=lambda x: -x["score"]); return out[:n]


def shot_flags():
    """footage/moments/flags.jsonl: clip windows a pre-render shot check (tools/shot_check.py) found wrong for what their
    card says, e.g. burned-in graphic, dog face on a hair line. {fid: [{t, issue}]}; t None = the whole clip."""
    out, f = {}, MD / "flags.jsonl"
    if f.exists():
        for ln in f.read_text().splitlines():
            try:
                d = json.loads(ln)
                out.setdefault(d["fid"], []).append({"t": d.get("t"), "issue": d.get("issue", "")})
            except (ValueError, KeyError):
                continue
    return out


def line(m):
    tk = m.get("take") or {}
    t = (f" take: swipes {tk.get('swipes_from')} flip {tk.get('flip_at')} strand {tk.get('strand_at')} ({tk.get('strand')}"
         f"{', COMPLETE' if tk.get('complete') else ''})") if tk else ""
    return (f"{m['id']:22s} {m['start']:5.1f}-{m['end']:5.1f}s q{m.get('quality')} [{m.get('kind')}] {m.get('action','')[:90]}"
            f" | {m.get('colour','')} {m.get('surface','')}, {m.get('room','')}{t}"
            + (f" | FAV {'+'.join(m.get('fav_why') or [])}" if m.get('fav') else '') + (f" | used in {m['uses']} ads" if m.get("uses") else "") +
            f" | {m['name'][:60]}" + (f" | FLAGGED: {m['flagged']}" if m.get("flagged") else ""))


# ---------------------------------------------------------------- beat intent + rerank (used by rawedit broll)
INTENT_SYS = f"""You are the storyboard layer of an ad editor for {BRAND['product']}. For each line of the script you decide what the viewer
must SEE. Two layers, both required:
1. literal: the concrete thing the line names (surface, object, tool, person, place). Owner rule T08: b-roll matches the line
   literally: car clips only on car lines, clothes only when clothes are said, a rug on a rug line, the problem itself on
   problem lines (not a cute face), the failing tool on its own line.
2. meaning: what the line does emotionally (embarrassment, frustration, relief, proof, curiosity) so the pick also FEELS right.
Owner rules: T31 the product is never shown before the line that reveals it (product = forbidden before the reveal; on and
after the reveal it is allowed or required). T05 a demo shot is one uncut take: {BRAND['complete_demo']} T12 failed tools
look real and actually fail. T25 real movement, never a static stare. T38 people in problem shots work on the mess, not the
camera. T09 never the same clip, room or angle twice in one ad. A line about the creator herself (I, my story, a reaction)
may stay on the creator: then needs_broll=false."""

INTENT_ASK = """Script (one beat per line, with the beat duration). The a-roll creator is {creator} ({pet}).
{beats}
Reply JSON only: {{"reveal_beat": n or null, "beats": [{{"n": 1, "needs_broll": true, "meaning": "...", "emotion": "...",
"literal": "must show: ...", "query": "one sentence describing the ideal shot, concrete and visual", "kind": "{kinds}",
"product": "forbidden|allowed|required", "fits": "{fits}"}}]}}"""

RERANK_ASK = """Pick b-roll moments for each beat. Candidates were found by meaning; you check them against the literal
must-show, the owner rules and each other. Rules: never the same source clip twice in this ad (T09/T39), vary rooms and
angles across beats, demo takes must be complete (action + show + result) when the beat demos the product (T05), the
product never before the reveal beat (T31), a moment shorter than the beat is fine up to 1.3x speed-up, otherwise say "two clips"
(C006: b-roll over ~3 s should be two clips). Prefer FAV clips and quality 3. If nothing fits a beat, return no picks for it
(the creator stays on camera) rather than a wrong clip.

{blocks}

Reply JSON only: {{"beats": [{{"n": 1, "picks": [{{"id": "m:...", "in": seconds in the source, "dur": seconds to use,
"why": "8-15 words: literal match + feeling"}}]}}]}}  Give up to 3 picks per beat, best first, and make the FIRST picks of all
beats a valid set together (no clip reused)."""


def _claude(system, prompt, max_tokens=8000):
    txt, _, _ = llm(PLANNER, system, prompt, (), max_tokens)
    return parse_json(txt)


def pick(proj, plan, verbose=True):
    """Fill beat.intent + beat.suggest (moment ids with in/dur/why) for every beat of a rawedit plan."""
    beats = plan["beats"]; aroll = plan.get("aroll") or {}
    mine = aroll.get("fid")
    txt = "\n".join(f"{b['n']}. ({b.get('dur', 0):.1f}s) {b['vo']}" for b in beats)
    it = _claude(INTENT_SYS, INTENT_ASK.format(creator=aroll.get("creator", "voiceover"), pet=aroll.get("pet", "customer"),
                 beats=txt, kinds="|".join(KINDS), fits="|".join(FITS)))
    reveal = it.get("reveal_beat")
    by_n = {x["n"]: x for x in it.get("beats", [])}
    blocks = [f"reveal_beat = {reveal}"]
    cand = {}
    for b in beats:
        x = by_n.get(b["n"]); b["intent"] = x
        if not x or not x.get("needs_broll", True):
            blocks.append(f"BEAT {b['n']} ({b.get('dur',0):.1f}s): \"{b['vo']}\" -> stays on the creator (no b-roll needed)"); continue
        g = {"forbidden": False, "required": True}.get(x.get("product"))
        if reveal and b["n"] < int(reveal): g = False
        q = f"{x.get('query','')} {x.get('literal','')}"
        hits = search(q, n=14, product=g, exclude={mine} if mine else ())
        if x.get("kind") == "demo-take":
            seen = {h["id"] for h in hits}
            hits += [h for h in search(q, n=8, product=True, take=True, exclude={mine} if mine else ()) if h["id"] not in seen]
        cand[b["n"]] = {h["id"]: h for h in hits}
        rows = "\n".join(f"  {h['id']} | {h['end']-h['start']:.1f}s ({h['start']}-{h['end']}) | q{h.get('quality')} | {h.get('kind')} | "
                         f"{h.get('action','')} | {h.get('colour','')} {h.get('surface','')} in {h.get('room','')} | shot {h.get('shot')} "
                         f"{h.get('camera')} | product {'yes' if h.get('product_visible') else 'no'}"
                         + (f" | take {json.dumps(h['take'])}" if h.get("take") else "")
                         + (" | competitor product visible (blur it)" if h.get("product_brand") == "other" else "") + (" | FAV" if h.get("fav") else "")
                         + (f" | used in {h['uses']} ads" if h.get("uses") else "") + f" | clip {h['fid'][:10]}" for h in hits)
        blocks.append(f"BEAT {b['n']} ({b.get('dur',0):.1f}s): \"{b['vo']}\"\n  literal: {x.get('literal')}\n  meaning: {x.get('meaning')} "
                      f"({x.get('emotion')})\n  product: {'forbidden' if g is False else x.get('product')}\n  candidates:\n{rows or '  (none)'}")
    rr = _claude("You are a senior UGC ad editor choosing b-roll. JSON only.", RERANK_ASK.format(blocks="\n\n".join(blocks)), 6000)
    picks = {x["n"]: x.get("picks", []) for x in rr.get("beats", [])}
    for b in beats:
        sug = []
        for p in picks.get(b["n"], []):
            h = cand.get(b["n"], {}).get(p.get("id"))
            if not h: continue
            tk = h.get("take") or {}
            src_in = float(p.get("in", tk.get("swipes_from") or h["start"]))
            src_in = min(max(src_in, h["start"]), h["end"] - 0.5)
            sug.append({"mid": h["id"], "fid": h["fid"], "name": h["name"], "in": round(src_in, 2),
                        "dur": round(float(p.get("dur") or b.get("dur", 2)), 2), "len": round(h["end"] - src_in, 2),
                        "what": h.get("action", ""), "why": p.get("why", ""), "q": h.get("quality"), "score": h["score"],
                        "take": tk or None, "sec": h["dur"], "brand": h.get("product_brand")})
        b["suggest"] = sug
    if verbose:
        print(f"reveal beat: {reveal}")
        for b in beats:
            x = b.get("intent") or {}
            print(f"\nbeat {b['n']} ({b.get('dur',0):.1f}s): {b['vo'][:80]}")
            if x: print(f"   intent: {x.get('literal','')} | {x.get('meaning','')} ({x.get('emotion','')}) | product {x.get('product')}")
            for s in b["suggest"]:
                print(f"   {s['mid']}  in {s['in']}s use {s['dur']}s (moment has {s['len']}s)  q{s['q']}  {s['what'][:70]}\n      why: {s['why']}")
            if not b["suggest"]: print("   (creator on camera)")
    return plan


# ---------------------------------------------------------------- CLI
def build(a):
    env()
    r = rawedit(); rows = [x for x in r.index_rows()]
    ids, pats = banned()
    rows = [x for x in rows if not is_banned(x["fid"], x["New file name"], ids, pats)]
    if a.only: rows = [x for x in rows if a.only.lower() in (x["New file name"] + x["fid"] + x["Folder"]).lower()]
    todo = [x for x in rows if a.force or not (CARDS / f"{x['fid']}.json").exists()]
    if a.limit: todo = todo[:a.limit]
    CARDS.mkdir(parents=True, exist_ok=True)
    print(f"{len(rows)} clips in scope (banned skipped), {len(todo)} to describe")
    tot = [0, 0, 0]; errs = []
    def one(row):
        f = r.RAW / f"{row['fid']}{row['ext']}"
        if not f.exists() or f.stat().st_size < 1000: f = r.fetch(row)
        return describe(row, f, a.force)
    with cf.ThreadPoolExecutor(a.workers) as ex:
        fut = {ex.submit(one, row): row for row in todo}
        for k, fu in enumerate(cf.as_completed(fut), 1):
            row = fut[fu]
            try:
                c, ti, to = fu.result(); tot[0] += ti; tot[1] += to; tot[2] += len(c["moments"])
                print(f"[{k}/{len(todo)}] {len(c['moments']):2d} moments  {row['New file name'][:70]}", flush=True)
            except Exception as e:
                errs.append((row["New file name"], str(e)[:160])); print(f"[{k}/{len(todo)}] ERROR {row['New file name'][:60]}: {str(e)[:160]}", flush=True)
    print(f"done: {tot[2]} moments, {tot[0]:,} input / {tot[1]:,} output tokens ({VISION} via {BACKEND['use']}), {len(errs)} errors")
    for n, e in errs: print("  ERR", n, e)
    if list(CARDS.glob("*.json")): embed_all()


# ---------------------------------------------------------------- library sync (local clips + INDEX rows with no card)
EXTRA = MD / "catalog_extra.csv"   # additive catalogue: Drive clips in footage/raw that the footage INDEX.csv lacks
ORG = pathlib.Path(os.environ.get("FOOTAGE_INDEX") or ROOT / "footage" / "INDEX.csv").parent   # folder that holds INDEX.csv
BROLL_FOLDER = os.environ.get("BROLL_DRIVE_FOLDER", "")   # Drive folder id of your raw footage library (for `sync --drive`)
DRIVE_ACCOUNT = os.environ.get("COMPOSIO_DRIVE_ACCOUNT", "")   # optional composio account name for Google Drive
CARD_SEC_WALL, CARD_WORKERS = 15.0, 6   # measured: build 2026-11-16 carded 268 clips 16:01-17:08 with 6 workers (CLI), fetches included
COLS = ["Folder", "New file name", "What you see", "Creator says (if talking)", "Type", "Pet", "Quality (1-3)", "Flags", "Creator",
        "Seconds", "Resolution", "MB", "Source / original file name", "Link"]


def extra_rows():
    """Rows of footage/moments/catalog_extra.csv in INDEX shape (+ fid, ext)."""
    if not EXTRA.exists(): return []
    import csv
    rows = list(csv.DictReader(open(EXTRA)))
    for r in rows:
        r["fid"] = r["Link"].split("/d/")[1].split("/")[0]
        r["ext"] = pathlib.Path(r["New file name"]).suffix.lower() or ".mp4"
    return rows


def known_names():
    """fid -> Drive file name from the organize tool's own upload logs (extra1111/done.json, f20_after.json)."""
    out = {}
    for f in (ORG / "extra1111" / "done.json", ORG / "extra1111" / "f20_after.json"):
        try: j = json.loads(f.read_text())
        except (OSError, ValueError): continue
        for v in (j.values() if isinstance(j, dict) else j):
            if isinstance(v, dict) and v.get("id") and v.get("name"): out.setdefault(v["id"], v["name"])
    return out


def _probe(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(f)],
                       capture_output=True, text=True)
    try:
        j = json.loads(r.stdout or "{}"); v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
        return float(j.get("format", {}).get("duration") or 0), v.get("width"), v.get("height")
    except (ValueError, TypeError):
        return 0.0, None, None


def drive_listing(runner=None, root=BROLL_FOLDER):
    """READ-ONLY listing of every video under Drive BRoll / Footage, with composio
    GOOGLEDRIVE_FIND_FILE (account COMPOSIO_DRIVE_ACCOUNT if set). Banned Drive folders are not entered. [{id, name, size, path, ...}]"""
    run = runner or (lambda d: subprocess.run(["composio", "execute", "GOOGLEDRIVE_FIND_FILE"] + (["--account", DRIVE_ACCOUNT] if DRIVE_ACCOUNT else []) + ["-d", json.dumps(d)],
                                              capture_output=True, text=True, timeout=300).stdout)
    skip = {f.lower() for f in _banned.load(ROOT)["folders"]}
    out = []

    def find(q, page=None):
        d = {"q": q, "fields": "nextPageToken,files(id,name,mimeType,size,parents,videoMediaMetadata)", "pageSize": 1000,
             "supportsAllDrives": True, "includeItemsFromAllDrives": True}
        if page: d["pageToken"] = page
        j = json.loads(run(d) or "{}")
        if not j.get("successful"): raise RuntimeError(f"composio GOOGLEDRIVE_FIND_FILE failed: {str(j)[:200]}")
        if j.get("storedInFile"): j = json.loads(pathlib.Path(j["outputFilePath"]).read_text())
        data = j.get("data", j)
        return data.get("files", []), data.get("nextPageToken")

    def walk(fid, path):
        page = None
        while True:
            files, page = find(f"'{fid}' in parents and trashed = false", page)
            for f in files:
                if f.get("mimeType") == "application/vnd.google-apps.folder":
                    if f.get("name", "").lower() not in skip: walk(f["id"], f"{path}/{f['name']}")
                elif str(f.get("mimeType", "")).startswith("video/"):
                    out.append({**f, "path": path})
            if not page: break
    walk(root, "")
    return out


def sync_report(drive=None):
    """What `sync` would do: (i) local Drive clips not in INDEX or the extra catalogue, (ii) catalogued clips with no card,
    (iii) Drive videos not downloaded (only with a drive listing). Nothing is written or fetched."""
    r = rawedit(); index = r.index_rows(); ids, pats = banned()
    extra = extra_rows(); cat = {x["fid"]: x for x in index + extra}
    names = known_names(); cards = {p.stem for p in CARDS.glob("*.json")} if CARDS.exists() else set()
    local = {}
    for f in sorted(r.RAW.iterdir()) if r.RAW.exists() else []:
        if f.is_file() and f.suffix.lower() in (".mp4", ".mov", ".m4v") and _banned.DRIVE_ID.fullmatch(f.stem) and f.stat().st_size > 1000:
            local.setdefault(f.stem, f)
    new_local = []
    for fid, f in local.items():
        if fid in cat or fid in ids: continue
        dur, w, h = _probe(f)
        nm = names.get(fid) or f"{fid}{f.suffix.lower()}"
        if is_banned(fid, nm, ids, pats): continue
        new_local.append({"fid": fid, "file": f, "name": nm, "dur": dur, "w": w, "h": h, "mb": f.stat().st_size / 1e6, "named": fid in names})
    uncarded = [x for x in index + extra if x["fid"] not in cards and not is_banned(x["fid"], x["New file name"], ids, pats)]
    banned_uncarded = sum(1 for x in index + extra if x["fid"] not in cards and is_banned(x["fid"], x["New file name"], ids, pats))
    on_drive = []
    if drive is not None:
        for d in drive:
            if d["id"] in cat or d["id"] in local or is_banned(d["id"], d.get("name"), ids, pats): continue
            on_drive.append(d)
    def secs(x):
        try: return float(x.get("Seconds") or 0)
        except ValueError: return 0.0
    to_card = [(x["fid"], x["dur"]) for x in new_local] + [(x["fid"], secs(x)) for x in uncarded] + \
              [(d["id"], int((d.get("videoMediaMetadata") or {}).get("durationMillis") or 0) / 1000) for d in on_drive]
    images = sum(math.ceil((d / step_for(d) + 1) / 24) if d else 1 for _, d in to_card)
    fetch_mb = sum(float(x.get("MB") or 0) for x in uncarded if not (r.RAW / f"{x['fid']}{x['ext']}").exists()) + \
               sum(int(d.get("size") or 0) / 1e6 for d in on_drive)
    return {"new_local": new_local, "uncarded": uncarded, "banned_uncarded": banned_uncarded, "on_drive": on_drive,
            "calls": len(to_card), "images": images, "fetch_mb": round(fetch_mb, 1),
            "minutes": round(len(to_card) * CARD_SEC_WALL / 60, 1), "local_total": len(local), "cards": len(cards)}


def extra_row(x):
    """INDEX-shaped row for a clip that is only local (or only on Drive)."""
    w, h = x.get("w"), x.get("h")
    return {"Folder": x.get("folder") or "local (not in INDEX)", "New file name": x["name"], "What you see": "", "Creator says (if talking)": "",
            "Type": "B-roll", "Pet": "", "Quality (1-3)": "", "Flags": "", "Creator": "", "Seconds": f"{x.get('dur') or 0:.0f}",
            "Resolution": f"{w}x{h}" if w and h else "", "MB": f"{x.get('mb') or 0:.1f}",
            "Source / original file name": x.get("source") or "footage/raw (moments.py sync)", "Link": f"https://drive.google.com/file/d/{x['fid']}/view"}


def sync(a):
    drive = None
    if a.drive:
        if not BROLL_FOLDER: sys.exit("set BROLL_DRIVE_FOLDER (Drive folder id of your footage library) in .env to use --drive")
        print("listing Drive BRoll / Footage (read-only) ...", flush=True); drive = drive_listing(root=BROLL_FOLDER)
        print(f"  {len(drive)} videos on Drive")
    rep = sync_report(drive)
    nl, un, od = rep["new_local"], rep["uncarded"], rep["on_drive"]
    print(f"(i)   {len(nl)} local Drive clips in footage/raw are in neither INDEX.csv nor {EXTRA.name} "
          f"({sum(x['mb'] for x in nl):.0f} MB, {sum(x['dur'] for x in nl) / 60:.0f} min of footage; "
          f"{sum(x['named'] for x in nl)} have a Drive name from the footage folder upload logs, the rest get their id as name)")
    for x in nl[:a.show]: print(f"        {x['fid']}  {x['dur']:5.1f}s  {x['name'][:80]}")
    print(f"(ii)  {len(un)} catalogued clips have no moment card ({rep['banned_uncarded']} more are banned and stay uncarded); "
          f"{sum(1 for x in un if not (rawedit().RAW / (x['fid'] + x['ext'])).exists())} of them must be fetched from Drive")
    for x in un[:a.show]: print(f"        {x['fid']}  {x['Type'][:16]:16s} {x['New file name'][:80]}")
    if drive is not None:
        print(f"(iv)  {len(od)} Drive videos are not downloaded or catalogued ({sum(int(d.get('size') or 0) for d in od) / 1e6:.0f} MB)")
        for d in od[:a.show]: print(f"        {d['id']}  {d.get('path', '')}/{d.get('name', '')}"[:120])
    print(f"(iii) carding them = {rep['calls']} Claude calls ({VISION} via the {BACKEND['use']} backend: .env key first, then "
          f"`claude -p` on the owner's plan), {rep['images']} frame sheets, ~{rep['minutes']:.0f} min at {CARD_WORKERS} workers "
          f"(measured {CARD_SEC_WALL:.0f} s/clip on the 2026-11-16 build), {rep['fetch_mb']:,.0f} MB to download first; then a local re-embed")
    if not a.go:
        print("\ndry run: nothing written or fetched. Real run: .venv/bin/python tools/moments.py sync --go" + (" --drive" if a.drive else ""))
        return rep
    # --go: append the new clips to the extra catalogue (INDEX.csv is never rewritten)
    import csv
    new_rows = [extra_row(x) for x in nl] + [extra_row({"fid": d["id"], "name": d.get("name") or d["id"], "folder": (d.get("path") or "").strip("/"),
                                                        "mb": int(d.get("size") or 0) / 1e6, "source": "Drive BRoll / Footage (moments.py sync --drive)",
                                                        "dur": int((d.get("videoMediaMetadata") or {}).get("durationMillis") or 0) / 1000}) for d in od]
    if new_rows:
        MD.mkdir(parents=True, exist_ok=True); fresh = not EXTRA.exists()
        with open(EXTRA, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS)
            if fresh: w.writeheader()
            w.writerows(new_rows)
        print(f"added {len(new_rows)} rows to {EXTRA}")
    r = rawedit(); ids, pats = banned(); cards = {p.stem for p in CARDS.glob("*.json")} if CARDS.exists() else set()
    rows = [x for x in r.index_rows() + extra_rows() if x["fid"] not in cards and not is_banned(x["fid"], x["New file name"], ids, pats)]
    allowed = {x["fid"] for x in un} | {x["fid"] for x in nl} | {d["id"] for d in od}   # never more than the report listed
    rows = [x for x in rows if x["fid"] in allowed]
    if a.limit: rows = rows[:a.limit]
    env(); CARDS.mkdir(parents=True, exist_ok=True)
    print(f"carding {len(rows)} clips with {a.workers} workers ...", flush=True)
    errs = []

    def one(row):
        f = r.RAW / f"{row['fid']}{row['ext']}"
        if not f.exists() or f.stat().st_size < 1000:
            if not row.get("MB"): row = {**row, "MB": "0"}
            f = r.fetch(row)
        return describe(row, f)
    with cf.ThreadPoolExecutor(a.workers) as ex:
        fut = {ex.submit(one, row): row for row in rows}
        for k, fu in enumerate(cf.as_completed(fut), 1):
            row = fut[fu]
            try:
                c, _, _ = fu.result(); print(f"[{k}/{len(rows)}] {len(c['moments']):2d} moments  {row['New file name'][:70]}", flush=True)
            except BaseException as e:   # rawedit.fetch exits on a failed download: log it and keep going
                errs.append((row["New file name"], str(e)[:160])); print(f"[{k}/{len(rows)}] ERROR {row['New file name'][:60]}: {str(e)[:160]}", flush=True)
    print(f"done: {len(rows) - len(errs)} carded, {len(errs)} errors")
    if list(CARDS.glob("*.json")): embed_all()
    return rep


def stats():
    ms, _ = load_index(); r = rawedit(); rows = r.index_rows()
    if ms is None: sys.exit("no index yet")
    import collections
    print(f"{len({m['fid'] for m in ms})}/{len(rows)} clips carded, {len(ms)} moments")
    print("kinds:", dict(collections.Counter(m.get("kind") for m in ms).most_common()))
    tk = [m for m in ms if (m.get("take") or {}).get("complete")]
    print(f"complete demo takes (action+show+result): {len(tk)} — strand big {sum((m['take'] or {}).get('strand')=='big' for m in tk)}")
    print("surfaces:", dict(collections.Counter((m.get("surface") or "").split()[0] if m.get("surface") else "" for m in ms).most_common(15)))
    print("quality:", dict(collections.Counter(m.get("quality") for m in ms)))


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--only"); b.add_argument("--limit", type=int); b.add_argument("--workers", type=int, default=6)
    b.add_argument("--force", action="store_true")
    sub.add_parser("embed"); sub.add_parser("stats")
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--kind"); s.add_argument("--product", action="store_true")
    s.add_argument("--no-product", action="store_true"); s.add_argument("--take", action="store_true"); s.add_argument("--surface")
    s.add_argument("--fits"); s.add_argument("--no-face", action="store_true"); s.add_argument("--n", type=int, default=12)
    s.add_argument("--json", action="store_true")
    sh_ = sub.add_parser("show"); sh_.add_argument("mid")
    p = sub.add_parser("pick"); p.add_argument("project")
    y = sub.add_parser("sync"); y.add_argument("--dry-run", action="store_true", help="the default: report only")
    y.add_argument("--go", action="store_true"); y.add_argument("--drive", action="store_true", help="also list Drive (read-only)")
    y.add_argument("--workers", type=int, default=CARD_WORKERS); y.add_argument("--limit", type=int); y.add_argument("--show", type=int, default=8)
    a = ap.parse_args()
    if a.cmd == "sync" and a.dry_run: a.go = False
    if a.cmd == "build": build(a)
    elif a.cmd == "sync": sync(a)
    elif a.cmd == "embed": embed_all()
    elif a.cmd == "stats": stats()
    elif a.cmd == "show": print(json.dumps(get_moment(a.mid), indent=1))
    elif a.cmd == "search":
        g = True if a.product else False if a.no_product else None
        hits = search(a.query, a.n, a.kind, g, a.take, a.surface, a.fits, a.no_face)
        if a.json: print(json.dumps(hits, indent=1))
        else: [print(line(h)) for h in hits]
    elif a.cmd == "pick":
        r = rawedit(); proj = pathlib.Path(a.project)
        if not proj.is_absolute() and not proj.exists(): proj = ROOT / "projects" / a.project
        plan = json.loads((proj / "plan.json").read_text()); pick(proj, plan); r.save(proj, plan)


if __name__ == "__main__":
    main()
