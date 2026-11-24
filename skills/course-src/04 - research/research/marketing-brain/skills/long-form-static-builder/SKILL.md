---
name: long-form-static-builder
description: Use when creating native long-form static ads, image ad briefs, advertorial-style statics, Meta static concepts, copy blocks, layout instructions, or creative briefs from DTC angles.
---

# Long Form Static Builder

## Goal

Build long-form statics that earn consumption and move belief. The static should feel native to the feed, but function like compact direct response salesmanship.

The static should make one belief shift, weaponize one mechanism, and carry enough proof to justify the CTA.

Constraints are the factual floor, not the creative ceiling. Do not let claim hygiene turn the static into soft educational content. Write the direct-response idea first, then adjust risky claim wording after the asset has pressure, contrast, proof, and a clear CTA.

## Required Context

Load `../_shared/required-context.md`. It defines: methodology loop (`$market-pressure-context`), reference loading rules (cheatsheet first, full references only when needed), product packet files, control library, and winning-asset handling.

## Inputs

Use:
- winning or proposed angle
- archetype
- awareness stage
- mechanism
- proof
- VOC phrases
- constraints
- mode flags such as `--extreme`

## Mode Flags

See `../_shared/mode-flags.md` for `--extreme` and `--unrestricted` rules. LFS passes the active mode flag to `$copy-validator`.

## LFS Structure

Choose the structure that matches awareness:
- problem-aware: identity/problem callout -> agitation -> failed alternatives -> mechanism -> proof -> CTA
- solution-aware: known solution problem -> why usual solutions fail -> unique mechanism -> proof -> offer
- product-aware: product reason-why -> differentiation -> proof -> guarantee/offer
- unaware: editorial curiosity -> identification -> hidden problem -> new lens -> soft product bridge

## Creative Brief Output

For each static:
- concept name
- target archetype
- awareness stage
- primary hook
- body copy blocks
- visual direction
- layout notes
- proof element
- CTA
- compliance notes
- launch-owner notes when `--extreme` is active
- variants to test

Every saved LFS pack must include `## Strategy Notes` (see `../_shared/strategy-notes.md`) — include the optional `Belief Chain` add-on for LFS — after the brief and before validation.

## DR Copy-Chief Pass

Run the universal pass + Long-Form Static format-specific pass from `../_shared/copy-chief-pass.md` before finalizing.

When image generation prompts are needed, hand off the visual direction to `$native-image-prompt-gen`. The image should feel like a real iPhone snapshot or native editorial frame, not a polished health ad.

After writing the static brief, run `$copy-validator` with the `long-form-static` spec when the output is saved to a file:

```bash
python3 marketing-brain/scripts/validate_copy.py \
  --spec long-form-static \
  --file <static-pack.md> \
  --product-dir <product-folder> \
  --report <validation-report.md>
```

## Consumption Rules

Use short sections, visible hierarchy, high-contrast claims, proof callouts, and image concepts that reward a second look. Avoid wall-of-text statics unless the market is highly problem-aware and motivated.

## Quality Bar

A good LFS should make the media buyer know exactly what asset to build and why it should beat the control.

It should also pass deterministic validation for structure, length, CTA, proof section, and claim hygiene.

After validation, run `$creative-scorecard` to rank the static or concept against Signal Strength, Pressure Intensity, Belief Shift Clarity, Mechanism Believability, Proof Density, Creative Visualizability, and Scale Potential.
