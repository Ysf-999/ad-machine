# Micro-expressions and cut rhythm — what makes it hooky

A podcast ad holds attention through **reaction**, not dialogue. The viewer
stays because the other host's face is doing something. Two prompt mechanisms
carry this, and both are per-beat.

## `reaction` — the listener, during a line

Attach to a dialogue beat. Renders as a second line describing the *other*
host reacting while the speaker talks. This is the "nodding, laughing
mid-talking" layer.

```json
{ "host": "B", "line": "Because you keep asking me the wrong question.",
  "reaction": "raises an eyebrow and half smiles" }
```

→

```
@image2: "Because you keep asking me the wrong question."

@image1 raises an eyebrow and half smiles while listening. Mouth closed.
```

`Mouth closed` is appended automatically. Without it the listener lip-syncs
the speaker's line, which is the tell that ruins the shot.

## `action` — the speaker, during their own line

Appended directly after the dialogue. Use for things the speaker does while
saying the line.

```json
{ "host": "A", "line": "See, that's crazy to me...", "action": "laughs it off" }
```

## `silent` — a beat with no dialogue at all

A held reaction shot. Costs screen time, zero words. Put one at the end of
almost every chunk: it gives the cut somewhere to land and reads as a real
pause rather than a hard stop mid-sentence.

```json
{ "host": "B", "silent": true,
  "reaction": "gives a knowing reaction with her mouth closed" }
```

The driver flags any chunk with no reaction or silent beat.

## Reaction vocabulary that renders

Grounded in the proven prompt's own language — small, physical, specific.

**Skeptical / withholding**
- raises an eyebrow and half smiles
- sits back, half laughing, clearly not buying it yet
- tilts her head slightly, unconvinced
- glances away for a beat, then back

**Agreeing / landing the point**
- nods slowly, amused
- gives a knowing reaction with her mouth closed
- gives a knowing look, like she is about to land the point
- small nod, eyes narrowing slightly in recognition

**Surprised / pulled in**
- eyebrows lift, leans a few inches toward the microphone
- blinks twice, caught off guard
- mouth stays closed but her expression opens up

**Warm / mid-laugh**
- laughs it off
- laughs quietly without opening her mouth wide
- shakes her head, smiling

### Writing rules

- **Physical, not emotional.** "raises an eyebrow" renders. "feels skeptical"
  does not.
- **Small.** Tiny eyebrow movements, nods, blinks, glances. Big gestures read
  as acting and break the documentary feel.
- **Vary them.** The same reaction twice in one chunk reads as a loop
  artifact. Three different reactions across a chunk is the target.
- **Never describe the listener's mouth opening.** Ever.

## Cut rhythm

From the proven chunk: **9 beats in 30s**, averaging ~3.3s per beat. That is
the target rhythm — faster than a real podcast edit, which is the point.

The pattern that works is uneven, not alternating:

```
A (short)  →  B (short)  →  B (long)  →  B (long)
           →  A (short)  →  B (short) →  B (long)
           →  A (short)  →  B (silent hold)
```

One host carries the information in 2–3 consecutive `Keep X on screen` beats;
the other punches in with short skeptical one-liners. Strict A/B/A/B
alternation reads mechanical.

**Cut on the reaction, not the sentence.** The strongest cut lands just as the
listener's expression changes — which is why the 2–4 frame pre-roll in the
preamble matters: it puts you on the new face slightly before the new voice.

## Budget

| | |
|---|---|
| Words per 30s chunk | 75–123 (123 is the proven ceiling) |
| Beats per chunk | 6–10 |
| Reaction or silent beats | at least 1, ideally 2–3 |

`driver.mjs budget <spec.json>` prints this per chunk. The `nat.read`
column shows how long the text takes at natural speech and will read longer
than 30s at proven density — that is expected. Gate on words, not seconds.
