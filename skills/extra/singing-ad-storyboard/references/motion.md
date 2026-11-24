# Motion prompts (image-to-video)

One motion prompt per shot, built on that shot's approved still as the start frame.
Works in Seedance 2.x, Kling 3.0, Veo, Sora or any image-to-video model.

## Template

```
[MODEL] — Shot [N] · [time] · "[lyric]"

START FRAME: Image 1 (the approved still for this shot).
[Character / product references as Image 2, 3… only if the model accepts them.]

1. [First visible action, already underway.]
2. [Its reaction or the next action.]
3. [The ending pose that hands off to the next shot.]

CAMERA: [plain words — "slowly moves in on her face", "stays still", "drifts left past the window"].
STAYS STILL: [everything that must not move — background people, furniture, the product].
Smooth natural-speed motion. Faces, hands, hair and outfits stay exactly as in the start frame — no morphing.
SILENT: no dialogue, no singing, no lip movement to words, no music, no sound effects. The song is added in the edit.
```

## Rules

- **2–3 numbered beats.** Prose blends actions into mush; numbering orders them.
- **Every beat must be possible from the start frame.** Don't ask for a person who isn't there
  to walk in from nowhere — start them at the edge of frame.
- **Never describe a referenced character's appearance.** With a reference image, say only
  where they are, what each hand does and their expression ("the person from Image 2 lowers the
  phone, eyes filling"). Appearance words fight the reference and the face drifts.
- **No lip-sync.** The singer is the narrator. Mouths may react (gasp, smile, tremble) but never
  form words.
- **Clip length:** the model's shortest length that covers the shot (usually 4–5s); trim to the
  grid's duration in the edit. Never stretch an action to fill 10s.
- **Body cutaways and product hero shots** move gently: a slow push in, glow pulsing, a drop
  falling — one event, nothing frantic.
- Phone screens and signs: the text must not change. Add `The on-screen words stay exactly the same.`

## Edit handoff (end every project with this, filled in)

> **In the edit**
> - Song is the master track. Lay it first, then cut each shot on its grid timecode.
> - Captions: karaoke style, bold sans, centred at ~55% height, active word highlighted in pink.
> - Clips are silent. Keep them that way.
> - Order: shots 1 → [N]. Product shots: [list].
> - Hook versions: export one ad per hook. Ad A = lead song as is. Ad B/C = hook take +
>   its hook shots, cut into the lead song at Verse 1's first word, then the shared body.
>   Name them [ad]-H1 / -H2 / -H3 so the test results stay readable.
