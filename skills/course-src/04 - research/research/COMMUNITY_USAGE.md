# Marketing Brain Skill Pack - Community Usage Guide

This project is a local Codex workflow for DTC market research, avatar research, ad angles, long-form statics, native image prompts, and scaling creative.

It is not a SaaS dashboard. It is a folder-based research and copy system.

## What This Helps You Do

- Research a product category from internet sources.
- Extract buyer pains, beliefs, objections, failed alternatives, and exact language.
- Build buyer archetypes by psychology, not generic demographics.
- Turn research into direct-response ad angles.
- Build native static ad briefs and image prompts.
- Expand winning ads into horizontal creative tests.

## Folder Map

- `marketing-brain/skills/`: the operating instructions for each agentic workflow.
- `marketing-brain/references/`: marketing frameworks and research methodology notes.
- `marketing-brain/specs/`: deterministic QA specs for copy, image prompts, and claim checks.
- `marketing-brain/scripts/`: validator/scoring scripts and other repeatable tools.
- `marketing-brain/templates/product-packet/`: blank intake files for new products.
- `marketing-brain/products/`: where each product research packet and outputs should live.

## Recommended Setup

1. Copy `marketing-brain/templates/product-packet/` into a new product folder:

```bash
cp -R marketing-brain/templates/product-packet marketing-brain/products/your-product-name
```

2. Fill in the product packet files:

- `offer.md`: product, price, mechanism, promise, guarantee, funnel.
- `research-request.md`: what you want researched and what decision you need to make.
- `reviews.md`: owned reviews, testimonials, comments, support tickets, or exports.
- `competitors.md`: competitor URLs, ads, pages, offers, claims.
- `constraints.md`: allowed claims, forbidden claims, disclaimers, market restrictions.
- `references.md`: landing pages, source URLs, docs, screenshots, notes.

3. Ask Codex to run the workflow.

## Starter Prompt

Use this prompt after filling a product packet:

```text
Use the Marketing Brain project workflow.

Product folder:
marketing-brain/products/your-product-name

Read the product packet, then use:
- dtc-research-orchestrator
- internet-avatar-research
- source-discovery
- voice-of-customer-research
- control-intelligence if you have winning ads, scripts, landing pages, or competitor controls
- archetype-builder
- angle-factory
- fb-ad-copy for standard Facebook/Instagram ad copy
- long-form-static-builder
- native-image-prompt-gen if image prompts are needed
- copy-validator after copy or image prompts are written
- creative-scorecard after validation to rank launch priority

Goal:
Create a research-backed ad strategy for this product.

Output:
1. Offer diagnosis
2. Decision-first avatar research brief
3. Source map
4. VOC table
5. Trigger event map
6. Pain ladders
7. Buyer archetypes
8. Ranked ad angles
9. Facebook ad copy variations, native ad concepts, or long-form static briefs
10. Validation report
11. Creative score report
12. Test plan
```

If your Codex session does not automatically discover project-local skills, explicitly tell it:

```text
Read the relevant SKILL.md files in marketing-brain/skills/ and follow them as the operating workflow.
```

## Forcing Skill Compliance (Single-Asset Prompts)

If the agent skips the gate and jumps straight to writing copy, the prompt was too vague. Three rules force compliance:

**1. Name the skill file by path.** Reading the skill file is what triggers the rest of the loop.

**2. Make the gate the first deliverable.** Ask for the loaded inputs before the asset, so skipping is visible.

**3. Use the orchestrator for full runs**, not single-skill prompts. Its Cache-Aware Workflow Gate enforces step order.

Reusable single-asset template:

```text
Skill: marketing-brain/skills/<skill-name>/SKILL.md
Product: marketing-brain/products/<product-name>/
Format: <single_image | carousel | video | testimonial 60s | LFS | etc.>
Mode: --lite

Before writing, list:
- product files loaded
- references loaded (cheatsheet vs full)
- control patterns selected (with pattern IDs)

Then produce the asset in the skill's output format,
including Strategy Notes, copy-chief pass, validation, and score.
```

Why this works: a vague natural-language ask gives the agent permission to "just help." A path + a pre-asset checklist removes that permission. The agent has to lie to skip the gate, and it won't.

For full multi-step campaigns, use the Starter Prompt above instead — the orchestrator handles the gate for you.

## How To Think About The Workflow

The system is decision-first.

Do not ask it to "research the customer" in a vague way. Give it a decision:

- Which cold ad angle should we test first?
- Which objection is blocking conversion?
- Which archetype should get its own landing page?
- Which competitor weakness should we attack?
- Which hook deserves a long-form static?

Good research changes what you do next.

## Best Inputs To Provide

The more raw material you provide, the sharper the output:

- product page copy
- best landing page
- customer reviews
- 1-star and 5-star reviews
- competitor pages
- competitor ads
- Meta Ad Library links
- winning ads, winning scripts, landing pages, advertorials, and current controls
- performance data: spend, CTR, CPA, ROAS, CVR, hook rate, hold rate, comments
- Reddit/TikTok/YouTube/forum comments
- support tickets
- refund reasons
- current winning ads
- failed ads
- offer constraints
- claims you can prove
- claims you cannot make

## Output Quality Rules

Good outputs should include:

- exact buyer phrases, not generic marketing language
- source references
- trigger events
- pain ladders
- behavior vs. opinion separation
- frequency x intensity ranking
- proof gaps
- clear creative recommendations
- validation reports for ad packs and image prompts
- score reports for launch priority
- control deconstructions for winning assets and competitor references
- test priorities

Weak outputs look like:

- generic persona descriptions
- unsourced pain points
- demographics without buying psychology
- ad hooks with no belief shift
- claims that do not match the product page
- missing validation report after a copy deliverable
- no scorecard when deciding which creative to launch first

## Validation Gate

Use the validator after generating ad copy or image prompts:

```bash
python3 marketing-brain/scripts/validate_copy.py \
  --spec facebook-native-ad \
  --file marketing-brain/products/your-product-name/ads/your-ad-pack.md \
  --product-dir marketing-brain/products/your-product-name \
  --report marketing-brain/products/your-product-name/ads/validation-report.md
```

Common specs:

- `facebook-ad-copy`: 3 variations, visible hook markers, headline/description limits, CTA button, format-specific blocks.
- `facebook-native-ad`: primary text length, headline CTA, required sections, product mention, disclaimer, image prompt rules.
- `ugc-video-script`: reference-control selection, source-tagged hooks, script source column, core beat jobs, spoken-word budget, launch notes.
- `long-form-static`: LFS structure, hook/body length, proof, CTA, claim hygiene.
- `image-prompt`: iPhone realism, fully focused background, no fake overlays, prompt length.
- `product-claims`: forbidden claims, product mention, price mismatch, `--extreme` labels. Claims-only; do not use it as the only gate for a format-specific deliverable.

The agent should revise and rerun until there are no errors. Warnings can be accepted only when the launch owner intentionally accepts them.

## Creative Scoring Gate

After validation passes, score the creative pack:

```bash
python3 marketing-brain/scripts/score_creative.py \
  --file marketing-brain/products/your-product-name/ads/your-ad-pack.md \
  --product-dir marketing-brain/products/your-product-name \
  --report marketing-brain/products/your-product-name/ads/creative-score-report.md
```

The score command runs the validation gate first. If validation fails, scoring stops. Use `--skip-validation-gate` only to inspect old drafts; skipped-gate scores should not drive launch decisions.

The scorecard ranks each creative on:

- Signal Strength
- Pressure Intensity
- Belief Shift Clarity
- Mechanism Believability
- Proof Density
- Creative Visualizability
- Scale Potential

Use scores as pre-launch priority, not as final truth. Spend data wins.

## Creative Ledger And Feedback Loop

Before launch, create or update the product ledger:

```bash
python3 marketing-brain/scripts/creative_ledger.py \
  --product-dir marketing-brain/products/your-product-name \
  --set creative_id=your-product-001 \
  --set concept="Scam Radar Checklist" \
  --set hypothesis="Trust inhibition blocks quiz starts" \
  --set variable_tested=first_frame \
  --set validation_spec=ugc-video-script \
  --set validation_status=PASS \
  --set score=80.5 \
  --set decision=queued
```

After launch data is entered in `creative-ledger.csv`, diagnose the loop:

```bash
python3 marketing-brain/scripts/performance_feedback.py \
  --ledger marketing-brain/products/your-product-name/creative-ledger.csv \
  --report marketing-brain/products/your-product-name/performance-feedback.md
```

Use the feedback diagnosis to decide whether to rebuild hook/visual, fix the landing bridge, fix quiz friction, fix checkout/offer trust, or expand a real winner.

## Using Winning Ad References

When you have winning ads, UGC transcripts, competitor controls, or batch analyses, turn them into a control library before asking for new scripts:

```bash
python3 marketing-brain/scripts/build_control_library.py \
  --input-dir "/path/to/analysis_output" \
  --output-dir marketing-brain/references/control-library
```

Then ask for scripts normally. The Marketing Brain should select 1-3 reference control patterns, explain why they fit the product, and adapt the belief movement and visual grammar without copying exact wording, claims, creators, or fake proof.

Control patterns are weighted by evidence quality. `Pattern-only` controls can inspire structure; performance-backed controls should carry more weight when choosing launch patterns.

Good request:

```text
Write 3 UGC scripts for this product and angle. Use the control library, but adapt the patterns to this product's VOC, mechanism, proof, and constraints.
```

## Optional Mode Flag

Use `--extreme` only when you want maximum direct-response aggression.

The workflow will ask for confirmation before using it. This mode increases hook intensity, contrast, urgency, and polarizing angle selection. Final launch review stays with the user.

## Suggested First Task

Start with one product and ask for:

```text
Run internet avatar research for this product and tell me which 3 cold traffic angles deserve the first creative test. Use evidence from reviews, competitors, Reddit/forums/comments, and the landing page. Rank by frequency, emotional intensity, buyer intent, and proof availability.
```

That is the cleanest way to feel the value of the system fast.
