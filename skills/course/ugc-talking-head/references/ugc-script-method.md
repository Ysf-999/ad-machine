---
name: ugc-video-script
description: Use when creating UGC video scripts, AI talking-head video scripts, creator briefs, full word-for-word scripts, video ad scripts for Meta/TikTok/YouTube Shorts, dialogue/Q&A skits, podcast-aesthetic ads, doctor/expert authority videos, day-in-life narratives, problem-solution rants, fake-vs-real PSAs, street interviews, or unboxing scripts. This is the default video script skill for direct-response video creative.
---

# UGC Video Script

## Purpose

Generate creator-ready, full-script, or AI-talking-head-ready video scripts that compress the same direct-response logic as `$fb-ad-copy` into a video format the viewer believes is real. UGC works because it doesn't feel like an ad — but the buyer pressure, mechanism, proof, and CTA still have to land.

If the user wants standard Meta ad copy with a video as one of three variations, use `$fb-ad-copy` and lift the script structure from this skill.

## Inputs

Required:

- product description or product folder
- target audience or archetype
- format (see Step 2)
- delivery mode: `creator_brief` (talking points), `full_script` (word-for-word for human), or `ai_talking_head` (word-for-word for AI avatar / faceless)
- platform: `meta`, `tiktok`, or `youtube_shorts`

Optional:

- video length: `15s`, `30s`, `60s`, `90s`, `180s`. Default `60s`.
- creator profile, mechanism, offer, awareness level, proof assets, objections, mode flag (`--extreme`, `--unrestricted`)

---

## Workflow

### 1. Load Framework Context

Load `../_shared/required-context.md`. It defines the methodology loop, reference loading rules (cheatsheet first), product packet, and control library.

Format does not change the logic — it changes the surface. The script is still moving belief.

**Reference Control Selection (mandatory when `marketing-brain/references/control-library/index.md` exists):**

1. Read the control library index.
2. Pick 1–3 pattern IDs that match buyer pressure, awareness stage, mechanism, proof, and platform.
3. For each pattern, state: why it fits, belief movement borrowed, visual grammar borrowed, product proof needed, what must not be copied (transcript, fake credentials, invented numbers, fake creator identity).
4. If no library exists, write `Reference Control Pattern: none available` and proceed from product research only.

### 2. Select Format Template

Pick the format that matches awareness state and market signal. If the user does not specify, infer.

| Format | Structure | Best For |
|---|---|---|
| `expert_authority` | Identity reveal -> hidden cause -> mechanism -> failed alternatives -> reason-why -> CTA | Problem/solution-aware. Health, supplements, skincare |
| `dialogue_qa` | Skeptic asks -> insider answers -> objection cycles -> CTA | Problem-aware, competitor-fatigued |
| `pattern_interrupt_rant` | Contrarian claim -> pain reframe -> villain -> mechanism -> proof -> CTA | High-sophistication markets |
| `problem_solution_rant` | Pain rant -> failed alternatives -> discovery -> mechanism -> result -> CTA | Problem-aware, mom/founder relatability |
| `testimonial` | Trigger -> prior skepticism -> use experience -> outcome -> recommendation | Solution-aware retargeting |
| `unboxing` | Anticipation -> first impression -> walkthrough -> reaction -> verdict | Product-aware, new launches |
| `day_in_life` | Routine -> problem moment -> product integration -> outcome -> CTA | Cold lifestyle/wellness |
| `fake_vs_real_psa` | Warning -> visual contrast -> sensory tell -> proof -> CTA | Saturated categories with copycats |
| `street_interview` | Compliment -> problem confession -> stakes -> tool reveal -> CTA | B2B, agency, high-AOV |
| `comparison_skit` | Old way vs. new way -> agitate old -> reveal new -> CTA | Switching from a known competitor |
| `timeline_reveal` | Day 1 -> Day 3 -> Day 7 -> CTA | Supplements, programs, chronological benefits |
| `case_study_narrator` | "This is [name]" -> problem -> old solution -> discovery -> result -> CTA | Cold tools, programs, B2B |
| `demonstration` | Bold claim -> live demo -> sensory reveal -> stack -> CTA | Visual products, cleaning, beauty, apparel |

### 3. Write Hook Options

Generate exactly 3 hook options. Each must:

- fit 0–3s (under 12 spoken words)
- sound like real speech, not headline copy
- create curiosity, contradiction, identity callout, or pressure
- avoid "Are you tired of..." / "Have you ever wondered..."

**Source hierarchy for hook lines (do not skip ahead):**

1. **Control library transcripts.** Pull rhythm and opening structure from the patterns selected in Step 1. Adapt — never copy verbatim
2. **Product VOC and reviews.** Use real buyer phrasing from `reviews.md` / `voc.md` / `avatar-research.md`.
3. **Product packet facts.** Real ingredient names, percentages, prices, timelines.
4. **Original writing — last resort.** Only invent when 1–3 cannot supply a line. Flag invented lines in `Launch Notes`.

Tag each hook's source inline as `[source: control-library/<pattern-id>]`, `[source: VOC]`, `[source: product-info]`, or `[source: original — needs review]`.

Hook archetypes (rotate so no two hooks attack the same belief):

- **Absolution** — removes shame, opens curiosity gap. Stigmatized symptoms.
- **Contrarian / pattern interrupt** — forces a belief check.
- **Insider secret** — Cialdini scarcity-of-information.
- **Result curiosity** — extreme outcome + reason-why setup.
- **Compliment / status hook** — stops scroll on a status signal.
- **Time-stamped pain** — visceral, specific moment.
- **Hidden symptom callout** — educational curiosity.
- **Discovery confession** — casual, native to feed.
- **POV / scenario** — TikTok-native grammar.
- **Failed alternative** — "I tried X for Y. Only this worked."
- **Negative warning** — loss aversion, safety.

Match hook archetype to awareness state. Do not use insider-secret hooks on most-aware buyers. Do not use direct-offer hooks on cold unaware audiences.

The first 3 seconds must work without sound and with sound. The visual itself — action, expression, product, demo, or B-roll — must carry the hook even if muted.

### 4. Build Script Outline

**Length-to-beat map** (ratios stay constant):

- `15s`: Hook 0-2s -> Pain/contradiction 2-5s -> Mechanism tease 5-10s -> CTA 10-15s
- `30s`: Hook 0-3s -> Pain 3-8s -> Mechanism 8-18s -> Proof 18-25s -> CTA 25-30s
- `60s`: Hook 0-3s -> Pain 3-12s -> Mechanism 12-25s -> Proof+objection 25-45s -> CTA 45-60s
- `90s`: Hook 0-4s -> Pain 4-15s -> Mechanism 15-35s -> Proof+objection 35-65s -> Offer/risk reversal 65-80s -> CTA 80-90s
- `180s`: VSL pacing — problem -> hidden cause -> education -> mechanism -> failed alternatives -> proof -> offer -> guarantee -> CTA

**Spoken word budget** (real speech ≈ 3 words/sec). Hard caps for `full_script` and `ai_talking_head` only — `creator_brief` talking points are not counted.

| Length | Target | Hard Cap |
|---|---|---|
| 15s | 45–55 | 60 |
| 30s | 90–110 | 120 |
| 60s | 180–220 | 240 |
| 90s | 270–330 | 360 |
| 180s | 540–660 | 720 |

Count every spoken word. Contractions = 1. If over, cut adjectives, redundant proof, or a beat — never raise the cap.

**Source hierarchy applies to every line** (control library → VOC → product packet → original). Tag each line's source.

**Mode-specific construction:**

- `creator_brief`: write talking points, not lines. Each beat is what to communicate, not what to say. Creator should sound like they discovered something.
- `full_script`: every line word-for-word in natural human speech. Contractions, filler ("look," "honestly," "okay so"), real rhythm, asides. Reads like a transcript of a real person, not polished ad copy.
- `ai_talking_head`: same natural human script as `full_script`. Modern AI voices handle long sentences, contractions, emotion, asides, and rhythm — do not strip to short choppy lines. Mark cuts with `[CUT TO: ...]`.

**Every script must:**

- embed the mechanism naturally — speaker discovered it, did not memorize it
- include audience journey — what they tried, what failed, what they currently believe
- handle ≥2 objections directly or by visual implication
- include ≥2 proof modes: testimonial, number, authority, demonstration, screenshot, before/after, lab result, guarantee
- adapt the selected control pattern's structure without copying its transcript, exact hook, fake proof, creator identity, or claims
- pass specificity gate: every claim has a number, name, timeframe, ingredient %, or source
- pass mechanism gate: when mechanism is named, attach a specific data point ("85% pharmaceutical-grade carvacrol" beats "powerful natural compound")
- end with a single CTA — one link, one button, one action

Controlled creative flexibility is allowed. The table may include a small number of extra beat labels such as `Product Bridge`, `Villain`, `Proof + Objection`, or `Offer + Risk Reversal` when the script meaning is stronger that way. The core jobs still must be covered: Hook, Pain, Mechanism, Proof, Objection, and CTA, and every row still needs a source.

Do not invent facts, outcomes, testimonials, prices, credentials, guarantees, scarcity, or proof.

### 5. Add B-Roll Suggestions

For `creator_brief`: 4–8 producible-on-a-phone shots. No "cinematic transitions" or studio rigs.
For `full_script` / `ai_talking_head`: every cut with a specific visual referent — product shot, screen recording, animation, photo overlay.

Cover at minimum:

- product close-up (texture, packaging, in-use)
- mechanism visualization (animation, label callout, ingredient panel, dashboard, before/after)
- proof visual (review screenshots, social proof grid, lab cert, side-by-side)
- pain moment (the relatable scene the viewer recognizes)
- offer/CTA visual (product + button + price stack)

For invisible mechanisms (gut, skin layer, biofilm), use internal-CGI overlays. For B2B/SaaS, use real screen recordings of the actual UI (URL bar visible) — that is the equivalent of "lab proof."

### 6. Write Do's and Don'ts

These ship inside the script pack so the editor/creator/AI-prompt-runner has instructions specific to this script.

**Do's:**

- Open with a stop-the-scroll line that works muted.
- Use specific numbers ($400k, 8 months, 85% carvacrol, 10,000 reviews) instead of "a lot."
- Reference the audience's prior failed attempt before pitching the mechanism.
- Make the mechanism visible — animation, ingredient callout, screen recording, demo.
- Keep one clear CTA. One link, one button, one action.
- Match outfit, setting, and tone to the format and awareness state.
- For `full_script` / `ai_talking_head`, write every line in natural human speech — contractions, filler, real rhythm. Read aloud and ask: would a real person say this?

**Don'ts:**

- Don't write word-for-word for `creator_brief` (use `full_script` if you want every line written).
- Don't write stiff, robotic, short-sentence "AI-friendly" copy for `ai_talking_head`. Modern AI voices handle natural cadence — write a real script.
- Don't open with "Are you tired of..." or "Have you ever wondered..."
- Don't stack five CTAs. Pick one.
- Don't reference the mechanism without a number, ingredient, or named source.
- Don't put the offer at the start of cold-traffic video. Earn the watch first.
- Don't soften the failed-alternative contrast. Name what the buyer already tried.
- Don't fabricate testimonials, credentials, certifications, ingredient %, or scarcity claims.
- Don't use generic B-roll directions like "lifestyle shot" or "cinematic transition." Be specific.

---

## Mode Flags

See `../_shared/mode-flags.md` for `--extreme` and `--unrestricted` rules. UGC Video Script passes the active mode flag to `$copy-validator`.

## DR Copy-Chief Pass

Run the universal pass + UGC Video Script format-specific pass from `../_shared/copy-chief-pass.md` before finalizing.

## Output Format

```markdown
## UGC Video Script: [Product Name]

**Format:** [format]
**Delivery Mode:** [creator_brief | full_script | ai_talking_head]
**Platform:** [meta | tiktok | youtube_shorts]
**Target Length:** [15s | 30s | 60s | 90s | 180s]
**Audience:** [archetype summary]
**Awareness Level:** [stage]
**Creator Profile:** [demographic + setting, or AI avatar persona]
**Offer:** [offer summary]

---

### Reference Control Selection

| Pattern ID | Why It Fits | Belief Movement Borrowed | Visual Grammar Borrowed | Product Proof Needed | Do Not Copy |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

### Hook Options

1. "[Hook A]" — [archetype] [source: ...]
2. "[Hook B]" — [archetype] [source: ...]
3. "[Hook C]" — [archetype] [source: ...]

### Script

| Beat | Timing | Direction (creator_brief) OR Line (full_script / ai_talking_head) | Source | B-Roll / Visual |
|---|---|---|---|---|
| Hook | 0-3s |  |  |  |
| Pain |  |  |  |  |
| Mechanism |  |  |  |  |
| Proof |  |  |  |  |
| Objection |  |  |  |  |
| CTA |  |  |  |  |

### Spoken Word Count

| Beat | Words | Cumulative |
|---|---:|---:|
| Hook |  |  |
| Pain |  |  |
| Mechanism |  |  |
| Proof |  |  |
| Objection |  |  |
| CTA |  |  |
| **Total** |  |  |

**Target window for [length]:** [from budget table]
**Status:** [within window | over hard cap — must rewrite]

### B-Roll Shot List

1. [Shot + when to cut]
2. [Shot]
3. [Shot]
4. [Shot]

### Do's (specific to this script)

- [behavior]

### Don'ts (specific to this script)

- [behavior]

### Launch Notes

[Compliance, substantiation, factual integrity flags. List any lines tagged `[source: original — needs review]` so the launch owner knows what needs substantiation.]

---

## Strategy Notes

[Use the template in `../_shared/strategy-notes.md`. All 5 framework levers required. Add `Reference Control Pattern(s)` listing pattern IDs and adaptation notes.]

---

## Testing Recommendation

| Priority | Hook Option | Format Variant | Why Test First |
|---:|---|---|---|
| 1 |  |  |  |
| 2 |  |  |  |
| 3 |  |  |  |
```

## Validation

After saving the script pack:

```bash
python3 marketing-brain/scripts/validate_copy.py \
  --spec ugc-video-script \
  --file <ugc-video-script-pack.md> \
  --product-dir <product-folder> \
  --report <validation-report.md>
```

Then score:

```bash
python3 marketing-brain/scripts/score_creative.py \
  --file <ugc-video-script-pack.md> \
  --product-dir <product-folder> \
  --validation-spec ugc-video-script \
  --report <creative-score-report.md>
```

Revise until validation has no errors. Use the scorecard to rank launch priority.
