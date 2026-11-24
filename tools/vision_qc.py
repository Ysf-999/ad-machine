"""Vision QC: checks keyframes and clip frame-strips with Claude (Opus, effort medium) and writes a text-only report.

Runs OUTSIDE the main Claude Code session so images never enter its context.
Usage: vision_qc.py <project-dir> [--stage frames|clips|all] [--model claude-opus-5-5] [--force]
Items are checked 3 at a time, and a verdict is remembered per item (QC/qc_cache.json: the file's bytes + its question +
model + rules), so a re-run after a redo only asks about what changed. --force asks everything again.
Each call carries the current owner taste rules (tools/taste_rules.py): the "still" stage for keyframes, "clip" for clips.
2026-11-22: was Haiku at effort low with no owner rules; --model still overrides (e.g. --model claude-haiku-5-5).
Reads plan.json beats (visual descriptions), FRAMES/scene_XX.png and CLIPS/clip_XX*.mp4,
writes QC/qc_report.json + QC/qc_report.md (pass/fail per item, with specific defects).
"""
import base64, concurrent.futures, hashlib, io, json, os, pathlib, re, subprocess, sys
import sys as _sys, os as _os; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import claude_client as anthropic
from PIL import Image

def _load_env():
    """Put the repo .env keys (ANTHROPIC_API_KEY, ELEVENLABS_API_KEY, KIE_API_KEY) into os.environ if missing."""
    f = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if f.exists():
        for l in f.read_text().splitlines():
            if "=" in l and not l.startswith("#"):
                k, v = l.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
_load_env()
import os
import taste_rules

ROOT = pathlib.Path(__file__).resolve().parent.parent
from brand import BRAND, rules_text
PRODUCT_RULES = (f"{BRAND['product']} ({BRAND['product_word']}). Looks: {BRAND['product_look']}\nHow it works: {BRAND['how_it_works']}\n"
                 f"Complete demo: {BRAND['complete_demo']}\n{rules_text()}")

SYSTEM = """You are a strict QA checker for AI-generated animated ad frames. You look only for concrete, visible defects.
Report each defect in one short line. Categories to check:
- hands/anatomy: extra or missing fingers/limbs, fused hands, melted faces
- character drift: face, hair, outfit or body differs from the described character
- product accuracy: the product must match the rules below (shape, sides, size vs the hand, how it is worn and used)
- scene logic: object that doesn't match the described visual (e.g. a rolling pin instead of a lint roller), floating objects, duplicated objects
- text artefacts: garbled letters or logos, unwanted on-screen text
- composition: subject cut off, empty frame, wrong orientation
Ignore style, lighting taste and minor softness. If nothing is wrong, say PASS.
Answer as JSON: {"verdict": "PASS"|"FAIL", "defects": ["..."], "severity": "none"|"minor"|"major"}.
"major" = a viewer would notice immediately or the product is wrong; "minor" = cosmetic."""


def img_block(path, max_side=1024):
    im = Image.open(path).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
            "data": base64.standard_b64encode(buf.getvalue()).decode()}}


def strip_for(clip, n=5):
    out = clip.with_name(clip.stem + "_qcstrip.jpg")
    if out.exists():
        return out
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)],
                               capture_output=True, text=True).stdout)
    frames = []
    for i in range(n):
        f = clip.with_name(f"{clip.stem}_q{i}.jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur*(i+0.5)/n:.2f}", "-i", str(clip), "-frames:v", "1", "-vf", "scale=320:-2", str(f)], check=True)
        frames.append(Image.open(f))
    w, h = frames[0].size
    sheet = Image.new("RGB", (w * n, h))
    for i, fr in enumerate(frames):
        sheet.paste(fr, (i * w, 0)); clip.with_name(f"{clip.stem}_q{i}.jpg").unlink()
    sheet.save(out, quality=85)
    return out


API_DOWN = False
WORKERS = 3              # calls in flight at once (the same as shot_check)


def item_key(src, ctx, model, rules):
    """Cache key of one QC item: the file's bytes + everything in its question. A redo makes a new file, so it is asked again."""
    h = hashlib.sha256()
    with open(src, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    h.update(json.dumps([ctx, model, rules, SYSTEM]).encode())
    return h.hexdigest()[:24]


def system_for(stage):
    """SYSTEM + the owner rules for 'still' (a keyframe) or 'clip' (a clip strip), read at call time."""
    block = taste_rules.prompt_block(stage)
    return SYSTEM + ("\n\n" + block + "\nA visible breach of one of these owner rules is a defect: start its line with the rule id. "
                     "The JSON answer format above does not change." if block else "")


def check(client, model, images, context, stage="still"):
    global API_DOWN
    if API_DOWN:
        return {"verdict": "MANUAL", "defects": [f"API unavailable: review {', '.join(pathlib.Path(i).name for i in images)} yourself (Read the file) against the checklist"], "severity": "none"}
    content = [img_block(p) for p in images] + [{"type": "text", "text": context}]
    try:
        r = client.messages.create(model=model, max_tokens=4000, system=system_for(stage),  # 800 truncated the JSON (Oct 28)
                                   output_config={"effort": "medium"},
                                   messages=[{"role": "user", "content": content}])
    except anthropic.BadRequestError as e:
        if "credit" in str(e).lower():
            API_DOWN = True; print("!! API_UNAVAILABLE (no credits): switching to manual mode — strips are written, review them yourself", flush=True)
            return check(client, model, images, context, stage)
        raise
    if r.stop_reason == "refusal":
        return {"verdict": "SKIP", "defects": ["refused by safety classifier"], "severity": "none"}
    text = "".join(b.text for b in r.content if b.type == "text")
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {"verdict": "FAIL", "defects": [text[:200]], "severity": "minor"}
    except json.JSONDecodeError:
        return {"verdict": "FAIL", "defects": [text[:200]], "severity": "minor"}


def latest(d, stem):
    c = [p for p in d.glob(f"{stem}*.mp4") if re.fullmatch(rf"{stem}(_v\d+)?", p.stem)]
    return max(c, key=lambda p: int(p.stem.rsplit("_v", 1)[1]) if "_v" in p.stem else 1) if c else None


def main():
    a = sys.argv[1:]
    stage = a[a.index("--stage") + 1] if "--stage" in a else "all"
    model = a[a.index("--model") + 1] if "--model" in a else "claude-opus-5-5"
    proj = pathlib.Path([x for x in a if not x.startswith("--") and x not in (stage, model)][0]).resolve()
    plan = json.loads((proj / "plan.json").read_text())
    rules = PRODUCT_RULES
    chars = json.dumps(plan.get("characters", plan.get("character", "")), indent=0)
    client = anthropic.Anthropic()
    qc = proj / "QC"; qc.mkdir(exist_ok=True)
    # 1. list every item to check (in beat order), 2. reuse stored verdicts for unchanged items, 3. ask the rest 3 at a time
    jobs = []
    for b in plan["beats"]:
        n = b["n"]
        ctx = (f"Characters: {chars}\nStyle: {plan.get('style','')}\nThis beat should show: {b['visual']}\n"
               f"Product rules:\n{rules}\n")
        if stage in ("frames", "all"):
            cands = sorted((proj / "FRAMES").glob(f"scene_{n:02d}*.png"))
            fr = cands[-1] if cands else None
            if fr:
                th = fr.with_name(fr.stem + "_thumb.jpg")
                if not th.exists():
                    im = Image.open(fr).convert("RGB"); im.thumbnail((540, 540)); im.save(th, quality=85)
                jobs.append({"item": fr.name, "kind": "frame", "src": fr, "image": fr, "stage": "still", "ctx": ctx + "This is the keyframe (single image).",
                             "manual": f"API unavailable: Read {th} (540px thumbnail) and judge it against: {b['visual'][:300]}"})
        if stage in ("clips", "all"):
            cl = latest(proj / "CLIPS", f"clip_{n:02d}")
            if cl:
                jobs.append({"item": cl.name, "kind": "clip", "src": cl, "image": None, "stage": "clip", "ctx": ctx + "This is a strip of 5 frames from the animated clip, left to right in time. Check motion logic too: does the action match the description, does the product stay the same size/shape, do hands stay intact."})
    cache_file = qc / "qc_cache.json"
    try:
        cache = json.loads(cache_file.read_text()) if cache_file.exists() and "--force" not in a else {}
    except json.JSONDecodeError:
        cache = {}
    hashes = {st: taste_rules.stage_hash(st) for st in ("still", "clip")}
    for j in jobs:
        j["key"] = item_key(j["src"], j["ctx"], model, hashes[j["stage"]])
    todo = [j for j in jobs if not isinstance(cache.get(j["key"]), dict)]
    for j in todo:
        if j["image"] is None:
            j["image"] = strip_for(j["src"])   # ffmpeg frame grabs: one clip at a time, before any call

    def one(j):
        r = check(client, model, [j["image"]], j["ctx"], j["stage"])
        if r["verdict"] == "MANUAL" and j.get("manual"):
            r["defects"] = [j["manual"]]
        return r
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as ex:
        for j, r in zip(todo, ex.map(one, todo)):
            j["result"] = r
            if r.get("verdict") in ("PASS", "FAIL"):   # MANUAL / SKIP are asked again next time
                cache[j["key"]] = r
    results = []
    for j in jobs:
        r = j.get("result") or cache[j["key"]]
        results.append({"item": j["item"], "kind": j["kind"], **r})
        print(j["item"], r["verdict"], r["defects"], "" if "result" in j else "(unchanged since the last QC: verdict reused)", flush=True)
    live = {j["key"] for j in jobs}
    old = [k for k in cache if k not in live]
    for k in old[:max(len(old) - 300, 0)]:
        cache.pop(k)
    tmp = cache_file.with_suffix(".json.tmp"); tmp.write_text(json.dumps(cache)); tmp.replace(cache_file)
    print(f"{len(jobs) - len(todo)} verdict(s) reused, {len(todo)} asked", flush=True)
    (qc / "qc_report.json").write_text(json.dumps(results, indent=2))
    fails = [r for r in results if r["verdict"] == "FAIL"]
    md = [f"# QC report — {plan.get('ad')}", f"{len(results)} items checked, {len(fails)} failed" + ("  (API unavailable: MANUAL items must be reviewed by you — Read the listed thumbnail/strip files; checklist = hands/anatomy, character drift, product rules, scene logic, text artefacts, composition)" if API_DOWN else ""), ""]
    for r in results:
        md.append(f"- **{r['item']}** — {r['verdict']} ({r['severity']})" + ("".join(f"\n  - {d}" for d in r["defects"]) if r["defects"] else ""))
    (qc / "qc_report.md").write_text("\n".join(md) + "\n")
    print(f"\n{len(results)} checked, {len(fails)} FAIL -> {qc/'qc_report.md'}")


if __name__ == "__main__":
    main()
