"""Owner taste rules (T-rules) + the tagger that maps any owner revision to them.

  .venv/bin/python tools/taste_tags.py "<owner note>"     print the T-rules the note matches

Rules live in feedback/taste_rules.json (id, group, title, rule, re). A note can match several. A note that matches
none is NEW: the agent must learn it right away (feedback.py taste-add or a one-off dismiss) - see the learn skill.
Added 2026-11-15.
"""
import json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TASTE = ROOT / "feedback" / "taste_rules.json"
_cache = {}


def load():
    m = TASTE.stat().st_mtime
    if _cache.get("m") != m:
        d = json.loads(TASTE.read_text())
        for r in d["rules"]:
            r["_re"] = re.compile(r["re"], re.I) if r.get("re") else None
        _cache.update(m=m, d=d)
    return _cache["d"]


def rules():
    return load()["rules"]


def by_id():
    return {r["id"]: r for r in rules()}


def norm(text):
    # owner types fast: fold the common typos so the patterns still hit
    t = re.sub(r"\[frame\.io[^\]]*\]", " ", text.lower()).replace("’", "'")
    for a, b in (("lipsyc", "lipsync"), ("vocieover", "voiceover"), ("voiceoer", "voiceover"), ("fotage", "footage"),
                 ("fotoage", "footage"), ("starnd", "strand"), ("clisp", "clips"), ("lcip", "clip"),
                 ("realisitc", "realistic"), ("realsitic", "realistic"), ("innaccurate", "inaccurate"), ("etxt", "text"),
                 ("scracth", "scratch"), ("captiosn", "captions"), ("seocnd", "second")):
        t = t.replace(a, b)
    return t


def tag(text):
    t = norm(text or "")
    return [r["id"] for r in rules() if r["_re"] and r["_re"].search(t)]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ids = tag(" ".join(sys.argv[1:]))
    B = by_id()
    for i in ids:
        print(f"{i}  {B[i]['title']}")
    if not ids:
        print("NEW - matches no taste rule")
