"""Brand settings for every tool: one place for the brand name, product description and hard rules.

Fill in brand/brand.json (copy brand/brand.example.json). Tools do `from brand import BRAND` (tools/ is on sys.path)
and use BRAND["product_word"], BRAND["product_look"] etc. in their prompts instead of hard-coding a product.
"""
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
_DIR = ROOT / "brand"


def load():
    for name in ("brand.json", "brand.example.json"):
        p = _DIR / name
        if p.exists():
            data = json.loads(p.read_text())
            data.pop("_help", None)
            return data
    raise SystemExit("brand/brand.json is missing: copy brand/brand.example.json and fill it in")


BRAND = load()


def photos():
    """Reference photos of the real product (used by product_check.py and the vision checkers)."""
    d = _DIR / "product-photos"
    return sorted(p for p in d.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")) if d.exists() else []


def rules_text():
    """The brand's never-show list as prompt lines."""
    return "\n".join(f"- HARD RULE {r}" for r in BRAND.get("never_show", []) if r and not r.startswith("Things the product"))
