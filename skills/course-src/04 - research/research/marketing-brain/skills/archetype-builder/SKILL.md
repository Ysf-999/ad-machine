---
name: archetype-builder
description: Use when clustering DTC research into buyer archetypes, awareness stages, belief states, market segments, objections, desires, or avatar maps for ad strategy.
---

# Archetype Builder

## Purpose

Turn scattered insights into testable buyer archetypes. An archetype is not a demographic persona. It is a buying psychology: desire, belief, objection, trigger, and angle path.

## Archetype Schema

For each archetype, define:
- name
- core desire
- current belief
- hidden fear
- failed solutions
- main inhibition
- awareness stage
- sophistication stage
- proof needed
- mechanism they will believe
- language markers
- behavioral evidence
- trigger event
- best first ad angle
- worst angle to avoid

## Clustering Rules

Cluster by buying psychology, not age/gender unless demographics change the belief or objection. Separate archetypes when they need different hooks, mechanisms, proof, or CTAs.

Use classification data only when it changes the buying psychology: life stage, purchase stage, problem duration, category experience, decision-maker role, trigger event, or failed alternative history.

## Reference Lens

Use `../../references/` as the source of truth:
- Avatar Research: decision-maker vs. user, behavioral/attitudinal/classification buckets, trigger events, pain ladders, frequency/intensity ranking.
- Schwartz / Breakthrough Advertising: awareness, sophistication, mass desire, mechanism.
- Halbert / Boron Letters: starving crowd, market-first selection, AIDA, central selling idea.
- Kennedy: message-market-media fit, differentiation, proof, offer.
- Cialdini / Influence: contrast, authority, social proof, scarcity, commitment, reciprocity, liking.
- Wundt: excitation vs. inhibition, repetition, emotional threshold.

If the user passes `--extreme`, identify the rawest useful version of each archetype: the fear they will not say out loud, the status loss they are avoiding, the enemy they already blame, the insult they privately feel from the market, and the emotional trigger most likely to move action.

## Output Format

Return:
- 3-7 archetypes
- confidence score per archetype
- supporting source evidence
- decision-maker / user / payer notes when relevant
- best channels/sources for each
- ad angle implications
- retargeting implications

## Operator Rule

If two archetypes would receive the same ad, combine them. If one archetype requires a different belief shift, split it.
