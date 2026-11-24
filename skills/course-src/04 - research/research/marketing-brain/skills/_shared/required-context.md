# Shared Required Context

Every output skill (FB ads, LFS, UGC, native ads, angles, archetypes) must load this context before generating output.

## Methodology

Load `$market-pressure-context` first. Use the loop:

```
Market signal -> Buyer pressure -> Awareness state -> Belief shift ->
Mechanism weapon -> Proof stack -> Creative asset -> DR copy-chief pass ->
Validation -> Scorecard -> Spend feedback
```

The format does not change the logic. It changes the surface. The asset is still moving belief.

## References

Default: load `references/cheatsheet.md` only. It compresses all 6 master references plus project-specific operating rules and the lever-naming convention.

Load a full reference (`avatar-research-dtc-playbook.md`, `breakthrough-advertising.md`, `boron-letters-halbert-dtc-framework.md`, `kennedy-dr-tactics.md`, `influence-dtc-dr-breakdown.md`, `wundt-psychology-dtc.md`) only when:
- the user explicitly asks to deepen one framework, or
- a first-time campaign architecture is being built from scratch, or
- the cheatsheet's "When to load full reference" line for that framework is triggered.

## Product Packet

Read these from the product folder when available. If a file is missing, proceed with labeled assumptions and mark the missing input as a risk.

- `offer.md`
- `product-info.md`
- `avatar-research.md`
- `archetypes.md`
- `angle-map.md`
- `reviews.md` or `reviews-voc.md` or `voc.md`
- `competitors.md`
- `constraints.md`
- `references.md`

## Control Library

If `marketing-brain/references/control-library/index.md` exists, use it before writing video scripts or LFS. Select 1-3 reference control patterns that match the product's buyer pressure, awareness stage, mechanism, proof stack, and platform. Treat patterns as structural evidence, not swipe copy.

Prefer performance-backed controls over `Pattern-only` controls when both fit. Pattern-only controls can shape structure, but spend-backed controls should carry more weight in launch prioritization.

## Winning Asset Inputs

If the user supplies winning ads, competitor copy, scripts, transcripts, or landing pages, run `$control-intelligence` first. Pull structure and belief movement out, then rebuild around the target product's market signal and mechanism. Do not lift copy.

If supplied assets are batch analyses (multiple ads in a folder), first build or refresh `marketing-brain/references/control-library` with `marketing-brain/scripts/build_control_library.py`, then use the aggregate pattern index as the reference layer.

## Creative Ledger And Feedback

Every launch candidate should be recorded in the product folder's `creative-ledger.csv` with the hypothesis, variable tested, validation spec/status, score, destination URL, and control patterns. Once spend data exists, run `marketing-brain/scripts/performance_feedback.py` and let the diagnosis update the next creative decision.
