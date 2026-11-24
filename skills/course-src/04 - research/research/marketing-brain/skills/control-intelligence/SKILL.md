---
name: control-intelligence
description: Use when the user provides winning ads, scripts, Facebook copy, landing pages, advertorials, emails, UGC scripts, performance data, competitor controls, or swipe files and wants them deconstructed into reusable DTC creative patterns, testing hypotheses, and new variants.
---

# Control Intelligence

## Purpose

At scale, winning assets are not inspiration. They are market evidence.

Use this skill to turn proven ads, scripts, captions, landing pages, and funnels into a control library that can generate better briefs, copy, tests, and scaling spirals without copying wording.

## Inputs

Use any supplied:

- winning Facebook ad copy
- video scripts
- UGC scripts
- long-form statics
- landing pages
- advertorials
- emails/SMS
- competitor controls
- Meta Ad Library links or screenshots
- spend, CTR, CPC, CPA, ROAS, CVR, AOV, hook rate, hold rate, comments
- product/category context

If performance data is missing, mark the asset as `Pattern-only`, not a proven control.

## Deconstruction

For each asset, extract:

- asset type
- source and date
- product/category
- traffic temperature
- awareness stage
- market sophistication
- hook type
- first 125 characters or first 3 seconds
- buyer pressure
- current belief
- new belief
- mechanism weapon
- proof stack
- objection handling
- CTA / offer structure
- visual or page structure
- persuasion levers: Schwartz, Halbert, Kennedy, Cialdini, Wundt
- what is transferable
- what is not transferable
- claims that require proof
- likely reason it won

## Pattern Library Rules

Do not copy the asset's exact wording unless the user owns the asset and explicitly asks for reuse.

Extract patterns like:

- "Why does X still happen after Y?"
- "False choice -> third path"
- "Authority confession -> industry trap -> mechanism reveal"
- "Offer stack -> proof bullets -> guarantee"
- "Problem micro-moment -> hidden mechanism -> CTA"
- "I tried X/Y/Z -> here is what finally changed"

Then rewrite using the target product's own market signal, mechanism, proof, and constraints.

## Control Library Workflow

When the user supplies batch analyses, uploaded winning ads, transcripts, or swipe-file markdown, convert them into reusable controls before creating new copy.

Preferred deterministic path:

```bash
python3 marketing-brain/scripts/build_control_library.py \
  --input-dir "/path/to/analysis_output" \
  --output-dir marketing-brain/references/control-library
```

The generated library lives at:

- `marketing-brain/references/control-library/controls.json` — individual ad deconstructions
- `marketing-brain/references/control-library/patterns.json` — aggregate pattern families
- `marketing-brain/references/control-library/index.md` — human-readable pattern index

The aggregate pattern index includes `evidence_quality`, `performance_status_counts`, and `performance_weight`. Use these to avoid treating a structural swipe the same as a spend-backed control.

If the input is not already in the batch format, manually deconstruct it into `templates/winning-asset/deconstruction.md` first, then add it to the library as a `Pattern-only` control unless real spend/performance data is supplied.

## Pattern Taxonomy

Use these pattern IDs consistently so other skills can retrieve and adapt controls:

- `dialogue-skeptic` — one speaker voices the buyer's objection; another answers with mechanism and proof.
- `podcast-myth-bust` — authority-style conversation challenges a common belief and reveals the better mechanism.
- `psa-warning` — protective warning about a hidden buying mistake or failed alternative.
- `listicle-signs` — diagnostic symptom/sign list that self-qualifies the buyer.
- `authority-expert` — expert or expert-coded explanation with proof and risk reduction.
- `pov-skit` — native micro-moment that dramatizes the buyer's lived frustration.
- `timeline-reveal` — honest result/process timeline for routines, supplements, skincare, or tools.
- `street-interview` — discovery interview built on status, curiosity, or social proof.
- `comparison-contrast` — old way vs. new way or failed alternative vs. mechanism.
- `demo-unboxing` — tactile product proof through opening, applying, using, or comparing.
- `problem-solution-rant` — creator vents the pain, names failed attempts, reveals hidden cause, then recommends.
- `contrarian-reframe` — familiar belief is challenged, then replaced with a more useful mechanism.
- `process-reveal` — workflow, document, or behind-the-scenes process becomes proof.
- `internal-monologue` — the buyer's private decision debate is dramatized and resolved.
- `redemption-story` — dramatic social reversal or comeback story reveals the transformation mechanism.
- `whistleblower-personification` — ingredient, product, or insider voice exposes an overlooked mechanism.

## Reference Matching

Before writing new creative, choose 1-3 reference patterns by fit:

1. **Buyer pressure:** shame, fear, wasted money, status, convenience, medical trust, or recurring frustration.
2. **Awareness stage:** problem-aware buyers need lived moments; solution-aware buyers need failed-alternative contrast; product-aware buyers need proof and offer.
3. **Mechanism shape:** ingredient, routine, diagnostic, delivery, access, proof, price, or process.
4. **Proof available:** do not pick `authority-expert`, `timeline-reveal`, or `psa-warning` if the product lacks proof to support the structure.
5. **Native format:** match visual grammar to platform: car/podcast/dialogue for objections, bathroom/kitchen/bedroom for intimate or personal pain, screen recording for SaaS, table demo for visible product proof.

Every adapted output must include:

- selected pattern IDs
- why each pattern fits this product/angle
- what belief movement is being borrowed
- what visual grammar is being borrowed
- what must not be copied
- what proof must be supplied by the target product

## Anti-Slop Rules

- A winning ad is not a script to imitate. It is evidence that a belief movement, hook shape, visual grammar, or proof order can hold attention and move action.
- If the adapted script could work for ten unrelated products, it has not used the control library correctly.
- If the output lacks a product-specific failed alternative, trigger event, mechanism, or proof stack, rewrite it before validation.
- Never import claims, credentials, statistics, scarcity, guarantee, price, testimonials, or medical outcomes from a reference ad.

## Output

For each source asset:

```markdown
## Control Deconstruction: [Asset Name]

**Asset Type:**
**Performance Status:** [Control | Winner | Pattern-only | Unknown]
**Traffic Temperature:**
**Awareness Stage:**
**Market Sophistication:**

### What The Asset Is Really Doing

### Hook Pattern

### Buyer Pressure

### Belief Shift

### Mechanism Weapon

### Proof Stack

### Offer / CTA Structure

### Reference Application

- Schwartz:
- Halbert:
- Kennedy:
- Cialdini:
- Wundt:

### Transferable Pattern

### Do Not Copy

### New Test Ideas

1.
2.
3.
```

## 9-Figure Scale Use

A mature account should maintain a control library by:

- product
- archetype
- awareness stage
- hook type
- mechanism type
- proof type
- format
- funnel step
- performance band

Evidence hierarchy:

1. Scaled control with spend and durable CPA/MER signal.
2. Account winner with clear spend and funnel metrics.
3. Competitor/reference winner with credible external signal.
4. Pattern-only deconstruction.

The goal is not more ads. The goal is faster learning loops:

1. Identify control pattern.
2. Extract the belief shift.
3. Rebuild it for a new product or archetype.
4. Validate structure and claims.
5. Score launch priority.
6. Launch variants.
7. Feed spend data back into the library.

## Quality Bar

A good deconstruction explains why the asset probably worked and what can be reused without stealing the words, claims, or brand identity.
