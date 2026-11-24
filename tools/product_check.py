"""Strict product check of a generated frame against the real product photos (text-only output, runs outside the chat).

Usage: product_check.py <image.png> [<image2.png> ...] [--worn] [--model claude-opus-5-5]
Reference photos come from brand/product-photos/ (brand.photos()); the product description from brand/brand.json.
--worn uses a photo whose file name contains "worn", "hand" or "use" (the product held or in use) instead of the first photo.
Prints a short verdict per image: PASS/FAIL + the single most important fix. Use it on every styled render,
master product prop, and every frame where the product is held or in use, BEFORE paying for video.
"""
import base64, io, os, pathlib, re, sys
import sys as _sys, os as _os; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import claude_client as anthropic
from PIL import Image
ROOT = pathlib.Path(__file__).resolve().parent.parent
for l in ((ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []):
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
from brand import BRAND, photos


def blk(p, side=900):
    im = Image.open(p).convert("RGB"); im.thumbnail((side, side)); b = io.BytesIO(); im.save(b, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b.getvalue()).decode()}}


Q = (f"Strict product QC of image 2 against the real product in image 1. The product is {BRAND['product']} ({BRAND['product_word']}). "
     f"What it looks like: {BRAND['product_look']} How it is used: {BRAND['how_it_works']}\n"
     "Answer in at most 6 short lines, no preamble: (1) shape/thickness (2) colours, logo and markings position (3) the working side (if visible) "
     "(4) how it is held or worn and scale vs the hand (if in use) (5) text/garbling (6) VERDICT PASS/FAIL + the single most important fix. "
     "Ignore style; judge geometry and layout.")


def main():
    a = sys.argv[1:]
    model = a[a.index("--model") + 1] if "--model" in a else "claude-opus-5-5"
    worn = "--worn" in a
    imgs = [x for x in a if not x.startswith("--") and x != model]
    refs = photos()
    if not refs: sys.exit("no product photos: add 1+ reference photos of the real product to brand/product-photos/")
    ref = next((r for r in refs if re.search(r"worn|hand|use", r.name, re.I)), refs[0]) if worn else refs[0]
    c = anthropic.Anthropic()
    for p in imgs:
        try:
            r = c.messages.create(model=model, max_tokens=3000, thinking={"type": "between_tools"}, output_config={"effort": "medium"},
                                  messages=[{"role": "user", "content": [{"type": "text", "text": "Image 1 = real product photo."}, blk(ref), {"type": "text", "text": "Image 2 = generated frame to check."}, blk(p), {"type": "text", "text": Q}]}])
        except anthropic.BadRequestError as e:
            if "credit" in str(e).lower(): sys.exit("!! API_UNAVAILABLE (no credits): make a 540px thumbnail (tools/thumb.py) and compare it yourself with the photos in brand/product-photos/ against brand/brand.json product_look")
            raise
        print(f"===== {pathlib.Path(p).name}\n" + "".join(getattr(b, "text", "") for b in r.content), flush=True)


if __name__ == "__main__":
    main()
