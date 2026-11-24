---
name: voice-of-customer-research
description: Use when extracting buyer language, pains, desires, objections, failed solutions, beliefs, anxieties, comments, reviews, Reddit threads, TikTok comments, or forum research for DTC ads.
---

# Voice of Customer Research

## Rule

Extract the market's words before writing the marketer's words. Preserve exact phrases with sources. Mark inference separately.

## Extraction Fields

For each useful source, capture:
- exact phrase
- source link or file reference
- evidence bucket: behavioral, attitudinal, or classification
- pain
- pain ladder level: surface, practical cost, emotional/social cost, identity/status fear
- desired outcome
- trigger event
- current belief
- failed solution
- objection or inhibition
- emotional charge
- identity signal
- awareness stage
- ad-use note

## What Counts As Useful

Useful VOC contains at least one of:
- a specific lived problem
- a failed attempt
- an objection that blocks purchase
- a contradiction between desire and behavior
- a phrase that sounds like an ad hook
- a belief that reveals market sophistication

## Analysis Lens

Use the shared references in `../../references/` for research and copy thinking. Use Schwartz to classify desire, awareness, and sophistication. Use Halbert to validate the starving crowd and mine "nugget notes." Use Kennedy to connect VOC to offer, proof, and CTA. Use Cialdini/Influence to tag persuasion levers already present in the market: authority, scarcity, social proof, reciprocation, commitment, liking, and contrast. Use Wundt to separate excitation from inhibition: what makes them want it, and what stops action.

Use `../../references/avatar-research-dtc-playbook.md` to separate behavior from opinion, hunt trigger events, build pain ladders, score frequency x intensity, and present quote-evidence-implication instead of generic summaries.

## Output Format

Return:
- top market pains
- top desired transformations
- trigger event map
- pain ladder by major theme
- belief map: what they believe now vs. what the ad must shift
- objection/inhibition map
- failed solution map
- frequency x intensity ranking
- phrase bank grouped by emotion
- research gaps

## Guardrails

Do not sanitize language into corporate copy. Do not invent quotes. If sources are weak, say the research base is weak.

Do not turn internet comments or review themes into percentages unless a real sample count is calculated and shown. Use "recurring theme" or "high-intensity theme" when the evidence is qualitative.
