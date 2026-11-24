---
name: creative-scorecard
description: Use after creating DTC ads, native ad packs, long-form statics, image prompts, hooks, or creative test concepts to score launch quality, market signal strength, pressure intensity, belief shift clarity, mechanism believability, proof density, visualizability, and scale potential.
---

# Creative Scorecard

## Purpose

Use this after `$copy-validator`. Validation answers: "Did it meet the spec?" Scoring answers: "Which creative deserves spend first?"

The score is not a replacement for ad account data. It is a pre-launch filter that stops polished but weak creative from entering the test plan.

## Score Command

Run from the project root:

```bash
python3 marketing-brain/scripts/score_creative.py \
  --file marketing-brain/products/<product>/ads/<ad-pack>.md \
  --product-dir marketing-brain/products/<product> \
  --report marketing-brain/products/<product>/ads/creative-score-report.md
```

The scorer now runs a validation gate first. It infers the validation spec from the asset unless `--validation-spec` is supplied. If validation fails, scoring stops and the report is not launch-usable.

Use `--skip-validation-gate` only for forensic/advisory scoring of old drafts. Do not use skipped-gate scores to choose launch priority.

## Score Dimensions

The default scorecard is `marketing-brain/specs/creative-scorecard.yml`.

It scores:

- Signal Strength: grounded in real market signal, trigger event, or market hatred.
- Pressure Intensity: makes the cost of inaction feel concrete.
- Belief Shift Clarity: moves one buyer belief cleanly.
- Mechanism Believability: explains why this product is the credible next move.
- Proof Density: uses proof, specificity, reason-why, guarantee, or authority.
- Creative Visualizability: can become a strong static, UGC shot, or prompt.
- Scale Potential: can expand into more hooks, formats, and variants.

## Grades

- 85-100: Scale Candidate
- 70-84: Testable
- 55-69: Needs Sharpening
- Under 55: Not Ready

## Required Behavior

After scoring:

1. Confirm the validation gate passed.
2. Rank creatives by score. UGC packs are scored per script, not as one giant document.
3. Add each launch candidate to `creative-ledger.csv`.
4. Launch or expand the highest-scoring creatives first.
5. Revise low dimensions before building variants.
6. Treat the score as a launch filter, then let spend data overrule it.

## Output Standard

Final copy or strategy outputs should include:

- score report path
- average score
- highest-scoring creative
- weakest dimension to improve
- which creative should launch first
