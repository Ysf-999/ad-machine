# UGC Video Script — Golden Examples

These are passing reference packs. Read one before writing your own.

## Purpose

Anchor structure, not content. The fictional products and claims here are illustrative — never copy lines, brands, ingredient percentages, trial figures, or VOC verbatim into a real launch.

What to copy from these examples:

- the section order and heading levels
- how `[source: ...]` tags are placed on every hook and every Script-table beat
- how the Spoken Word Count table is filled in and how it lines up with the budget
- how Strategy Notes ties levers to specific operating choices instead of restating framework names
- how Launch Notes flags `[source: original — needs review]` lines

## Status

Each pack passes `validate_copy.py --spec ugc-video-script` with zero errors. The validator enforces:

- required top fields and allowed values (Format, Delivery Mode, Platform, Target Length)
- all 8 required sections present (Reference Control Selection, Hook Options, Script, Spoken Word Count, B-Roll Shot List, Do's, Don'ts, Launch Notes)
- exactly 3 hook options, each carrying a `[source: ...]` tag
- all 6 script beats present (Hook, Pain, Mechanism, Proof, Objection, CTA) with the Source column populated
- spoken-word total within target window and below the hard cap (creator_brief is exempt from word counting)
- Strategy Notes carrying all 5 framework levers + Reference Control Pattern + Copy-Chief Pass
- no banned phrases, no missing Testing Recommendation

## Examples

| File | Format | Delivery Mode | Length | Why It's Here |
|---|---|---|---|---|
| `01-problem-solution-rant-60s-full-script.md` | problem_solution_rant | full_script | 60s | Word-for-word natural human script with one beat flagged for substantiation review |
| `02-expert-authority-30s-ai-talking-head.md` | expert_authority | ai_talking_head | 30s | Tighter mechanism-first script for AI avatar delivery; no robotic TTS-safe simplification |
| `03-testimonial-30s-creator-brief.md` | testimonial | creator_brief | 30s | Talking points only — shows what `creator_brief` looks like (and how Spoken Word Count is filled when word counting doesn't apply) |

## How To Validate

From the project root:

```bash
python3 marketing-brain/scripts/validate_copy.py \
  --spec ugc-video-script \
  --file marketing-brain/skills/ugc-video-script/examples/01-problem-solution-rant-60s-full-script.md \
  --quiet
```

Should print `PASS: 0 error(s), N warning(s)`. Warnings are acceptable — errors are not.
