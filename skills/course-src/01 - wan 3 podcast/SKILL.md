---
name: wan3-podcast-ads
description: Builds Wan 3.0 podcast-style video ad prompts from host images, voice references and a product - two hosts in reference mode (@image1/@image2, File 1/File 2), hard-cut multicam grammar, product inserts, wide two-shots and listener micro-expressions, chunked into 30s generations for any requested duration. Use when the user wants a Wan 3.0 podcast ad, a two-host talking ad, podcast chunk prompts, a 60s/90s/3-minute podcast ad, or wants to add a product or a wide shot to an existing podcast ad. Not for single-speaker UGC selfie ads or non-Wan models.
---

# Wan 3.0 — Podcast Ad Prompts

Generates the chunked prompt set for a two-host podcast ad in Wan 3.0
reference mode. Hosts are locked to reference images, voices to reference
audio, and every speaker change is a hard cut — the format that reads as a
real multicamera podcast recording rather than AI video.

**The driver is the deliverable.** You write a JSON spec; `driver.mjs` builds
the prompts and refuses to emit a spec that would waste a render. Do not
hand-write chunk prompts — the preamble must be byte-identical across every
chunk and that is exactly what hand-writing gets wrong.

## Prerequisites

Node 20+. Nothing to install — the driver has no dependencies.

```bash
node --version
```

## Run (agent path)

The driver runs from any directory. Keep the spec in the working directory and
call the driver by path:

```bash
D=~/.claude/skills/wan3-podcast-ads
node "$D/driver.mjs" scaffold ad.json --minutes 3   # 6 empty chunks
node "$D/driver.mjs" check  ad.json                 # validate
node "$D/driver.mjs" budget ad.json                 # per-chunk word/beat table
node "$D/driver.mjs" build  ad.json                 # all chunk prompts
node "$D/driver.mjs" build  ad.json --chunk 6       # just chunk 6
```

| command | what it does |
|---|---|
| `scaffold <out> --minutes N` | writes a skeleton spec with `N*2` chunks |
| `check <spec>` | validates; exit 1 on errors |
| `budget <spec>` | words, beats and fit per chunk |
| `build <spec> [--chunk N]` | prints complete, paste-ready prompts |

`build` refuses to run while `check` reports errors. That is deliberate — an
over-cap chunk or a crossed audio slot costs a render.

Working examples to copy from (paths relative to this skill directory):

- `examples/two-host-reference.json` — the operator's proven chunk 6. Its
  preamble is verified byte-identical to the prompt that rendered well.
- `examples/product-multicam.json` — 3 chunks with a wide plate, a product
  insert and an in-hand product beat.

## Procedure

**S1 — Intake.** Ask only for what is missing, in one message:

1. Duration — 30s, 60s, 90s, 3 min? This sets chunk count (duration ÷ 30).
2. Host images — one close-up plate per host. Who is on the left?
3. Voice references — one audio file per host.
4. Product image, if the ad introduces one.
5. Wide shot with both hosts in frame, if they have one.
6. The product/offer, the angle, and who the ad is for.

If they hand over a script, skip to S3.

**S2 — Write the conversation.** Read `references/micro-expressions.md` first.
One host is skeptical and curious; the other knows the subject and talks like
a friend, not an advertiser. Land one idea per chunk. Keep each chunk in the
75–123 word band.

**S3 — Build the spec.** Schema in `references/spec-schema.md`. Wire slots per
`references/reference-slots.md`.

**S4 — Validate, then build.**

```bash
node "$D/driver.mjs" check ad.json && node "$D/driver.mjs" budget ad.json
node "$D/driver.mjs" build ad.json
```

**S5 — Deliver.** Give the operator the upload order first, then each chunk
prompt as its own block. State plainly that each chunk is a separate Wan 3.0
generation and the whole block gets pasted every time.

## Duration → chunks

| Duration | Chunks | Words |
|---|---|---|
| 30s | 1 | 75–123 |
| 60s | 2 | 150–246 |
| 90s | 3 | 225–369 |
| 3 min | 6 | 450–738 |

Chunk `n` sets its own timecode header: chunk 6 renders `2:30 to 3:00`. Number
chunks by their real position in the ad, not by build order — that is how you
regenerate a single failed chunk later without disturbing the rest.

## Gotchas

- **The preamble repeats in full in every chunk, and that is not redundancy.**
  Wan renders each 30s chunk as an independent generation and carries nothing
  over. Trim the preamble from chunk 4 and chunk 4 gets drifting faces, a
  floating camera and smoothed skin. The driver emits it every time; let it.

- **Gate on words, not seconds.** The proven chunk is 123 words in 30s — about
  246 wpm nominal, far above natural speech. The `nat.read` column in `budget`
  will say ~48s for a chunk that renders fine. It is advisory only. The word
  ceiling is the number grounded in a render that actually worked.

- **`Do not beautify or smooth their faces` is load-bearing.** Drop it and the
  render drifts to glossy AI skin, which kills the "real recording" read that
  makes the format convert.

- **The one-mouth rule is the difference between usable and unusable.** Without
  "Only the woman currently speaking moves her lips", both hosts lip-sync every
  line. Every listener beat also ends in `Mouth closed.` — the driver appends
  it, do not strip it.

- **Set `cast`.** It switches the pronouns in the one-mouth rule and the cut
  grammar to `woman/her`, `man/his`, or generic. The proven prompt says
  "woman", not "person"; concrete nouns hold better. Default `mixed` is the
  weakest of the three — only leave it for a genuinely mixed cast.

- **Wide shots animate both mouths unless you stop them.** A wide beat with
  `host` set names the speaker inside the frame and explicitly holds the other
  silent. A wide beat without `host` is a silent establishing shot. There is no
  third option that works.

- **Left/right must survive every cut.** Whoever is on the left in the plate
  stays on the left in the wide. Cross them and the cuts read as a chair swap.

- **Slot numbers are upload positions, not names.** `@image1` is whatever you
  uploaded first. `File 1` is the first *audio* upload — a separate sequence
  from images. Cross the audio slots and the hosts swap voices with their own
  faces, which is the worst failure mode here because it looks fine until you
  listen.

- **Strict A/B/A/B alternation reads mechanical.** Let one host hold 2–3
  consecutive beats with `Keep X on screen` while the other punches in with
  short lines.

## Troubleshooting

- **`refusing to build - run check and fix the errors first`**: `check` found a
  blocking error. Fix it; `build` will not emit a spec that wastes a render.

- **`chunk N: X words exceeds the proven 123-word ceiling`**: move a line to the
  next chunk, or add a chunk. Do not compress the dialogue to fit.

- **`reference slots are not contiguous from 1`**: you have a gap like
  `@image1, @image2, @image7`. Upload order cannot match those numbers.
  Renumber the refs.

- **`chunk N has no listener reaction or silent beat`**: add a `reaction` to a
  dialogue beat or a `silent` beat. This is what makes the cut feel real.

- **`host X has no audio slot - Wan will invent a voice`**: intentional only if
  you are generating the voice. Otherwise add `audio`.

- **`spec is not valid JSON`**: usually a trailing comma, or a smart quote
  pasted from a document into a `line` value.
