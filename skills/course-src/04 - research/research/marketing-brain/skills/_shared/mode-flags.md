# Shared Mode Flags

Applies to every output-producing skill: `$fb-ad-copy`, `$long-form-static-builder`, `$ugc-video-script`, `$native-image-prompt-gen`, `$angle-factory`, `$archetype-builder`, `$offer-diagnosis`, `$scaling-spiral`.

## Default Mode

Aggressive but proof-aware. DR-first, not compliance-first. Constraints prevent fabricated or unsupported claims; they should not remove pressure, contrast, urgency, enemy framing, market hatred, or cost-of-inaction.

Factual floor (always on, all modes): never invent facts, testimonials, prices, credentials, endorsements, medical outcomes, guarantees, or performance claims.

## `--extreme`

Maximum direct-response intensity after explicit confirmation.

Confirmation rule: if not already confirmed in the conversation, ask once before proceeding:

```
Confirm --extreme: I will write at maximum DR aggression and you own final review/launch responsibility. Continue?
```

After confirmation:
- harsher enemy / failed-alternative contrast
- more visceral pain, cost-of-inaction, social comparison
- favor curiosity, contradiction, urgency, status-threat hooks
- low taste-polishing, high conversion pressure
- no platform-safe hedging unless requested
- launch responsibility shifts to user

Label output:

```
Mode: --extreme / User confirmed final review responsibility
```

## `--unrestricted`

User explicitly asked to remove constraints/claims/length limits. They are taking 100% responsibility.

When using this mode:
- Output the label `Mode: --unrestricted / User takes all responsibility`
- Pass `--unrestricted` to the validator instead of `--extreme`.
- Ignore length constraints, forbidden medical/marketing claim lists, platform compliance.
- Do not add disclaimers or compliance notes.
- Do not lecture. Just deliver.

## Stacking

`--extreme --unrestricted` is valid. Output both labels. Validator gets `--unrestricted`.

`--lite` (orchestrator-level only) can stack with creative-mode flags. Example: `--lite --extreme` reuses cached research and writes maximum-DR creative.
