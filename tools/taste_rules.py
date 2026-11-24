"""Owner taste rules (T-rules) for the automatic checkers: which rules each checker must see, as prompt text.

Every LLM checker reads the CURRENT rules from feedback/taste_rules.json at call time, so a rule the owner adds
tomorrow reaches the checkers with no code change (built 2026-11-22: the checkers carried fixed rule lists).

Stages (optional per-rule field "stages"; a rule WITHOUT the field goes to every stage):
  plan    script / plan review before anything is generated        -> tools/plan_review.py
  shot    planned source-footage frames vs the spoken line          -> tools/shot_check.py
  still   an AI still / starting frame                              -> tools/vision_qc.py --stage frames
  clip    an AI clip                                                -> tools/vision_qc.py --stage clips
  master  the finished video with audio                             -> tools/master_qc.py
An empty list ("stages": []) = a process rule no picture/plan checker can judge (it still sits in PREFLIGHT.md).
Optional "enforced_by": list of checkers that cover the rule today ("preflight" = a code check in tools/preflight.py).

  python3 tools/taste_rules.py <stage>        print that stage's prompt block
  python3 tools/taste_rules.py --table        rule id -> stages -> checkers
Stdlib only.
"""
import hashlib, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TASTE = ROOT / "feedback" / "taste_rules.json"
STAGES = ("plan", "shot", "still", "clip", "master")
CHECKER_OF = {"plan": "plan_review", "shot": "shot_check", "still": "vision_qc", "clip": "vision_qc", "master": "master_qc"}
BUILT = "2026-11-15"   # T01-T34 carry no "added": the list was built that day (see _about in the json)
BLOCK_VERSION = "1"    # bump when the block's wording changes, so cached verdicts keyed on stage_hash are re-asked
HEADER = ("OWNER TASTE RULES (current list from feedback/taste_rules.json; the owner has already had to correct every one "
          "of these). Judge what you are shown against each rule where it applies to this kind of material, cite the rule "
          "id (e.g. T08) for a breach, and ignore a rule that does not apply here.")
_cache = {}


def _path(path=None):
    return pathlib.Path(path) if path else TASTE


def load(path=None):
    """All rules (list of dicts, as stored), re-read when the file changes."""
    p = _path(path)
    m = (str(p), p.stat().st_mtime_ns)
    if _cache.get("k") != m:
        _cache.update(k=m, rules=json.loads(p.read_text())["rules"])
    return [dict(r) for r in _cache["rules"]]


def stages_of(rule):
    s = rule.get("stages")
    return list(STAGES) if s is None else [x for x in s if x in STAGES]


def _check(stage):
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}: one of {', '.join(STAGES)}")


def for_stage(stage, path=None):
    _check(stage)
    return [r for r in load(path) if stage in stages_of(r)]


def checkers_of(rule):
    """The LLM checkers that see this rule (from its stages), in pipeline order."""
    out = []
    for s in stages_of(rule):
        if CHECKER_OF[s] not in out:
            out.append(CHECKER_OF[s])
    return out


def coverage(rule):
    """Every automatic check on this rule: the stored enforced_by plus the LLM checkers its stages imply."""
    out = list(rule.get("enforced_by") or [])
    for c in checkers_of(rule):
        if c not in out:
            out.append(c)
    return out


def _line(r, cap=None):
    text = " ".join(str(r.get("rule", "")).split())
    if cap and len(text) > cap:
        cut = text[:cap]
        dot = cut.rfind(". ")
        text = (cut[:dot + 1] if dot > cap * 0.5 else cut.rstrip() + "...")
    return f"{r['id']} {r.get('title', '').strip()}: {text}"


def prompt_block(stage, max_chars=24000, path=None):
    """Compact text block for a checker prompt: one line per rule of that stage. Over max_chars, every rule's text is
    shortened evenly (each rule keeps its id and title) rather than dropping rules. '' when the stage has no rules."""
    rules = for_stage(stage, path)
    if not rules:
        return ""
    lines = [_line(r) for r in rules]
    if len(HEADER) + sum(len(x) + 1 for x in lines) > max_chars:
        room = max_chars - len(HEADER) - sum(len(f"{r['id']} {r.get('title', '').strip()}: ") + 1 for r in rules)
        cap = max(room // len(rules), 60)
        lines = [_line(r, cap) for r in rules]
    return HEADER + "\n" + "\n".join("- " + x for x in lines)


def stage_hash(stage, path=None):
    """sha256 over the ids + rule texts a stage sees (plus the block version): a cache key part for checker verdicts."""
    rules = for_stage(stage, path)
    blob = json.dumps([BLOCK_VERSION, stage] + [[r["id"], r.get("rule", "")] for r in rules], ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--table":
        for r in load():
            print(f"{r['id']}  {','.join(stages_of(r)) or '-':32s}  {', '.join(coverage(r)) or '-'}")
    elif a and a[0] in STAGES:
        b = prompt_block(a[0])
        print(b)
        print(f"\n[{len(for_stage(a[0]))} rules, {len(b)} chars, hash {stage_hash(a[0])[:12]}]", file=sys.stderr)
    else:
        sys.exit(__doc__)
