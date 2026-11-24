---
name: learn
description: Learn from the owner's video revisions immediately, with NO approval step. Logs any revision given in chat, Frame.io or the review page that isn't in feedback/log.jsonl yet, lets the auto-tagger match it to the owner taste rules (REPEAT = a known mistake came back), and turns every unmatched note into a new taste rule or a one-off on the spot, then regenerates OWNER_TASTE.md. Use the moment the owner gives ANY correction on a video made with this system (animated, song, AI UGC, real-footage edit, HyperFrames, hybrid), when he types /learn, says "learn from this", "remember this edit", "don't make this mistake again", or after `frameio.py pull`.
---

# /learn: every revision changes the system, right away

The owner's standing instruction: every revision is learned right away, without asking for approval, so the same revision
is never needed again. So this skill never stops to propose. It logs, learns, and reports in one
line. Run from the repo root: `PY=.venv/bin/python`, tool `tools/feedback.py`.

## 1. Capture every revision (before fixing anything)
- Chat: each separate correction in the owner's own words:
  `$PY tools/feedback.py add <project> "<owner's words>" --src chat [--beat N] [--time 12.4] [--skill S]`
  (projects without plan.json need `--skill`; hybrid ads use the main skill, e.g. `ugc-talking-head`).
- Frame.io: `$PY tools/frameio.py pull --all`. Review-page paste: `ad.py <p> notes`.
- Also log what he LIKES or picks ("C is the best", "this one is perfect because...") with `--src chat`: his picks are
  the taste the next ad starts from (T29).
Every logged note is auto-tagged on arrival against `feedback/taste_rules.json`:
- `REPEAT T05 ...`: the system already knew this and broke it anyway. Fix it in this ad AND ask why it slipped: if a
  check could have caught it, add the check (preflight.py or the tool the skill uses) in this same session.
- `NEW #id ...`: unknown to the system. Go to step 2 for it now.

## 2. Learn each NEW note now (no approval)
Decide alone, in seconds, per note:
- **One-off** (only about this ad's content: "make the dog brown", "swap this clip for that Drive link"):
  `feedback.py dismiss <id> "one-off"`. Still fix it in the ad.
- **General** (would apply to another ad: general wording, always/never/again, a default the system gets wrong, or the
  same thing on a 2nd ad): `feedback.py taste-add "<short title>" "<rule as an instruction for the next producer>"
  --re "<regex that would have caught this note and its likely rewordings>" --ids <id> [--group "<group>"]`.
- **Refines or contradicts an existing T-rule**: the newest owner wording wins, no asking:
  `feedback.py taste-edit T07 "<full new wording>"` (old wording is kept in `was`).
- **A banned clip** ("never use this clip again", "this one is bad"): add its Drive id to
  `footage/BANNED_CLIPS.json` the same minute. `preflight.py` fails any build that references it.
- **Mechanical** (timing, size, position, levels, cuts, angle, a check a script could do): also put it in code:
  `tools/preflight.py` for a check on the finished video, or the default in the tool that sets it. A check in code
  always runs; a sentence can be skipped.
Write rules as plain instructions, one or two sentences, no story. Don't overfit: a correction that names one ad's
specific shot is a one-off.

## 3. Close the loop
- `feedback.py taste` regenerates `feedback/OWNER_TASTE.md` (taste-add / taste-edit already do this).
- One-line report to the owner, no approval question: "Learned: T35 <title>; repeat of T13 (now checked in preflight);
  2 one-offs fixed in this ad."
- If the rule applies outside video ads (statics, scripts), also save it to memory.

## Guardrails
- Never loosen a checker to make something pass. Never delete a T-rule; a newer owner note replaces its wording.
- Brand offer/claims rules live in `brand/brand.json` (`default_offer`, `never_show`, `banned_phrases`), not here.
- `feedback.py top` = the week's most repeated mistakes; the Monday `weekly_report.py` writes `feedback/WEEKLY_<date>.md`.
