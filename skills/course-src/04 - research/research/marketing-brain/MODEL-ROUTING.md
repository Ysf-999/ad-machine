# Model Routing

How to route the marketing-brain workflow across Claude models so token spend stays low without losing creative performance. Routing is a decision made at the orchestrator level (or by the human) before a step runs.

## Default Tiers

| Tier | Model | Use For |
|---|---|---|
| Heavy | Opus | Belief shifts, angle synthesis, control-intelligence on novel ads, copy-chief pass on cold-traffic creative, BOF unlocks, anything where the strategic call is the work. |
| Standard | Sonnet | Most creative output (FB ad copy, UGC scripts, LFS, native prompts) once the angle/avatar/mechanism are locked. The default for skill execution. |
| Light | Haiku | Validation, scoring, file ops, batch reformatting, control-library indexing, status/diff summaries, anything deterministic. |

If unsure, run Sonnet. Escalate to Opus only when a step has been flagged Heavy. Drop to Haiku only when the step is mechanical.

## Step → Tier Map

| Workflow Step | Tier | Reason |
|---|---|---|
| `$market-pressure-context` (cold start) | Heavy | Frames the entire campaign — pay once, reuse. |
| Avatar / archetype synthesis from VOC | Heavy | Belief work, not summarization. |
| Angle map / belief chain construction | Heavy | The angle is the asset. |
| `$control-intelligence` on a new winner | Heavy | Pattern extraction across novel structure. |
| `$control-intelligence` on patterns already in the library | Standard | Library carries the heavy lift; just adapt. |
| `build_control_library.py` (indexing) | Light | Scripted aggregation, no judgment. |
| FB ad copy / UGC script / LFS / native prompts | Standard | Lever choices are locked; execute against them. |
| Variant generation (3rd/4th/Nth variation on locked angle) | Light or Standard | If hook archetype is prescribed, Light is fine. Otherwise Standard. |
| DR Copy-Chief Pass (cold-traffic, BOF, $1M+ spend bets) | Heavy | Sharpening is where performance is won or lost. |
| DR Copy-Chief Pass (MOF iteration, retests) | Standard | Marginal sharpening; Sonnet is sufficient. |
| `$copy-validator` runs | Light | Deterministic spec check. |
| `$creative-scorecard` runs | Light | Rubric scoring against fixed dimensions. |
| Reformatting, file moves, MD index updates | Light | Mechanical. |
| Strategy Notes synthesis on a new pack | Standard | Lever choices are pulled from cheatsheet, not invented. |

## Mode Flag Interactions

- `--lite`: forces Standard tier for creative steps unless the user explicitly upgrades. Skips full reference loads. Pairs naturally with cached cheatsheet.
- `--research-only`: heavy front-loaded (avatar / angle / belief chain), skip Standard creative steps entirely.
- `--creative-only`: assumes the research packet is locked. Default to Standard, fall back to Light for variants.
- `--extreme` / `--unrestricted`: do not change tier. Aggression is a copy decision, not a compute decision.

## Caching Discipline

The cache TTL is 5 minutes. The orchestrator's Cache-Aware Workflow Gate enforces stable cache prefixes — do not break the cache by re-shuffling step order or re-loading already-loaded references mid-run.

- Load `references/cheatsheet.md` once at the top of any creative step. Do not re-load it per variation.
- Load `_shared/*` partials once at first creative step. They are stable.
- Load product packet files once per product session. Do not re-read them per variation.
- Full references (`breakthrough-advertising.md`, etc.) are only loaded when the cheatsheet's "When to load full reference" line for that framework is triggered. They are big — loading them invalidates the cache window for everything after.

If a step needs a tier upgrade mid-run (e.g. an unexpected belief problem surfaces during execution), surface it to the user instead of silently re-routing. The cost difference matters and the user owns that call.

## Escalation Rules

Escalate to Heavy when:
- The avatar or angle has not been written yet.
- The product is in a Stage-5 sophistication market and stale-angle risk is real.
- The user is launching into cold traffic with no prior winners.
- The copy-chief pass is the last gate before a meaningful spend bet.
- Control-intelligence is being run on an outlier winner whose structure is novel.

Drop to Light when:
- The output is structurally fixed (validation, scoring, indexing, reformatting).
- The variation is a swap on a locked frame (e.g. hook archetype B on the same body copy).
- The work is summarization with no judgment call.

## Operating Default

When in doubt: Sonnet for creative, Haiku for mechanical, Opus only when the strategy call is the work. Token cost compounds across a 13-step workflow — getting the tier right per step is worth more than picking the "smartest" model for everything.
