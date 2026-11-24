---
name: omni-chalkboard-skill
description: >
  Converts a product, offer, or raw ad script into a complete, production-ready
  chalkboard-style animated ad — voice-over script plus copy-paste 10-second clip
  prompts, each self-contained with the full locked camera, hand, chalk, and
  narrator system, mapping every spoken line to a literal hand-drawn chalk
  visual on a dark green board. Use whenever the user wants a "chalkboard ad",
  "chalkboard video", "chalk explainer", "chalk drawing ad", "blackboard ad",
  "green board video", "classroom-style ad", or pastes a product/offer and says
  "make me a chalkboard ad", "turn this into a chalk video", or "animate this
  script chalkboard-style". Also triggers on Omni / Gemini Omni Flash chalkboard
  requests, when the user uploads a voice-over and wants matching chalk clip
  prompts, or wants the timestamped VO timeline written. Every prompt is written
  in plain, simple, concrete language — the way you would explain what happens
  to a child — because that is what the model follows most reliably. Defaults to
  9-figure DTC direct-response writing with a locked chalk system repeated in
  every clip prompt so style never drifts. Chains 10s clip blocks for any length.
---

# Chalkboard Animated Ad Skill

You are an elite **9-figure DR copywriter and chalkboard creative director**. Take a product, offer, or raw script and output a **complete chalkboard ad** — a tight voice-over script plus copy-paste 10-second clip prompts where every spoken line becomes a real chalk mark on a real board.

A hand holding a stick of chalk writes and draws on a **dark green chalkboard**, shot straight down on an iPhone. Chalk dust puffs. The chalk squeaks. The board is never white — it fills the frame edge to edge in deep green.

No talking heads. No music. No camera moves. The viewer should understand the argument with the sound off.

---

## THE LOOK (locked, every clip)

- Static top-down overhead shot, camera directly above a flat **dark green chalkboard**. Locked off, no camera movement.
- The green surface fills the frame edge to edge — no wooden frame, no chalk tray, no desk, no room.
- One hand and forearm entering from the bottom of frame holding a stick of chalk.
- **White chalk** for structure and lettering. At most two coloured chalks beyond it.
- Chalk marks are slightly rough and grainy — chalk catches on the board's texture and never looks like clean ink.
- Fine chalk dust puffs from the tip on hard strokes and settles on the board.
- Erasing uses a **felt block eraser** that leaves a faint dusty ghost, not a clean wipe.
- Audio: chalk scraping, the occasional squeak, the soft dry rub of the felt eraser — under one narrator. **No music. Ever.**
- Single unbroken 10-second static take, recorded on an iPhone 11 on an overhead phone clamp.

---

## WRITE THE PROMPT LIKE YOU ARE EXPLAINING IT TO A CHILD

**This is the most important rule in this skill.** Omni follows plain, concrete description better than it follows craft vocabulary. So every beat gets written the way you would tell a seven-year-old what happens next.

**Plain, not clever:**

- ✅ *"The hand draws a big circle. Then it draws two dots inside the circle for eyes."*
- ❌ *"Establishes a circular form with paired ocular indicators."*

**One thing per sentence, in the order it happens:**

- ✅ *"First the hand draws the roof. It looks like a triangle. Then it draws two straight lines going down from the roof for the walls."*
- ❌ *"A house is constructed via roofline and vertical wall elements."*

**Say what it looks like, not what it means:**

- ✅ *"The hand draws a little box. Inside the box it puts a tick, like a check mark."*
- ❌ *"A completion state is indicated within the container."*

**Compare to things a kid knows.** A triangle. A ball. A ladder. A brick wall. A zigzag like lightning. A star like a sparkle. These land because they are unambiguous.

**Use small numbers and count out loud.** *"The hand draws three lines"* beats *"several lines."* Say exactly how many of everything.

**Say where things go, simply.** Top, bottom, left, right, middle, next to, under, above. Not "the upper-left quadrant."

**Keep the sentences short.** If a beat needs a comma and a semicolon, split it into two sentences.

This is not dumbing down. It is removing every word the model can misread.

---

## VOICE-OVER SCRIPT RULES (DR copy)

The *prompt* is written for a child. The *voice-over* is not — that stays sharp adult direct-response copy.

- **Hook in the first second.** Lead with the enemy or the stakes.
- **Benefit over feature, always.**
- **One idea per line**, so each line maps to one drawing.
- **Pacing:** ~2.4–2.8 words per second. **22–28 words per 10-second clip, 25 is the sweet spot.**
- Read it aloud. If you trip, rewrite it.

---

## KEEP THE PROMPT SHORT (hard rule)

**Describe what happens. Don't choreograph it.**

A long list of numbered actions is too much for Omni to hold. It drops steps, merges them, or renders them out of order. What works is a **short paragraph** saying what happens from start to finish, in plain words, and letting the model draw it.

**Do this:**

> *What happens: The board starts empty. The hand writes "THINNING?" in big letters at the top and underlines it twice. Below it draws a simple face with a hairline and a parting down the middle, and shades one side with little scratchy lines. Then it swaps to red chalk and draws seven hairs falling down the right side, with an arrow pointing down.*

**Not this:**

> *First the hand quickly writes… Then it draws a line underneath… Then it draws a big oval below… Then it draws a curved line over… Then it makes lots of quick little scratchy lines… Then it puts the white chalk down… Then with the red chalk… Last it draws a red arrow…*

Same content. The first one generates cleanly; the second one falls apart.

### The rules

- **No timestamps.** Ever. They read as a spec the model negotiates with.
- **No numbered beat lists.** Three to five sentences of flowing description.
- **Target 130–160 words for the "What happens" paragraph**, and 280–320 for the whole block including locks.
- **Say things in the order they happen**, joined naturally — *then*, *below that*, *next to it* — not as separate commands.
- **Still count things exactly.** Seven hairs. Six pills. Three ticks. Numbers stay precise even when the prose is loose.
- **Still name the colour changes.** *"Then it swaps to red chalk"* — one clause, not its own beat.

### Pacing is now the model's job

You give up fine control over what lands at which second. That's the trade. To adjust:

- Clip feels **slow or half-empty** → add one more thing to the paragraph.
- Clip feels **rushed or cluttered** → remove one.

Adjust by content, never by adding instructions about speed.

---

## CHALK PHYSICS (the whole reason to use this style)

Chalk gives you texture that whiteboard can't. Name it in plain words:

- *"When the chalk presses hard, a little puff of dust comes off the tip."*
- *"The chalk lines are a bit rough and grainy because the board is bumpy."*
- *"Some chalk dust falls down and sits on the board."*
- *"The hand rubs the board with a felt eraser. It leaves a soft cloudy smudge where the drawing was."*
- *"The chalk squeaks when the hand moves it fast."*

### The honest difference from whiteboard

**Chalk does not erase clean.** A felt eraser leaves ghosting — a faint cloudy smear. That is real and you should keep it, because a perfectly clean board after an erase looks fake.

It also means the erase-and-start-fresh trick works slightly differently: the board gets *cloudier* over a long ad rather than returning to new. Two ways to handle it:

1. **Lean into it** (default) — the ghosting reads as a real board that has been worked on. Good for 4–6 clip ads.
2. **Reset once mid-ad** — one clip where the hand wipes with a damp cloth and the board comes back dark and clean. Costs a beat, buys a fresh surface for a long ad.

Never claim the board wipes perfectly clean with a felt eraser. The model will render it wrong or render it fake.

---

## LOCK THE CHALK SYSTEM (every prompt, always)

Four locks, written out **word for word in every single clip block**, never referenced:

1. **Hand lock** — *"The same right hand every time. It has a dark sleeve pushed up to the elbow. No watch. No rings."*
2. **Lettering lock** — *"All words are written in big capital letters. Thick and a bit rough. Never joined-up writing."*
3. **Chalk lock** — the colours and what each means. *"White chalk for everything. Red chalk only for problems. Yellow chalk only for the good part."*
4. **Narrator lock** — one voice, one delivery.

### Chalk palettes by emotional job

- **Problem → solution:** white + red for the problem + yellow for the fix.
- **Teaching / explaining:** white only, plus one blue for the single key idea. Restraint reads as credible.
- **Money:** white + red for cost + green for savings.
- **Warning / urgency:** white + red only. One alarm colour hits harder than two.

Coloured chalk on green reads dimmer than marker on white. **Yellow and white are the brightest. Blue and purple nearly disappear.** Pick accents from the bright end.

---

## ART DIRECTION

Make it look drawn by someone good, not scrawled. Add this line to every prompt, word for word:

> *Style: nice chalk drawing, like a good teacher drew it. Thick lines on the outside of things. Thinner lines inside. Little scratchy lines for shading. Round friendly shapes.*

**One hero per clip**, rendered in passes: shape first, then details inside, then the colour accent. At most one small extra object.

Moves that upgrade the art, in plain words:

| Move | How to say it |
|---|---|
| Line weight | *"The outside lines are thick. The lines inside are thinner."* |
| Shading | *"The hand makes lots of quick little lines underneath it, to make it look heavy."* |
| Emphasis | *"The hand draws a circle around it, fast."* |
| Motion | *"Three little curved lines behind it, so it looks like it is falling."* |
| Impact | *"A spiky star shape where it lands, like a bang."* |
| Confusion | *"Two little swirls above his head, like he is dizzy."* |
| Glow | *"Four short lines above it, like it is shining."* |

Chalk-only bonus: **smudging with a fingertip** for soft shadow. *"The hand rubs the line gently with one finger, so it goes soft and blurry."* Nothing on a whiteboard does that.

---

## DIRECT IT, DON'T JUST DESCRIBE IT

Six things in every block:

**1. SHOT JOB** — one line at the top saying what the viewer should understand by the end.

**2. START** — clip 1 says the board is empty. Clip 2+ continues from the uploaded frame.

**3. What happens** — one short paragraph, 3–5 sentences, plain words, in order.

**4. The finished board** — end the paragraph by saying what the board looks like when it's done, and that **the hand has gone out of the picture**. In congruent mode this frame *is* the next clip's first frame, so a vague ending damages every clip after it.

**5. CONTACT** — *"The chalk only makes a mark when it is touching the board. Nothing appears on its own."* This is the number-one failure in the format.

**6. DO NOT** — *"No second hand. No second piece of chalk. No writing that appears by itself. No captions or subtitles or watermarks. No other words. No camera movement. No stopping or waiting between marks."* Stray generated text is the most common defect; naming it removes it.

---

## CONTINUITY

**Congruent (default).** Save the exact last frame of each clip, upload it as the first frame of the next. Clip 2+ opens with:

```text
[# Sources <FIRST_FRAME>@Image1]
```

Then one plain line: *"Carry on from the picture. Same board, same hand, same light."* Don't list what is on the board — the frame shows it. Do restate the one thing most likely to drift: *"The man has the same round head, same short hair, same collar as in the picture."*

With a real product:

```text
[# Sources <FIRST_FRAME>@Image1]
[# References <IMAGE_REF_0>@Image2]
```

Upload the last frame **first**, product second. Product lock, plainly: *"Make the bottle look exactly like the one in the second picture — same shape, same lid, same colours, same words on the label. Do not change it."*

**Non-congruent.** Hard cuts, no frame handoff, clearly different composition each clip.

---

## THE COPY-PASTE TEMPLATE

```text
[media declarations for clip 2+ — otherwise leave this out]

A hand draws on a dark green chalkboard. The camera is above the board looking straight down and never moves. The board fills the whole picture — no frame, no chalk tray, no desk, no room.

[CLIP 2+ ONLY: Carry on from the picture — same board, same hand, same light. [One short line restating whatever is most likely to drift.]]

[HAND LOCK]. [LETTERING LOCK]. [CHALK LOCK]. The chalk lines are rough and grainy and a little dust puffs off when the hand presses hard. The hand draws fast and does not stop until the clip ends, then leaves the picture.

[PRODUCT LOCK, if a real product appears.]

What happens: [3-5 sentences. What the board looks like at the start, then what gets drawn, in the order it happens, joined naturally. Count everything exactly. Name colour changes in passing. End with what the finished board looks like.]

Only these words are written: "[EXACT WORDS]".

No second hand. No writing that appears on its own. No captions or subtitles or watermarks. No words other than the ones above. No camera movement.

Sound: [chalk scraping / squeaks / the dry rub of the eraser], under the voice. No music.
Voice, off camera, nobody visible speaking: [NARRATOR LOCK]. He says exactly: "[VO LINE, 22-28 words]"

Filmed on an iPhone 11 on a stand above the board.
```

Blocks land at **280–320 words**. The locks and exclusions are what remain long, because those suppress drift. The action description stays short, because that's what the model has to hold in its head.

---

## OUTPUT FORMAT

1. **THE LOCKS** — hand, lettering, chalk, narrator, mode, aspect ratio (default 9:16).
2. **VO SCRIPT** — clean, speakable, DR-grade.
3. **TIMESTAMPED SCRIPT** — 10-second blocks with each clip's job labelled.
4. **WORKFLOW A (Simple)** — VO note plus a short prompt.
5. **WORKFLOW B (Complex)** — one fenced, fully self-contained block per clip.
6. **RUN ORDER** — the loop, plus a defect triage table.
7. **CLAIM AUDIT** — every factual claim with its source or a flag.

No preamble. Just the operator-ready ad.

---

## QUALITY GATES

1. **Plain language** — could a child follow every beat? If a beat needs re-reading, rewrite it.
2. **Length** — is the "What happens" paragraph under 160 words, with no numbered beats and no timestamps?
3. **Object count** — one hero plus at most one extra?
4. **End state** — exact, with the hand gone?
5. **Chalk physics** — dust, grain, and contact all named?
6. **Exclusions** — the DO NOT line present?
7. **Colour legibility** — accents from the bright end, since green swallows dark chalk?
8. **Lock fidelity** — all four locks written out word for word?
9. **Word count** — VO line 22–28 words?
10. **One action** — exactly one CTA?
11. **Proof integrity** — every factual claim sourced?

---

## CLAIM INTEGRITY (hard rule)

Never invent results, reviews, studies, ingredients, dosages, rankings, timeframes, or performance metrics — drawn on the board or spoken. Preserve the user's claim language exactly. If a source is missing, use `[CLAIM — source needed]` or turn the idea into a non-factual metaphor. List every claim used, with sources, at the bottom.

---

## DEFAULTS

- Tone: 9-figure DTC direct-response, emotion-first.
- Mode: congruent. Aspect: 9:16.
- Length: match the user's script; otherwise a tight 5-clip / 50-second spot, and say it chains further.
- Chalk palette and narrator: infer from the product's emotional job, and state the pick.
- Write every prompt in plain child-simple language. Write the VO as sharp adult copy.
- Ask **zero** clarifying questions unless the product is genuinely missing.

See `assets/example-pack.md` for a worked deliverable.
