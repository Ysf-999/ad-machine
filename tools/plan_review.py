"""Second-pass review of a visual plan BEFORE any image is generated (Boris's 'review stage').

Usage: plan_review.py <project-dir> [--apply]
Sends plan.json beats + the product rules (brand/brand.json) to Claude, gets back per-beat findings and a tightened
`visual`/`motion` rewrite. Writes QC/plan_review.md; with --apply, patches plan.json (keeps originals in beat['visual_orig']).
The system prompt carries the current owner taste rules for the "plan" stage (tools/taste_rules.py, read at call time).
Opus at effort high: this is the one gate before paid generation.
"""
import json, os, pathlib, sys
import sys as _sys, os as _os; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import claude_client as anthropic

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

SYSTEM = """You review visual plans for short animated product ads before they are rendered by an image model (Nano Banana Pro) and an image-to-video model (Kling 3.0, 5-second silent clips).
For each beat check:
1. LITERAL VISUAL: does the visual show the meaning of the line, not a person saying it? One clear action per clip.
2. RENDERABILITY: will the models struggle? Hands manipulating small objects, readable text, two characters interacting, fast multi-step actions, objects changing state mid-clip. Simplify: tight close-ups, one action, start+end frames for state changes.
3. PRODUCT: every appearance of the product must follow the product rules exactly (shape, which side faces where, size relative to the hand, how it is worn, how it cleans, the result state).
4. CONTINUITY: same room/lighting/outfit across beats unless a cut is intended.
5. SCALE WORDS: when the product is held, the visual must state its size relative to the hand.
6. HOOK FRAME (beat 1 only): with the sound off, does the first second make clear what problem this is about and who it is for? If not, rewrite beat 1 so the problem is shown literally and instantly.
7. ONE IDEA, ONE FEELING: a viewer must take in each frame in under a second, so one focal point and no busy composition. Name the feeling the beat should land (e.g. frustration, disgust, embarrassment, curiosity, relief, satisfaction) and make sure the visual carries it; flag beats that carry none.
Beats with a "lib" field reuse an approved library clip: report issues but never rewrite their visual or motion.
Return JSON: {"beats":[{"n":1,"issues":["..."],"emotion":"<the feeling this beat lands>","visual":"<rewritten visual, or same>","motion":"<one sentence of motion for the clip>","needs_end_frame":false,"end_visual":"<if needs_end_frame, the end state>"}],"summary":"..."}"""


def system_prompt():
    """SYSTEM + the current plan-stage owner rules (a breach becomes an issue naming the rule id; same JSON reply)."""
    block = taste_rules.prompt_block("plan")
    return SYSTEM + ("\n\n" + block + "\nReport a beat that would break one of these owner rules as an issue that starts with the rule id "
                     "(e.g. \"T31: ...\") and fix it in the rewrite. The JSON reply format above does not change." if block else "")


def main():
    a = sys.argv[1:]
    proj = pathlib.Path([x for x in a if not x.startswith("--")][0]).resolve()
    plan = json.loads((proj / "plan.json").read_text())
    rules = PRODUCT_RULES
    payload = {"style": plan.get("style"), "characters": plan.get("characters", plan.get("character")),
               "beats": [{k: b.get(k) for k in ("n", "vo", "visual", "camera", "sfx", "motion", "end_visual", "lib")} for b in plan["beats"]]}
    client = anthropic.Anthropic()
    qc = proj / "QC"; qc.mkdir(exist_ok=True)
    try:
        with client.messages.stream(model="claude-opus-5-5", max_tokens=64000, system=system_prompt(),
                                    output_config={"effort": "high"},
                                    messages=[{"role": "user", "content": f"PRODUCT RULES:\n{rules}\n\nPLAN:\n{json.dumps(payload, indent=1)}"}]) as s:
            r = s.get_final_message()
    except anthropic.BadRequestError as e:
        if "credit" in str(e).lower():
            (qc / "plan_review.md").write_text(f"# Plan review — {plan.get('ad')}\n\nAPI unavailable (no credits). Review the plan manually against the 7 checks in tools/plan_review.py SYSTEM and record findings here.\n")
            sys.exit("!! API_UNAVAILABLE (no credits): wrote QC/plan_review.md placeholder; do the review pass manually")
        raise
    if r.stop_reason == "refusal":
        sys.exit("review refused")
    text = "".join(b.text for b in r.content if b.type == "text")
    (qc / "plan_review_raw.txt").write_text(text)  # kept so a malformed reply can be inspected
    i, j = text.find("{"), text.rfind("}")
    try:
        out = json.loads(text[i:j + 1], strict=False)
    except json.JSONDecodeError as e2:
        sys.exit(f"reviewer returned malformed JSON ({e2}); raw text saved to QC/plan_review_raw.txt — review manually")
    md = [f"# Plan review — {plan.get('ad')}", "", out.get("summary", ""), ""]
    by_n = {x["n"]: x for x in out["beats"]}
    for b in plan["beats"]:
        x = by_n.get(b["n"], {})
        md.append(f"## Beat {b['n']} — “{b.get('vo','')}”")
        if x.get("emotion"): md.append(f"- feeling: {x['emotion']}")
        for iss in x.get("issues", []): md.append(f"- ⚠️ {iss}")
        if x.get("visual") and x["visual"] != b["visual"]: md.append(f"- visual → {x['visual']}")
        if x.get("motion"): md.append(f"- motion → {x['motion']}")
        if x.get("needs_end_frame"): md.append(f"- end frame → {x.get('end_visual','')}")
        md.append("")
    (qc / "plan_review.md").write_text("\n".join(md))
    print("\n".join(md))
    if "--apply" in a:
        for b in plan["beats"]:
            x = by_n.get(b["n"])
            if not x: continue
            if x.get("emotion"): b["emotion"] = x["emotion"]
            if b.get("lib"): continue
            v = (x.get("visual") or "").strip()
            # the reviewer sometimes answers "same" / "unchanged" / a short note instead of a full rewrite: never
            # overwrite a scene description with that (hw12 got the literal visual "same", Oct 28)
            if len(v) < 60 or v.lower().rstrip(".") in ("same", "unchanged", "no change", "keep", "as is"):
                v = ""
            if v and v != b["visual"]:
                x["visual"] = v
                b.setdefault("visual_orig", b["visual"]); b["visual"] = x["visual"]
            if x.get("motion"): b["motion"] = x["motion"]
            if x.get("needs_end_frame") and x.get("end_visual"): b["end_visual"] = x["end_visual"]
        (proj / "plan.json").write_text(json.dumps(plan, indent=2)); print("plan.json patched")


if __name__ == "__main__":
    main()
