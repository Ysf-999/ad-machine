# DTC Agentic Research Skill Pack Design

## Goal

Create a project-local Marketing Brain v0 for repeated DTC research runs. The system should help a future Codex session ingest a product packet, research credible market sources, extract voice of customer, classify buyer psychology, generate direct response angles, create long-form static briefs, and expand winners into a scaling spiral.

## Product Philosophy

The pack should think like a profit-responsible 9-figure DTC direct response operator. It should prefer source-backed market truth over clever copy. Its job is to protect spend by finding the true desire, belief state, objection, proof gap, and creative path before assets are produced.

## Architecture

The project contains:

- `marketing-brain/references/`: durable marketing source notes.
- `marketing-brain/skills/`: project-local Codex skills.
- `marketing-brain/templates/product-packet/`: reusable intake files for each product.
- `marketing-brain/products/`: future per-product research folders.

The shared master references are:

- `avatar-research-dtc-playbook.md`: decision-first internet avatar research, trigger events, pain ladders, review mining, frequency/intensity scoring.
- `breakthrough-advertising.md`: awareness, sophistication, mass desire, mechanism, belief chain.
- `kennedy-dr-tactics.md`: offer, CTA, differentiation, proof, guarantee, price framing.
- `boron-letters-halbert-dtc-framework.md`: starving crowd, market-first research, A-pile/B-pile, grabbers, AIDA, order logic.
- `influence-dtc-dr-breakdown.md`: contrast, reciprocity, commitment, social proof, liking, authority, scarcity.
- `wundt-psychology-dtc.md`: attention, inhibition, repetition, creative fatigue, retargeting.

## Skills

- `dtc-research-orchestrator`: runs the full workflow.
- `offer-diagnosis`: identifies offer constraints and scale blockers.
- `internet-avatar-research`: turns internet evidence into decision-first avatar insights, trigger events, pain ladders, and ranked creative decisions.
- `source-discovery`: chooses credible market research sources.
- `voice-of-customer-research`: extracts pains, beliefs, objections, failed solutions, and language.
- `archetype-builder`: clusters research into buyer archetypes and awareness states.
- `angle-factory`: creates and ranks DR ad angles.
- `long-form-static-builder`: turns angles into native static ad briefs.
- `native-image-prompt-gen`: turns static concepts into candid photorealistic iPhone/UGC image prompts for native ads and social statics.
- `scaling-spiral`: expands winners across static formats, AI talking heads, creator briefs, and retargeting.
- `kennedy-dr-tactics`: retained as a project-local skill, with the same framework also available in `references/` for research/copy workflows.

## Data Flow

1. User creates a new folder under `marketing-brain/products/<product-name>/`.
2. User fills product packet files from `marketing-brain/templates/product-packet/`.
3. Orchestrator reads the packet and selects relevant references.
4. The avatar research decision is framed: what decision is being made, what evidence would change it, and which sources can answer fastest.
5. Research sources are chosen and scored.
6. VOC is extracted and organized into behavioral, attitudinal, and classification evidence.
7. Trigger events, pain ladders, failed alternatives, objections, and frequency/intensity rankings are synthesized.
8. Archetypes and awareness stages are built.
9. Angles are generated and ranked.
10. Long-form static briefs are produced.
11. Native image prompt batches are generated when creative images are needed.
12. When performance data exists, winners are expanded through the scaling spiral.

## Error Handling

If inputs are missing, the workflow continues with labeled assumptions and explicit risk notes. If sources are weak, the output must say the research base is weak. If a claim lacks proof, the output must mark it as unsupported rather than turning it into ad copy.

## Mode Flags

Default mode is aggressive but proof-aware. `--extreme` requires explicit confirmation before use, then switches copy and creative strategy into maximum direct-response intensity: sharper hooks, harder contrast, stronger urgency, more visceral cost-of-inaction, more polarizing angle selection, and less platform-safe softening. Outputs must be labeled `Mode: --extreme / User confirmed final review responsibility`. The mode removes creative softness, not factual integrity.

## Testing

Validation should check that each skill has valid frontmatter and no leftover template text. A future live test should run one real product packet through the orchestrator and inspect whether the output contains evidence-backed insights rather than generic marketing advice.

## Scope

This v0 is a folder workflow and skill pack, not a SaaS dashboard. It is intentionally local so the marketing brain can be sharpened before building UI, databases, automations, or scrapers.
