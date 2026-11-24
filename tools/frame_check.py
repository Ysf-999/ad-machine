"""Strict single-frame check against an expected description (text-only output; images never enter the chat).

Usage: frame_check.py <image> "<what it should show>" [--hook] [--model claude-opus-5-5]
--hook adds the first-frame test: on mute, in under a second, is the problem + the audience + Halloween obvious?
Prints: VERDICT PASS/FAIL, severity, defects (one per line), and the single best fix note for `ad.py redo N frame "..."`.
"""
import base64, io, os, pathlib, sys
import sys as _sys, os as _os; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import claude_client as anthropic
from PIL import Image
ROOT = pathlib.Path(__file__).resolve().parent.parent
for l in ((ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []):
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1); os.environ.setdefault(k.strip(), v.strip())


def blk(p, side=1024):
    im = Image.open(p).convert("RGB"); im.thumbnail((side, side)); b = io.BytesIO(); im.save(b, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b.getvalue()).decode()}}


def main():
    a = sys.argv[1:]
    model = a[a.index("--model") + 1] if "--model" in a else "claude-opus-5-5"
    hook = "--hook" in a
    pos = [x for x in a if not x.startswith("--") and x != model]
    img, expected = pos[0], pos[1]
    q = ("You are a strict QA checker for a keyframe of an AI-animated ad. Compare the image with the EXPECTED description and report only concrete, visible problems: "
         "wrong or missing objects/characters, character drift (face, outfit, species, costume), anatomy errors (extra/missing limbs, fused hands, melted faces), "
         "duplicated or floating objects, garbled text, style breaks, busy composition with no single focal point, wrong framing (subject cut off), "
         "and anything a viewer would notice in the first second. Ignore taste.\n"
         + ("HOOK TEST: this is the FIRST frame of the ad. With no sound and no caption, can a viewer tell in under one second (a) what problem this is about, "
            "(b) who it is for, and (c) that it is Halloween? Score each yes/no.\n" if hook else "")
         + f"EXPECTED: {expected}\n\nAnswer in plain text, at most 8 short lines: VERDICT PASS/FAIL; SEVERITY none/minor/major; DEFECTS (one per line); "
           "FIX: one sentence that could be pasted as an edit note ('change only this: ...').")
    c = anthropic.Anthropic()
    try:
        r = c.messages.create(model=model, max_tokens=3000, thinking={"type": "between_tools"}, output_config={"effort": "medium"},
                          messages=[{"role": "user", "content": [blk(img), {"type": "text", "text": q}]}])
    except anthropic.BadRequestError as e:
        if "credit" in str(e).lower(): sys.exit("!! API_UNAVAILABLE (no credits): make a 540px thumbnail (tools/thumb.py) and judge it yourself against the checklist in this file")
        raise
    print(f"===== {pathlib.Path(img).name}\n" + "".join(getattr(b, "text", "") for b in r.content), flush=True)


if __name__ == "__main__":
    main()
