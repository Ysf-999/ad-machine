# Prompt anatomy — what the driver assembles, and why

Every chunk prompt is **preamble + beat sheet**. The preamble is identical in
every chunk; only the beat sheet changes.

## Why the preamble repeats in full, every chunk

Wan 3.0 renders each 30s chunk as its own generation. It carries nothing over
from the previous one. If the identity lock, the framing and the cut grammar
are not in chunk 4's prompt, chunk 4 will not have them — the hosts drift,
the camera starts floating, the faces get smoothed.

This is the single biggest cause of a 3-minute ad where chunks 1–2 look great
and chunks 4–6 look like different people in a different room. The driver
handles it: it emits the full preamble every time. Never hand-trim it.

## The eight blocks, in fixed order

The order is load-bearing. Identity before look, look before performance,
performance before cut grammar, negatives late, audio binding last.

### 1. Identity lock

```
Preserve Woman 1 exactly from @image1 and Woman 2 exactly from @image2.
Preserve their real facial structure, skin texture, hairstyle, clothing,
microphone, chair, lighting and podcast environment. Do not beautify or
smooth their faces.
```

`Do not beautify or smooth their faces` is not decoration. Without it the
render drifts toward glossy AI skin and the ad stops reading as a real
recording — which is the whole reason the format converts.

### 2. Extra reference slots

Only emitted when `refs` has entries. A product slot gets the
"exact label, exact typography, exact colour, exact container shape" lock;
a wide slot gets the "seating positions must match the close ups" lock.

### 3. Look

Framing, camera, movement negatives. The default is the proven one:
medium close, chest to top of head, seated eye level, locked tripods, no
push-ins, no floating camera, no background changes. `spec.environment` is
appended here.

### 4. Personas

One sentence per host. These drive *delivery*, not wardrobe. Write them as
character notes — "curious, skeptical, slightly amused", "speaks casually,
like telling a friend something surprising rather than performing an
advertisement." That second phrasing is doing real work: it is what stops
the read sounding like an ad.

### 5. The one-mouth rule

```
Only the woman currently speaking moves her lips. The listening woman keeps
her mouth naturally closed and reacts with tiny eyebrow movements, nods,
smiles, blinks, glances and changes of expression.
```

The highest-value line in the prompt. Without it both hosts mouth every
line and the render is unusable. The nouns are gendered off `spec.cast`
(`women` / `men` / `mixed`) — the proven prompt says "woman", not "person",
and concrete nouns hold better.

### 6. Cut grammar

```
Every speaker change uses an immediate hard cut to that woman's camera. Cut
approximately 2 to 4 frames before her first spoken word so the edit feels
like a real multicamera podcast. Hold the speaker for roughly 0.2 seconds
after her final word before cutting away.
```

The 2–4 frame pre-roll is what makes the edit feel cut by a human rather
than sliced on the waveform. Keep the numbers.

### 7. Negatives, then imperfections

Negatives kill the AI-video tells: crossfades, morphing, split screen,
dramatic zooms, subtitles, background music. Then the imperfections block
*adds back* the human ones: breathing, swallowing, fingers near the mic,
posture shifts. Both halves matter — negatives alone give you a clean,
dead render.

### 8. Audio binding — always last

```
for reference_audio_urls use File 1 for Woman 1
for reference_audio_urls use File 2 for Woman 2
```

Consecutive lines, no blank line between them: they read as one mapping
table. Placed immediately before the beat sheet so the voice assignment is
the last thing the model reads before the dialogue.

## The beat sheet

Timecode header, then one shot instruction + one content line per beat:

```
CHUNK 6
2:30 to 3:00

Start on @image1.

@image1: "That quickly, thats crazyy?"

Hard cut to @image2.

@image2: "For me, that was when I started paying attention though."

Keep @image2 on screen.
...
End on @image2.

@image2 gives a knowing reaction with her mouth closed. No dialogue.
```

Rules the driver enforces:

- First beat is `Start on X.`
- Speaker change is `Hard cut to X.`
- Same speaker continuing is `Keep X on screen.` — **never** silently run two
  lines under one shot instruction; every line gets its own.
- Last beat gets an explicit `End on X.` so Wan holds instead of drifting.
- A silent final beat uses `End on X.` as its shot instruction, not a hard cut.

The blank line between every instruction and every line of dialogue is
intentional. Dense prompts parse worse.
