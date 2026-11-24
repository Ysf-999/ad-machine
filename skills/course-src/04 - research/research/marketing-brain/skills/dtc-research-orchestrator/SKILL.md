---
name: dtc-research-orchestrator
description: Use when a DTC product, landing page, reviews, competitors, or research packet needs full-funnel market research, avatar mapping, ad angles, long-form static briefs, or scaling creative strategy.
---

# DTC Research Orchestrator

## Core Standard

Think like a profit-responsible 9-figure DTC direct response marketer. Do not reward clever ideas unless they can plausibly lower CAC, raise CVR, increase AOV/LTV, or unlock spend. Separate evidence from inference. Never invent voice-of-customer language.

Before running the workflow, load `$market-pressure-context` as the shared methodology. Use its loop: market signal -> buyer pressure -> awareness state -> belief shift -> mechanism weapon -> proof stack -> creative asset -> DR copy-chief pass -> validation -> scorecard -> spend feedback.

If the user passes `--extreme`, first confirm before continuing unless the user already wrote an explicit confirmation. Ask: `Confirm --extreme: I will write at maximum DR aggression and you own final review/launch responsibility. Continue?` After confirmation, use Extreme DR Mode: maximum aggressive framing, sharper contrast, bigger pattern interrupts, blunt problem agitation, stronger urgency, and polarizing angle selection. Label the output `Mode: --extreme / User confirmed final review responsibility`. Do not soften copy for platform comfort or conservative brand safety. Keep one factual floor: do not invent facts, testimonials, prices, credentials, endorsements, medical outcomes, guarantees, or performance claims.

## Inputs

Prefer a product packet with:
- `offer.md`
- landing page URL or page copy
- reviews/testimonials
- competitors and competitor ads
- compliance/claim constraints
- reference ads or creative taste notes

If something is missing, proceed with labeled assumptions and mark the missing input as a risk.

## Reference Selection

**Default: load `../../references/cheatsheet.md` only.** It contains the condensed operating layer for all 6 master references (Schwartz, Halbert, Kennedy, Cialdini, Wundt, Avatar playbook) plus project-specific rules and the lever-naming convention used in Strategy Notes. The cheatsheet is enough for 95% of work.

Load a full reference only when:
- The user explicitly asks to deepen one framework, or
- A first-time campaign architecture is being built from scratch, or
- The cheatsheet's "When to load full reference" line for that framework is triggered, or
- A diagnosis reveals a framework-specific failure (e.g., stalled funnel -> load `wundt-psychology-dtc.md` for the full excitation/inhibition diagnostic).

Full references available in `../../references/`:
- `avatar-research-dtc-playbook.md` - decision-first research, trigger events, pain ladders, review mining.
- `breakthrough-advertising.md` - awareness, sophistication, mechanism, belief chain.
- `kennedy-dr-tactics.md` - offer, CTA, differentiation, proof, guarantee.
- `boron-letters-halbert-dtc-framework.md` - starving crowd, A-pile/B-pile, AIDA, order logic.
- `influence-dtc-dr-breakdown.md` - contrast, reciprocation, commitment, social proof, liking, authority, scarcity.
- `wundt-psychology-dtc.md` - attention, inhibition, repetition, retargeting, emotional sequence.

Never read a full reference "to be safe." Token cost without performance gain.

## Mode Flags

Default mode is aggressive but proof-aware. That means DR-first, not compliance-first. Constraints should prevent fabricated or unsupported claims; they should not remove pressure, contrast, urgency, enemy framing, market hatred, or cost-of-inaction.

`--extreme` means maximum direct-response intensity after explicit confirmation. It should:
- use harsher enemy/failed-alternative contrast when strategically useful
- make the pain, cost of inaction, and social comparison more visceral
- favor curiosity, contradiction, urgency, and status-threat hooks
- keep taste-polishing low and conversion pressure high
- avoid conservative platform-safe hedging unless the user asks for it
- treat final claim review and launch responsibility as the user's job

`--lite` means token-efficient run that reuses cached intermediate outputs from the product folder. Skip any workflow step whose output already exists in the product folder unless the user explicitly asks to refresh it. Use this mode when generating new creative for a product that already has research artifacts. Default to `--lite` whenever the product folder contains `avatar-research.md` and `archetypes.md` unless the user requests a full re-research.

`--research-only` stops the workflow at archetypes (steps 1-7). Use when the user asks for research without creative.

`--creative-only` skips research (steps 1-7) and assumes the product folder already has `avatar-research.md`, `archetypes.md`, and `angle-map.md`. Goes straight to creative generation (steps 9-12). Use when the user asks for new ads/scripts/statics on an already-researched product.

Mode flags can stack. Example: `--lite --extreme` reuses cached research and writes maximum-DR creative.

## Cache-Aware Workflow Gate

Before running any workflow step, check the product folder for the corresponding cached output. If the file exists and the user has not asked for a refresh:

- Load it instead of regenerating it
- Note in the run log: `[CACHED] step N - reused <filename>`
- Continue to the next step

Cache map (step -> file):
- step 1 offer-diagnosis -> `offer-diagnosis.md`
- step 2-5 avatar/VOC/sources -> `avatar-research.md`, `voc.md`, `sources.md`
- step 6 control deconstruction -> `control-intelligence.md`
- step 7 archetypes -> `archetypes.md`
- step 8 angles -> `angle-map.md`
- step 9 fb ads -> `fb-ad-copy-pack.md`
- step 10 LFS -> `lfs-pack.md`
- step 11 image prompts -> `image-prompts.md`
- step 12 video -> `ugc-video-script-pack.md`
- step 14 validation -> `validation-report.md`
- step 15 scorecard -> `creative-score-report.md`
- step 16 creative ledger -> `creative-ledger.csv`
- step 17 performance feedback -> `performance-feedback.md`

In default (non-lite) mode, the cache is informational only - regenerate, but log the prior version was overwritten. In `--lite` mode, treat cache hits as authoritative and skip regeneration.

## Workflow

Apply the **Cache-Aware Workflow Gate** to every step. In `--lite` mode, skip any step whose cached output exists. In `--creative-only`, jump to step 9. In `--research-only`, stop after step 7.

1. Diagnose the offer using `$offer-diagnosis`.
2. Frame the decision-first avatar research plan using `$internet-avatar-research`.
3. Identify credible sources using `$source-discovery`.
4. Extract VOC using `$voice-of-customer-research`.
5. Synthesize trigger events, pain ladders, source quality, and frequency/intensity rankings using `$internet-avatar-research`.
6. If winning assets, competitor controls, scripts, captions, or landing pages are supplied, deconstruct them using `$control-intelligence`. If supplied assets are batch analyses, first build or refresh `marketing-brain/references/control-library` with `marketing-brain/scripts/build_control_library.py`, then use the aggregate pattern index as the reference layer.
7. Build archetypes using `$archetype-builder`.
8. Create angles using `$angle-factory`.
9. Build normal Meta ad copy using `$fb-ad-copy` unless the user specifically asks for long-form statics, native advertorial statics, or LFS.
10. Build LFS briefs using `$long-form-static-builder` when requested or strategically needed.
11. Create native image prompts using `$native-image-prompt-gen` when static ad concepts, UGC frames, advertorial images, or ChatGPT Images prompts are needed.
12. Build UGC video scripts, AI talking-head scripts, dialogue/skit scripts, or video ad packs using `$ugc-video-script` when the user requests video creative, creator briefs, or AI avatar scripts. Require a `Reference Control Selection` section whenever the control library exists.
13. Run a DR copy-chief pass before validation: sharpen hooks, pressure, failed alternatives, mechanism contrast, and CTA while keeping factual integrity.
14. Validate ad copy, LFS briefs, image prompts, video scripts, or claim-heavy outputs using `$copy-validator`. Always use the most specific spec. `product-claims` alone is not enough when a format spec exists.
15. Score creative quality and launch priority using `$creative-scorecard`. The score command must pass the validation gate first.
16. Add launch candidates to `creative-ledger.csv` with hypothesis, variable tested, validation status, score, destination, and control patterns using `marketing-brain/scripts/creative_ledger.py`.
17. When spend data exists, analyze `creative-ledger.csv` with `marketing-brain/scripts/performance_feedback.py` and save `performance-feedback.md`.
18. Expand winners using `$scaling-spiral` only after performance feedback identifies what actually won.

## Output Contract

Every full research run should produce:
- offer diagnosis
- decision-first internet avatar research brief
- source map with credibility notes
- VOC table: pain, desire, belief, objection, failed solution, exact phrase, source
- trigger event map
- pain ladder and frequency/intensity theme ranking
- awareness and sophistication map
- buyer archetypes
- control deconstructions when winning assets or competitor references are supplied
- selected control-library patterns and adaptation notes when creative is generated from winning ad references
- ranked ad angles
- Facebook/Meta ad copy variations when requested or when no copy format is specified
- long-form static briefs
- native image concepts and generation prompts when requested
- UGC video scripts or AI talking-head scripts when video creative is requested
- validation report path for copy/image outputs when applicable
- creative score report path and launch ranking when applicable
- creative ledger row(s) for launch candidates
- performance feedback report when spend data exists
- test plan with success signals
- open questions and risks

## Quality Bar

Prefer one sharp, source-backed insight over ten generic "pain points." A useful insight explains why the buyer has not already bought, what they currently believe, and what ad idea could move that belief.
