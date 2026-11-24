# PIXAR SONG — Style Definition

Status: **DRAFT — built from frame analysis, not yet validated by generation.**
Validate before relying on it: generate the character sheet + 3 frames (one dark rock-bottom,
one product, one glow-up) on the chosen model, compare against `references/visual-dna.md`,
then mark this file LOCKED with the date and model.

Default model: `nanobanana-2.1` (Nano Banana 2). Cheaper option: `gpt-image-2`. Fallbacks in order:
`nanobanana-pro`, `seedream-5.0-pro`. Avoid `seedream-4.5` — it leaks hex codes
and typos into rendered text.

Every frame prompt is: `STYLE BLOCK` + `LIGHTING LINE` + blank line + `SCENE: …`
The style block and lighting lines are pasted **verbatim**. Only the scene changes.

---

## STYLE BLOCK (paste verbatim in every frame and sheet)

```
A frame from a high-end 3D animated feature film in the style of modern Pixar and Disney animation. Stylized characters with large expressive eyes with real irises and soft highlights, softly rounded facial features and clear readable micro-expressions. Realistic skin with a gentle warm subsurface glow. Richly detailed hair with distinct braids, coils, curls or silver strands. Fabric with visible weave and soft natural folds; gold jewelry that catches the light. Shallow depth of field with a softly blurred background. Rich saturated jewel-tone colors — royal blue, emerald, magenta, burgundy and warm gold. A clean polished feature-film render. NOT a toy, NOT a vinyl figure, NOT anime, NOT a photograph. Vertical 9:16.
```

## LIGHTING LINES (append exactly one, chosen by the shot's beat)

| Beat | Line |
|---|---|
| 1 Shock · 3 Rock bottom | `Lighting: night, cool blue ambient light with a single warm lamp or neon glow, deep soft shadows, moody and heavy.` |
| 2 Sacrifice | `Lighting: warm amber lamp light, nostalgic and tender, soft falloff into shadow.` |
| 4 Messenger | `Lighting: soft warm window daylight, gentle and intimate.` |
| 5 Ritual | `Lighting: raking golden morning sunlight across the scene, warm and hopeful.` |
| 6 Glow-up · 7 Payoff | `Lighting: bright golden-hour sunlight, glowing warm highlights, confident and celebratory.` |
| 8 Close | `Lighting: bright, warm and clean, flattering soft key light.` |

Exterior establishing shots keep the beat's line but may name the source: `a pink neon motel sign`,
`a sunset behind the church steeple`.

---

## CHARACTER SHEET (one per character, 16:9)

```
[STYLE BLOCK — but end with "Horizontal 16:9." instead of "Vertical 9:16."]
Lighting: soft even studio light, neutral and flattering.

SCENE: A character reference sheet on a plain light grey background, four large clearly separated panels of the same character: full-body front view, full-body three-quarter view, full-body side view, and a large head-and-shoulders close-up showing [EXPRESSION]. [LOCKED CHARACTER DESCRIPTION — age, build, skin tone, face shape, hair, the complete outfit head to toe, jewelry]. Identical face, proportions, hair and outfit in every panel. No text, no labels, no logos.
```

**Transformation version** (when the story has a glow-up): generate the "after" sheet with the
accepted "before" sheet as Image 1 and this line added to the scene:
`The same person as Image 1 — identical face, eyes, skin tone and identity — now slimmer and radiant, hair freshly styled, wearing [AFTER OUTFIT]. Change only the build, hair styling and wardrobe.`

Name the complete outfit head to toe. Models add nothing you don't name.

---

## FRAME TYPES (the SCENE changes shape by type)

**Story frame** — characters acting in a location.
`SCENE: [shot size in plain words: "really close on her face", "both of them, head to toe", "wide, the whole room"]. [Who, by reference: "the woman from Image 1"]. [One action, one expression]. [Setting and props]. [Accent: one jewel-tone pop named explicitly]. Only the characters named. No text, captions, logos or watermarks.`

**Detail insert** — a hand, a ring, feet on a scale, a doorknob. No faces.
**Phone screen** — say the exact on-screen words in quotes and nothing else on the screen.
`The phone screen shows an incoming call from "Marcus" and nothing else.`

**Body cutaway** — the mechanism, same render, never a diagram:
`SCENE: Inside the human body, rendered as a glowing stylized 3D animated world in the same feature-film style: [a translucent x-ray glow over the woman from Image 1 showing soft glowing yellow buildup in her belly and arms | a warm tunnel of soft pink tissue | a single golden drop of oil cracking open a pearly bubble wall]. Soft volumetric glow, magical and clear, not gory, not a medical diagram. No text or labels.`

**Product hero** — product photo as the last reference image:
`SCENE: The product from Image [N] standing on [a warm wooden kitchen counter], label facing camera, its shape, colors and label artwork exactly as in Image [N] — do not redesign or retype the packaging. [Context: morning sun, a coffee mug softly blurred behind]. The product is the sharpest thing in frame.`

**Product in hand** — `the woman's open palm holding two of the softgels from Image [N]` / `a hand setting the pouch from Image [N] on the counter`.

---

## Rules that broke things elsewhere — apply silently

- Never use photo jargon: "bloom" renders flowers, "grain" renders wheat, "flare" renders fire.
  Say "a soft glow", "softly blurred".
- One main action per frame. One accent pop per frame.
- No text unless the shot needs it (phone screen, motel sign). Spell exact words in quotes.
- Never let the frame contain captions — those come in the edit.
- With reference images, describe identity only by reference ("the woman from Image 1").
  Restating her appearance in words fights the reference and drifts the face.
