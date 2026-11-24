# Research Project — Codex Instructions

## Marketing Brain: Always Use the Workflow

Before writing any ad copy, script, hook, angle, or creative asset, complete this gate in order. Do not write copy from the user's message alone.

### Step 1 — Pick the Entry Point

If the user is running a full campaign (research → angles → creative), start with the orchestrator:

- `marketing-brain/skills/dtc-research-orchestrator/SKILL.md`

If the user names a single creative task, jump to the matching skill:

| Task | Skill |
|---|---|
| Facebook / Meta ad copy | `marketing-brain/skills/fb-ad-copy/SKILL.md` |
| UGC video script (creator brief or AI talking head) | `marketing-brain/skills/ugc-video-script/SKILL.md` |
| Long-form static / advertorial static | `marketing-brain/skills/long-form-static-builder/SKILL.md` |
| Native ad image prompts (iPhone realism) | `marketing-brain/skills/native-image-prompt-gen/SKILL.md` |
| Angle generation | `marketing-brain/skills/angle-factory/SKILL.md` |
| Avatar / audience research | `marketing-brain/skills/internet-avatar-research/SKILL.md` |
| Offer diagnosis | `marketing-brain/skills/offer-diagnosis/SKILL.md` |
| Copy validation | `marketing-brain/skills/copy-validator/SKILL.md` |
| Creative scoring | `marketing-brain/skills/creative-scorecard/SKILL.md` |
| Control intelligence (winning ad teardown) | `marketing-brain/skills/control-intelligence/SKILL.md` |

Every output skill loads `skills/_shared/required-context.md` first. That file defines the methodology loop, reference loading rules, product packet, and control library.

### Step 2 — Load the Product Packet

If `marketing-brain/products/<product-name>/` exists, read what is present (any of these may be absent — proceed with labeled assumptions):

- `offer.md`
- `product-info.md`
- `avatar-research.md`
- `archetypes.md`
- `angle-map.md`
- `reviews.md` or `reviews-voc.md` or `voc.md`
- `competitors.md`
- `constraints.md`
- `references.md`

If no product folder exists, say so and offer to run the research workflow first.

### Step 3 — Load References (Cheatsheet First)

**Default:** load only `marketing-brain/references/cheatsheet.md`. It compresses all 6 master references plus the project's lever-naming convention.

Load a full reference (`breakthrough-advertising.md`, `boron-letters-halbert-dtc-framework.md`, `kennedy-dr-tactics.md`, `influence-dtc-dr-breakdown.md`, `wundt-psychology-dtc.md`, `avatar-research-dtc-playbook.md`) only when the cheatsheet's "When to load full reference" line for that framework is triggered, or the user explicitly asks to deepen one framework.

Do not bulk-load all references. That was the old default and it burns tokens without lifting performance.

### Step 4 — Check the Control Library

If `marketing-brain/references/control-library/index.md` exists, select 1–3 reference patterns that match the product's pressure / awareness / mechanism / proof / platform. Use them as structural evidence, not swipe copy. The skill specifies how to apply them.

### Step 5 — Honor Mode Flags

See `marketing-brain/skills/_shared/mode-flags.md` for `--extreme`, `--unrestricted`, `--lite`, `--research-only`, `--creative-only`. `--lite` is the default for token-conscious runs; it forces cheatsheet-only references and cached partials.

### Step 6 — Follow Skill Output Format Exactly

Every skill has a defined output format, a Strategy Notes section, a copy-chief pass, and a validation step. Use the format specified in the skill. Do not invent a different structure.

---

## Rules

- Never invent VOC quotes, stats, prices, proof, credentials, scarcity, or testimonials. Use only what is in the product files.
- Constraints are the factual floor, not the creative ceiling. Move risk language into `Launch Notes` and keep selling copy sharp.
- After writing a script or copy asset, tell the user which product files, references, and skill were used.
- If the user asks for a "quick version," still read the product files — just write a shorter output.
- For model routing decisions across the workflow, see `marketing-brain/MODEL-ROUTING.md`.
