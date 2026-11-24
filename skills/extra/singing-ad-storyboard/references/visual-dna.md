# Visual DNA — what the proven singing ads actually look like

Measured 2026-10-14 from the five top-scoring singing ads on the GetHookd True Nutra board
(Ancient Roots 173951951 · score 100; Resilia 204501909, 204501459, 204501728 · 62;
Resilia 203067471 · 50). Videos, lyrics and the breakdown deck live in
`Ad Creator's Lab/Singing Ads Breakdown/`. Every rule below came from those frames.

## Story — 8 beats, always in this order

| # | Beat | What happens | Typical share of runtime |
|---|---|---|---|
| 1 | Shock line | First sung line is a betrayal, humiliation or tragedy. No product. | 2–8% |
| 2 | Sacrifice | What the hero gave before it went wrong. Optional — Ad 5 skips it. | 10–25% |
| 3 | Rock bottom | Mirror, parked car, motel, doctor who shrugs, everything they tried. | 10–15% |
| 4 | Messenger | Sister / brother / church friend / a pouch found in a cabinet reveals the hidden cause. | 10–20% |
| 5 | Ritual | The product as one daily habit, sold by taste and feel. | 3–8% |
| 6 | Glow-up | Week-by-week visible wins. | 10–15% |
| 7 | Revenge payoff | The person who hurt them sees it. A stranger asks "what are you on?" | 5–15% |
| 8 | Close | Singer turns to the viewer, restates cause + ritual, offer. | 10–15% |

## Cut rhythm (measured with scene detection)

| Ad | Shots | Avg shot | Median | Opening shot |
|---|---|---|---|---|
| Ancient Roots (100) | 497 | 1.65s | 1.37s | 0.9s |
| Resilia "10 pounds" (62) | 153 | 3.06s | 2.28s | 3.4s |
| Resilia "stepmom" (62) | 222 | 2.09s | 1.43s | 2.6s |
| Resilia "wife's Instagram" (62) | 110 | 3.66s | 2.27s | 6.5s |
| Resilia "lingerie" (50) | 91 | 2.79s | 1.53s | 5.9s |

- Cuts follow the lyric, not the bar. One shot per sung line is the spine; dramatic lines get
  2–3 quick shots; quiet runs hold one shot across two lines.
- The best scorer cuts fastest (~1.7s). That is the `fast` pace in `scripts/beat_grid.py`.
  The others sit near 2.8s — the `standard` pace. Fast doubles the number of frames to make.
- The opening shot usually holds the whole first line.

## Render style

Modern Pixar / Disney feature animation, not toy-like and not anime:
- Large expressive eyes with real irises and wet highlights, soft rounded features, readable
  micro-expressions (brow tension, trembling lip). Faces carry the story at full-screen size.
- Realistic skin with gentle subsurface glow; richly detailed hair — braids, coils, curls,
  silver hair for elders — each strand group readable.
- Fabric with visible weave and folds; gold jewellery (hoops, rings, chains) catching light.
- Shallow depth of field, softly blurred backgrounds, polished clean render.

## Lighting tracks the emotion

| Beat | Light |
|---|---|
| Shock / rock bottom | Night, cool blue, a single warm lamp or neon sign; deep shadows |
| Sacrifice | Warm amber lamp light, nostalgic interiors |
| Messenger | Soft warm window daylight, kitchens and living rooms |
| Ritual | Raking golden morning sun across a counter |
| Glow-up / payoff | Bright golden-hour sunlight, sunsets, string lights |
| Close | Warm, bright and clean |

## Colour and wardrobe

- Jewel tones throughout: royal blue, emerald, magenta, burgundy, gold.
- "Before" wardrobe is muted or oversized (cardigans, knits, robe). The "after" version is the
  same face and identity, slimmer and glammed up, in a fitted red, magenta or burgundy dress or
  a sharp black suit, hair done.
- Villains dress sharp and confident (green blazer, tailored suit) — the viewer reads status.

## Cast

The hero mirrors the buyer: in these ads, Black American women 40–70 (one male POV). Elders
appear as the parent or messenger. Always cast from the user's buyer, never from these ads.

## Shot library (each seen repeatedly across the five)

1. **Peak-emotion face close-up** — wide eyes, tears held, mouth open in shock. The most used shot.
2. **Two-shot confrontation** — villain towering or turning away, hero small in frame.
3. **Hand / detail insert** — hand on a door frame, ring on a finger, feet on a bathroom scale.
4. **Phone screen** — a name on an incoming call, a photo on a feed, a text. Short exact text.
5. **Establishing exterior** — neon MOTEL sign at night, church steeple at sunset, a porch.
6. **Mirror or glass** — reflection in a mirror, seen through a restaurant window.
7. **Body cutaway** — the mechanism made visual: a translucent x-ray glow over the body with
   glowing yellow buildup in belly and arms; stylised organs (liver, intestines); a tunnel of
   tissue; a golden drop of oil cracking a bubble wall; a tiny glowing capsule flying through
   the body. Same Pixar render, never a medical diagram.
8. **Product hero** — the real product on a kitchen counter in raking gold light, label legible.
9. **Product in hand** — two softgels in an open palm, a dropper held up, a pouch set on a counter.
10. **Glow-up walk** — from behind or through glass, dress flowing, heads turning.
11. **Celebration** — cookout, string lights, family table, grandbaby held up.
12. **Stranger reaction** — a woman holding a door asks "what are you on?"

## Captions (added in the edit, never in the frames)

Burned-in karaoke captions, centred around 50–60% height: bold sans, white with a dark shadow,
the active word in a pink/magenta box or the full line in bold white. Frames must carry no text.

## Audio

The song is the only audio. Characters do not lip-sync — the singer is the narrator. Generated
clips must be silent.
