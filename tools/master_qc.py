"""Strict final review of MASTER.mp4 outside the chat context: contact sheets (1 fps) + a Whisper transcript check.

Usage: master_qc.py <project-dir> [--model claude-opus-5-5] [--file MASTER.mp4]
Writes QC/master_qc.md (text only). Checks: script vs spoken words, continuity/character drift across clips,
product accuracy (brand/brand.json), caption legibility, dead frames, the current owner taste rules for the "master" stage
(tools/taste_rules.py, read at call time), anything a strict creative director would send back. Verdict SHIP / FIX with
a numbered fix list keyed to beats and timestamps. Opus at effort medium (2026-11-22; the Halloween item was removed:
owner 2026-11-09, no Halloween ads).
"""
import base64, io, json, os, pathlib, re, subprocess, sys
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


def sheets(mp4, tmp, fps=1.0, cols=6, w=300, per_rows=5):
    tmp.mkdir(parents=True, exist_ok=True)
    for f in tmp.glob("f*.jpg"): f.unlink()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp4), "-vf", f"fps={fps},scale={w}:-2", str(tmp / "f%04d.jpg")], check=True)
    ims = [Image.open(f) for f in sorted(tmp.glob("f*.jpg"))]
    fw, fh = ims[0].size; out = []; per = cols * per_rows
    for s in range(0, len(ims), per):
        chunk = ims[s:s + per]; rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (fw * cols, fh * rows), "black")
        for i, im in enumerate(chunk): sheet.paste(im, ((i % cols) * fw, (i // cols) * fh))
        buf = io.BytesIO(); sheet.save(buf, "JPEG", quality=80); out.append((s / fps, buf.getvalue()))
    return out


def transcript(mp4):
    import mlx_whisper
    r = mlx_whisper.transcribe(str(mp4), path_or_hf_repo="mlx-community/whisper-large-v3-turbo")
    return "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text'].strip()}" for s in r["segments"])


def main():
    a = sys.argv[1:]
    model = a[a.index("--model") + 1] if "--model" in a else "claude-opus-5-5"
    fname = a[a.index("--file") + 1] if "--file" in a else "MASTER.mp4"
    proj = pathlib.Path([x for x in a if not x.startswith("--") and x not in (model, fname)][0]).resolve()
    plan = json.loads((proj / "plan.json").read_text())
    mp4 = proj / fname
    qc = proj / "QC"; qc.mkdir(exist_ok=True)
    tr = transcript(mp4)
    # audio levels (LUFS, true peak, music under the voice when VO/vo.mp3 exists) — the frame checks can't hear
    vo = proj / "VO" / "vo.mp3"
    au = subprocess.run([sys.executable, "-I", str(pathlib.Path(__file__).parent / "audio_check.py"), str(mp4)] + (["--voice", str(vo)] if vo.exists() else []),
                        capture_output=True, text=True).stdout.strip()
    tr += "\n\nAUDIO LEVELS (measured):\n" + au
    blocks = sheets(mp4, qc / "_master_frames")
    order = (proj / "EDIT_KIT" / "ORDER.txt").read_text() if (proj / "EDIT_KIT" / "ORDER.txt").exists() else ""
    beats = [{k: b.get(k) for k in ("n", "vo", "visual", "vo_start", "vo_end", "emotion")} for b in plan["beats"]]
    content = []
    for t0, b in blocks:
        content.append({"type": "text", "text": f"Contact sheet from t={t0:.0f}s, one frame per second, left-to-right then top-to-bottom, 6 per row. Captions are burned in."})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b).decode()}})
    owner_rules = taste_rules.prompt_block("master")
    content.append({"type": "text", "text": f"""You are a strict creative director reviewing a finished AI-animated 9:16 ad before it goes to the client. Be harsh and specific; the client sends back anything that looks off.

AD: {plan.get('ad')}  STYLE: {plan.get('style')}
CHARACTERS: {json.dumps(plan.get('characters'), indent=0)}
INTENDED BEATS (vo line, intended visual, timing):
{json.dumps(beats, indent=0)}
EDIT ORDER / speed map:
{order}
SPOKEN WORDS (Whisper transcript of the master):
{tr}
PRODUCT RULES (the product must obey these whenever it appears):
{PRODUCT_RULES}

{owner_rules}

Check, in this order, and report only real problems:
1. SCRIPT: does the transcript match the intended VO word for word? List any mismatch.
2. SYNC: does each beat's picture match what the words say at that time (within ~1 s)? Any frozen/held frames, obvious speed-up jitter, or a scene that ends before its line?
3. CONTINUITY: same character (face, hair, outfit, species, costume), same room, same lighting across cuts unless a location change is intended. Name every drift with the timestamp.
4. PRODUCT: every product appearance against the rules (shape, colours and logo position, size vs the hand, how it is held or worn, how it is used, the result state). Hand anatomy check on close-ups.
5. RENDER DEFECTS: extra limbs, melted faces, garbled text, duplicated objects, floating objects, style breaks (a photoreal frame in a cartoon).
6. CAPTIONS: legible, not covering faces/product, not overlapping other on-screen text.
7. HOOK: with the sound off, does the first frame make the problem and audience clear, and is the hook readable as on-screen text by t=1.0 s (sheet frames 0 s and 1 s)? Is every spoken line captioned, so the ad still makes sense muted?
8. OWNER RULES: any breach of the owner taste rules listed above that you can see or read in the sheets, transcript or audio levels; name the rule id in the fix.

Output format (plain text):
VERDICT: SHIP or FIX
SCORE: n/10
FIX LIST: numbered, each = [beat N @ t=..s] what is wrong -> exactly what to regenerate or change (frame edit note / clip note / re-time). Order by severity.
MINOR NOTES: optional.
"""})
    # always keep the sheets on disk so a human/agent can review them without the API
    sheet_dir = qc / "master_sheets"; sheet_dir.mkdir(exist_ok=True)
    for f in sheet_dir.glob("*.jpg"): f.unlink()
    for t0, b in blocks: (sheet_dir / f"sheet_{int(t0):03d}s.jpg").write_bytes(b)
    prompt_txt = content[-1]["text"]
    (qc / "master_review_prompt.md").write_text(prompt_txt)
    try:
        client = anthropic.Anthropic()
        r = client.messages.create(model=model, max_tokens=6000, thinking={"type": "between_tools"},
                                   output_config={"effort": "medium"}, messages=[{"role": "user", "content": content}])
        txt = "".join(b.text for b in r.content if b.type == "text")
    except anthropic.BadRequestError as e:
        if "credit" not in str(e).lower(): raise
        txt = ("VERDICT: MANUAL (API unavailable)\n"
               f"Read the contact sheets in {sheet_dir} (1 frame/s, 6 per row) and apply the checklist in {qc / 'master_review_prompt.md'} yourself; "
               "write your own VERDICT/SCORE/FIX LIST into QC/master_qc.md.")
        print("!! API_UNAVAILABLE (no credits): sheets + transcript + review prompt written for manual review", flush=True)
    (qc / "master_qc.md").write_text(f"# Master QC — {plan.get('ad')} ({fname})\n\n{txt}\n\n## Transcript\n{tr}\n")
    print(txt)


if __name__ == "__main__":
    main()
