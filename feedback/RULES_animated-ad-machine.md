# Learned rules — animated-ad-machine (claymation, Pixar 3D, flat 2D, talking character)

Rules learned from owner reviews of animated ads. Read these before writing a beat table or generating frames:
`ad.py <project> rules`. New rules arrive through `feedback.py promote`. Rule numbers continue from the universal file.
What the product looks like and how it is used comes from `brand/brand.json` (`product_look`, `how_it_works`) and
`brand/product-photos/`, never from memory.

- **R026** Instant-change beats (a rinse, a spray, a pour): the action is already touching the subject in frame 1, the change completes by mid-clip, duration 4 s, no "then keeps going" tail (the model invents motion). Prefer a start+end pair whose end frame shows the result.
- **R028** Still-image zoom sequences are rejected for product beats; animate them. Real footage is the fallback for demo shots only if the animated version keeps failing.
- **R029** Build an approved styled reference of the product for each style (Pixar 3D, 2D cartoon, clay) from the real product photos, and use it as the product source for that style; text-only product prompts fail.
- **R030** Demo beats: the product must touch the problem and visibly work on it; the result must never appear while the product is in the air or barely touching.
- **R032** When a failed alternative demo plays, the problem is there before AND after the pass.
- **R033** Competitor or alternative tools are drawn from a real product reference image when the owner supplies one, never a generic stand-in.
- **R034** Demo clips use a start+end pair whose end frame is the same shot with the problem solved; the problem disappears with the action and never spreads or moves around.
- **R035** Our logo on the product stays sharp and readable. Never run an AI edit over a frame once the product is in it, because it blurs the lettering: edit the empty plate, then composite the product last. A product lying on a surface must be foreshortened to the camera angle or it reads as held up.
- **R036** Kling 3.0 clip audio can come in near -51 dB, so `sfx_db` alone gives a silent ad. The owner wants real small sound effects and audible product sounds: generate them with ElevenLabs sound-generation and mix a timed SFX bus after stitch.
- **R037** If Kling keeps getting the demo motion wrong, stop re-rolling. Track the product's position in the liked clip, then either animate the composited product yourself or keep the liked clip's arm and replace the background so the result appears where the product has passed.
- **R038** The owner wants a clean transition from the hook into the body, not a hard cut. Give the last hook clip a start+end pair whose end frame is the first body frame and describe one continuous camera move. Exclude that beat from punch-in cuts in the finish pass.

## agentchad seeds (A-rules; owner can strike any)
Seeded from the free agentchad.io skills (Reality Drama Engine, Trendjack Animator), not from an owner review. Source copies: `knowledge/agentchad/`. The owner can strike any of them; an owner R-rule always wins over an A-rule.
- **A301** Every clip prompt starts with a camera line ("Camera: <move, speed, start to end framing>"); never a static camera. Short shots with a different move each time make 15 s feel fast.
- **A302** Never reuse the same shot twice inside one ad.
- **A303** Knitted, crochet and felt looks default to a white studio background: write "walls fill the whole background edge to edge, no white background" (and "almost completely dark" for a night scene).
- **A304** Looks that animate badly (paper, parchment): two stills (before and mid-action, the second made with the first as reference) cut together look right and cost less than a clip.
- **A305** Same scene in many styles: keep the person, room and action words identical and change only the style block. Start frame = the moment just before the action; the clip = the action.
- **A306** Check contact sheets for: a split frame (a second image in the bottom fifth), a stranger appearing when the prompt says "a hand", and a transparent or glossy item turning into a coloured streak after about 2.5 s (use only the clean start of that clip).
- **A307** Model routing per shot: the cheaper default model for normal shots; the strong model only for emotional close-ups (crying, shock, joy) and product-on-skin/fabric shots (about 1 in 5); a start+end-frame model for big action and moves that must land exactly. The cheap model barely moved a crying face and drew a streak on skin after ~3 s.
- **A308** Narrated cartoon story beats: hook in the first sentence on a close shot (never a calm establishing shot) -> problem, specific and sensory (~15 %) -> one self-blame line ("I thought it was just me") -> failed fixes as a fast montage of 1-1.5 s inserts (~10 %) -> a trusted person shows the answer -> how it works in 1-2 lines, shown literally while said -> payoff as a callback to the hook (~15 %) -> one sweet or funny twist -> offer. Shots 1.2-2.7 s, one per line.
- **A309** Claymation motion lines ask for "slightly choppy stop-motion movement"; smooth motion breaks the look. Watercolor: keep moves slow and simple (fast action smears). Paper cut-out: 2-4 depth layers at most. Felt/wool: frame closer, small details get lost. Never name a studio, film or franchise in a look line.

## Owner rules (continued)

