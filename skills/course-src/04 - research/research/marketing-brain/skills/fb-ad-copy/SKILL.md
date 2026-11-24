---
name: fb-ad-copy
description: Use when creating standard Facebook/Meta direct-response ad copy, including single image ads, carousel ads, or video ad scripts. This is the default Meta copy skill unless the user specifically asks for long-form statics, native advertorial statics, LFS, or image-only prompt generation.
---

# FB Ad Copy

## Purpose

Create direct-response Meta ad copy that compresses strategy into feed-native copy: hook, buyer pressure, mechanism, proof, objection handling, and CTA.

Use this for normal Facebook/Instagram ad copy. If the user asks for long-form statics, advertorial-style statics, native image concepts, or LFS, use `$long-form-static-builder` and `$native-image-prompt-gen` instead.

## Required Context

Load `../_shared/required-context.md`. It defines: methodology loop (`$market-pressure-context`), reference loading rules (cheatsheet first, full references only when needed), product packet files, control library, and winning-asset handling.

## Inputs

Required:

- product description or product folder
- target audience or avatar
- ad format: `single_image`, `carousel`, or `video`
- mechanism or reason-why
- offer

Optional:

- awareness level
- tone: `aggressive`, `conversational`, or `professional`
- landing page angle
- proof assets
- objections to handle
- mode flag such as `--extreme`

Default tone is aggressive-conversational. Do not default to compliant, educational, or polished brand voice unless the user explicitly asks for it.

## Awareness To Copy Length

- Unaware: story, curiosity, visible symptom, or market hatred first. Longer primary text.
- Problem-aware: pain and failed alternatives first. Mechanism bridges to solution.
- Solution-aware: mechanism differentiation first. Proof-heavy.
- Product-aware: offer, proof, objection handling, and urgency.
- Most-aware: offer/price/bonus/guarantee first. Minimal education.

## Variation Rules

Generate exactly 3 variations unless the user asks otherwise.

Each variation must use a different hook type:

- curiosity gap
- contradiction
- failed alternative
- market hatred
- desire outcome
- social proof
- price/value contrast
- objection reversal
- identity callout
- timing trigger

No two variations should attack the same belief in the same way.

## First 125 Character Rule

The first 125 characters are the ad.

Mark the visible hook with `||`:

```text
||Specific contradiction. Mechanism tease. Reason to keep reading.||
```

The marked hook must:

- fit under 125 characters
- stand alone before "See more"
- create curiosity, pressure, or contradiction
- avoid vague openings like "Are you looking for..."

## Character Limits

- Primary text: max 2,200 characters.
- Headline: max 40 characters.
- Description: max 30 characters.

Shorter is usually better unless awareness is low and education is needed.

## Format Requirements

### Single Image

Include:

- Primary Text
- Headline
- Description
- CTA Button
- Image Direction

Primary text should be 3-5 short paragraphs: hook -> pressure -> mechanism -> proof/objection -> CTA.

### Carousel

Include:

- Primary Text
- Headline
- Description
- CTA Button
- Carousel Cards

Use 3-5 cards:

- Card 1: hook/problem
- Cards 2-3: mechanism/proof
- Final card: offer/CTA

### Video

Include:

- Primary Text
- Headline
- Description
- CTA Button
- Video Script

Script structure:

- 0-3s: visual and verbal hook
- 3-10s: problem or failed alternative
- 10-25s: mechanism
- 25-40s: proof and objection handling
- 40-60s: offer and CTA

The first 3 seconds must work without sound and with sound.

## CTA Button Selection

Choose from Meta CTA options:

- Shop Now
- Learn More
- Sign Up
- Get Offer
- Book Now
- Contact Us
- Subscribe
- Order Now

Use `Shop Now`, `Get Offer`, or `Order Now` for direct product purchase. Use `Learn More` only when cold traffic needs education or the landing page is an advertorial.

## Proof And Objection Rules

Every variation should include:

- the product mechanism, not just features
- at least 2 proof modes when available: testimonial, number, authority, demonstration, guarantee, reason-why
- at least 2 objections handled directly or indirectly
- the audience journey: what they have tried, what is failing, or what they currently believe

Do not invent facts, outcomes, testimonials, prices, credentials, guarantees, scarcity, or proof.

## Reference Application

Every saved ad pack must include `## Strategy Notes` (see `../_shared/strategy-notes.md`) after the variations and before the testing recommendation. Pull lever names from `references/cheatsheet.md`. Use specific lever choices, not framework labels.

## DR Copy-Chief Pass

Run the universal pass + FB Ad Copy format-specific pass from `../_shared/copy-chief-pass.md` before finalizing.

Only put disclaimers inside the ad copy when the user asks, the product category demands it, or `constraints.md` explicitly says they are required in ad copy. Otherwise put them under `Launch Notes`.

## Mode Flags

See `../_shared/mode-flags.md` for `--extreme` and `--unrestricted` rules. FB Ad Copy passes the active mode flag to `$copy-validator`.

## Output Format

```markdown
## Facebook Ad Copy: [Product Name]

**Format:** [single_image | carousel | video]
**Audience:** [target audience summary]
**Awareness Level:** [detected or provided level]
**Offer:** [offer summary]

---

### Variation 1: [Hook Type]

**Primary Text:**
[Primary text with visible hook marked as ||...||]

**Headline:** [40 chars max]
**Description:** [30 chars max]
**CTA Button:** [Meta CTA option]
**Image Direction:** [single image only]
**Carousel Cards:** [carousel only]
**Video Script:** [video only]
**Launch Notes:** [claim/proof/risk notes outside the ad copy]

---

### Variation 2: [Hook Type]

[same structure]

---

### Variation 3: [Hook Type]

[same structure]

---

## Strategy Notes

[Use the template in `../_shared/strategy-notes.md`. All 5 framework levers required. Lever names from `references/cheatsheet.md`.]

---

## Testing Recommendation

| Priority | Variation | Hook Type | Why Test First |
|---:|---|---|---|
| 1 |  |  |  |
| 2 |  |  |  |
| 3 |  |  |  |
```

## Validation

After saving the ad pack, run:

```bash
python3 marketing-brain/scripts/validate_copy.py \
  --spec facebook-ad-copy \
  --file <fb-ad-copy-pack.md> \
  --product-dir <product-folder> \
  --report <validation-report.md>
```

Then score:

```bash
python3 marketing-brain/scripts/score_creative.py \
  --file <fb-ad-copy-pack.md> \
  --product-dir <product-folder> \
  --report <creative-score-report.md>
```

Revise until validation has no errors. Use the scorecard to rank launch priority.
