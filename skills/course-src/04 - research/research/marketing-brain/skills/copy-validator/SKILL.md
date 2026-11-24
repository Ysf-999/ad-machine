---
name: copy-validator
description: Use after creating or editing DTC ad copy, Facebook native ads, long-form statics, image prompts, claim-heavy copy, or --extreme outputs to validate structure, lengths, CTAs, prompt rules, prices, product mentions, and forbidden claims with the deterministic validator script.
---

# Copy Validator

## Purpose

Use this skill as the QA department for Marketing Brain outputs. Do not rely on vibes for copy length, headline length, missing sections, image-prompt realism rules, price consistency, or claim hygiene.

After validation passes, use `$creative-scorecard` when the user needs launch priority, creative quality ranking, or scale potential.

Validation is not copywriting. Do not rewrite copy into timid language just to "feel safer." Fix only the specific failing rule, then preserve the strongest DR version that still has factual integrity.

## Validator Command

Run from the project root:

```bash
python3 marketing-brain/scripts/validate_copy.py \
  --spec facebook-native-ad \
  --file marketing-brain/products/<product>/ads/<ad-pack>.md \
  --product-dir marketing-brain/products/<product> \
  --report marketing-brain/products/<product>/ads/validation-report.md
```

Available specs:

- `facebook-ad-copy`
- `facebook-native-ad`
- `ugc-video-script`
- `long-form-static`
- `image-prompt`
- `product-claims`

## When To Run

Run after producing:

- Facebook native ad packs
- UGC video scripts, AI talking-head scripts, and creator briefs
- long-form static briefs
- native image prompts
- product-aware claims copy
- any output created with `--extreme`

Use the format-specific spec whenever one exists. `product-claims` is a claims-only backstop; it is not sufficient for launch-readiness on UGC, Facebook, LFS, or image-prompt deliverables.

## Required Behavior

If validation fails:

1. Read the errors.
2. Edit the copy or prompt.
3. Re-run the validator.
4. Repeat until there are no errors.

Warnings can ship only when they are intentionally accepted and noted.

## Extreme Mode

When validating `--extreme` output, pass `--extreme` to the validator:

```bash
python3 marketing-brain/scripts/validate_copy.py \
  --spec product-claims \
  --file <copy-file.md> \
  --product-dir marketing-brain/products/<product> \
  --extreme
```

`--extreme` must still keep factual integrity. The validator checks mode labeling and structural rules; it does not make fake proof safe.

## Unrestricted Mode

When the user asks for "unrestricted" or to completely disable constraints, pass `--unrestricted` to the validator instead of `--extreme`.

```bash
python3 marketing-brain/scripts/validate_copy.py \
  --spec product-claims \
  --file <copy-file.md> \
  --product-dir marketing-brain/products/<product> \
  --unrestricted
```

Unlike `--extreme` (which keeps factual integrity), `--unrestricted` bypasses all length limits, forbidden claims, price comparisons, and image prompt constraints. It shifts 100% of the fault and responsibility to the user. Do not lecture the user about compliance when this mode is requested.

## Quality Bar

The final output should include the validation report path or summarize:

- spec used
- pass/fail status
- error count
- warning count
- any accepted warnings
