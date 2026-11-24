# agentchad.io free skills (reference copies)

The three free skills from agentchad.io (Armandas Puckus), downloaded from agentchad.io /downloads/<name>.zip (no email
needed). Kept here as reading material. They are built on Starpop + Atria, not kie.ai, and their triggers overlap our
own skills, so two of them are NOT installed as skills.

| Skill | Status | Why |
| --- | --- | --- |
| multi-market-agent | reference copy here; install it as a skill if you want ad translation | Real gap: translating/dubbing finished ads (demucs bed, ElevenLabs voice locked to the original cuts, new captions) |
| reality-drama-engine | reference only | Overlaps ugc-talking-head + drama-ad-machine; Starpop-only tool calls. Ported: A001-A010, A101-A108, A201-A205 rules, assembler -> tools/av_check.py, joiner sync fix in tools/assemble_ugc.py |
| trendjack-animator | reference only (MIT parts, see its LICENSE/NOTICE) | Overlaps animated-ad-machine + song skills. Ported: A301-A309, A401-A407 |

Not ported on purpose (clash with owner rules or our course setup): "never change clip speed" (course: Kling 1.1x),
"top-of-funnel ends without a sale line", "never present an AI person as a real expert / check platform rules"
(owner: invented authority figures are fine, no compliance hedging), its own caption style, the Meta upload steps
(Meta is read-only), and all affiliate sign-up links.

Worth reading when stuck: reality-drama-engine/templates/prompts.md (Omni prompt templates: talking clip, dialogue
turn, reaction shot, frozen voice sentence, room sound lines) and trendjack-animator/looks.md (15 style blocks).

Format recipes in `trendjack-animator/formats/` (not ported as presets because the owner
limits styles to the course): `explainer-3d.md` (3D "how it works" cutaway on one studio stage, 4-8 shots: question,
surprise, into the object, mechanism, back out, product), `skeleton.md` (cartoon skeleton / X-ray overlay demo),
`narrated-story.md` (beat shares, now A308), `drama-song.md` (7 sung lines, same as our singing-drama 7 beats),
`product-song.md` (song shape + genre-by-buyer table, now A405-A406). Useful if the owner asks for an X-ray or
how-it-works ad.
