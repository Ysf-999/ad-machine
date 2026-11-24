# Video-ad editing playbook (from "Video Ads Mastery" + "Video Editing Breakdowns")

Source: an agency course by Carlo (Ecom Talent)
plus breakdowns by its editors: 17 lessons in "3 Video Ads Mastery" (A01–A17) and 9 in "4 Video Editing Breakdowns" (B01–B09),
about 10 hours in total. Each lesson was transcribed (Whisper) and read with its screen frames (Sonnet, every 15 s, outside
the session). Per-lesson notes are in `lesson-notes/`, transcripts in `transcripts/`, videos in `course/07 - …` and `course/08 - …`.
Re-run with `tools/course_ingest.py knowledge/video-editing-course`.

**Why this matters to us:** three breakdowns (B03/B04/B05, B07, B08) edit ads for **Dog Friendly Co**, a pet brand selling a
no-pull harness to women aged about 25–60+. Those ads had real spend. Treat their numbers as the strongest references in this file.

Tags: **[AUTO]** = done by a tool (named), **[JUDGE]** = the agent or the owner decides (say what to check), **[NLE]** = needs a
GUI editor or a paid desktop app we don't run. Rule ids (C0xx) are the seeded rules in `feedback/RULES_raw-ugc-editor.md`.

---

## 1. Before touching footage

- Read the brief's **ad type and example ad first**: the example sets captions, style, rhythm and pacing (B03). Then the
  colour-coded line notes: each script line gets one visual idea (B03, B05). [JUDGE]
- Keep the **buyer in your head while editing** (B06, B07): their age sets the pace (§6) and the music (§8). [JUDGE]
- **Style follows the buyer's feed, not what looks cool** (A01, A02). Raw phone footage often beats polished: "sometimes the
  worst looking ad is actually the better ad" (A01). Mediocre high production is worse than good organic (A09). [JUDGE]
- Know the library. "Some of the best ideas come from knowing the content" (A13). Keep footage local and organised by creator
  (A13); download creator footage including past batches, because "running out of b-roll is your worst nightmare" (B06).
  [AUTO: `footage/INDEX.csv` + `rawedit.py broll`]
- Plan b-roll **before** opening the editor: a two-column table, script line | the exact clip (B09). [AUTO: `rawedit.py broll`
  + STORYBOARD.html is this table]

## 2. Ad types and structures

- **Every brief ships as 3 hooks + 1 hold = 3 ads**; only the hook changes, the hold is identical (A04, A06, B03, B06, B07).
  Some briefs use 2 holds or 2 CTAs when the hooks' context differs (A08, B08). [AUTO: `rawedit.py variant`]
- **Organic** (A02, A04): looks like the creator made and edited it herself. Testimonials run nearly as-is (cut silences, maybe
  basic captions). Social-style = iPhone, home, a POV text overlay she could have typed. Copy sounds like the person, not the
  brand ("I finally found something that helps…", not "try our revolutionary…"). Show an *achievable* person from the audience.
  One creator per organic ad: a second face makes viewers skeptical (B07).
- **UGC** (A05): an honest friend's recommendation with strategy. One workable order: Hook → Problem → Twist the knife →
  Product intro (an "aha", never forced; a pre-emptive objection handle works) → Feature tied to benefit → Bad alternative →
  Results (specific proof) → CTA. Variants: lead with results for results-led products; drop "bad alternative" for unique
  products; a 30 s silent demo for show-don't-tell products.
- **VSL** (A07, B09): for education-heavy, older buyers (they tolerate 5 min). Hook (struggle + shocking twist) → problem
  amplification → hope spot (a discovery story) → gradual solution (mechanism → simple science → proof → cliffhanger). B09 arc:
  curiosity story → reveal → mechanism → problem → product → benefit stack → CTA.
- **Text-only organic** (A04, B08): no VO; music carries the "internal monologue". Layer order flips: music → text cards →
  b-roll. Cut each card on the beat; same screen area every card; at least ~3 s per hook card, 5 s for a two-part hook, because
  older viewers read slowly; a two-word card can be ~1.8 s (B08). [NOT BUILT YET: see §13]
- **High production** (A09): only for premium positioning, eye-bought products or long-term brand assets. Not the default lane for a direct-response ad.
- **AI-VO + product b-roll** is a proven winner format: brand footage + AI script + AI VO, no creators (A17, A06 Dr. Squatch style).

## 3. Hooks (A11, B07, B08, B06)

- About 3 s to win. A great demo at second 10 is worthless if nobody gets there (A11). Most editors spend hours on the hold
  and five minutes on the hook: "If your hook is shit, your hold is wasted" (B07). [JUDGE]
- **Half-second test:** a viewer scanning for 0.5 s must understand what's going on. One focal point, readable at arm's length.
  Intrigue ("I need to know how"), never confusion ("what am I looking at") (A11). [JUDGE: `hook-lab`, `video-ad-checklist`]
- **Hook text is its own element, not a caption.** It says why to care. It is **on screen from frame one with no animation**
  (no slide-in: by then the viewer is three videos down), clean, slightly bigger than captions, top of the frame where it does
  not fight the visual (A11). Built as a native-looking rounded box (white box, black text; Figma PNG; padding 40/20, radius
  ~21, tilted ~1.2° so it looks phone-made) (B05, B06, B07). [AUTO: `rawedit.py` hook box, C009]
- **Condense rambling intros** into number/result + who it's for + an authority label; "THIS" in caps can replace the reveal:
  "I replaced two hours of cardio with 15 minutes of THIS" (A11). [JUDGE: `hook-lab`]
- **Negative line over a positive visual** creates dissonance and an open loop: "I regret getting this" over the dog happily
  putting on the harness (B07). Hook b-roll shows the pain point immediately, then the mechanism *being attached but not
  explained*, which opens "how?" (B08).
- **Test messaging OR visuals, never both** (A11). Message test = same video, 3 hook texts aimed at 3 desires. Visual test =
  same text, 3 hook visuals (before/after, the struggle, the result). A winner becomes the baseline; make three more of the
  winning type. [AUTO: `rawedit.py variant --hook-card` (message) / `--keep` (visual), C012]
- If the creator gave only one hook line, vary the hook *visual* instead (talking, unboxing, product missing) (A06).

## 4. A-roll and voice (B03, B06, B09, A07)

- **Fix the main audio first; everything sits on it** (A07). Layer order: A-roll/VO → music → b-roll → animation/transitions
  → captions/text → SFX (B06, B07). **Finish each layer before starting the next and don't revisit it**: layers 1-3 are the
  content, 4-6 only enhance (B02). Choose the music before cutting if it has drops, so the edit sits on them (B02).
  [AUTO: `rawedit.py render` order]
- **No silences:** cut gaps, breaths and fillers; keep the best take of the hook; cut from the back on long takes (B06). But
  don't trim too tight: leave a small natural breath (B06). Trim over-long pauses to about half, not to zero (B03).
  [AUTO: S001/S002 silence-anchored edges]
- **Keep a deliberate gap before the word you want to land** ("Records that had stood for years… gone.") (B09) and a
  **bigger pause before the CTA** so the story feels finished (B03). [AUTO: `cta_beat` + C008; landing-word gaps = JUDGE in keep ranges]
- **Levels:** VO peaks −3 to −6 dB on the meter, never into 0; music and SFX sit lower (B03). Flatten single loud words with
  a keyframe dip (B03). **Chain:** Multiband Compressor "Broadcast" → (De-esser: low voice 4.7 kHz, threshold ~−30 dB) → Hard
  Limiter −6 dB (B06, B09). [AUTO: C004 `voice_chain` = highpass 80 Hz, compressor 3:1, de-esser, loudnorm; S008 −14 LUFS]
- Three review passes, one of them a **blind listen** (eyes off the timeline) (B03). [AUTO: `rawedit.py verify` re-transcribes
  every seam; the owner's blind listen stays JUDGE]

## 5. AI voiceover (ElevenLabs) (A17, B03, B05, B07, B09) — for the AI pipelines

- Model **Eleven Multilingual v2** ("stability over new features"; v3 was alpha) (B07, A17). Studio project with one chapter
  per hook + one for the hold + CTA (A17, B07). Hooks as separate files, body as one block (B03).
- **Settings:** start near Stability 35, Similarity 40, Style 15, Speaker boost on, and tune per voice (A17). Too much stability
  = robotic; too much style = tired/fast/loud (B03). Calibrate once; changing settings mid-generation re-renders everything (B07).
- **Text is the biggest lever** (A17): merge lines that are one thought (separate lines make awkward pauses); CAPITALISE the
  stressed word; remove commas that create unwanted pauses; " - " for a connected beat, "…" for a pause; "!" for energy; join
  list items with commas, not full stops; add spoken connectors ("and so", "basically", "so get yours today"); **delete stage
  directions** like "(short pause)" — they get read aloud; use `<break time="1s" />` instead. Lowercase first letter = the
  line continues the previous one (B03). A falling end intonation sounds generic (B03).
- **Domains and brand names:** write them phonetically ("dog friendly koh dot com") (B03).
- **Regenerate the weak line, don't patch it** (B03, A17). Listen to the joined chapters back to back (A17).
- **Voice cloning:** clone the creator voice of a winning ad (Instant Voice Clone, file < 10 MB, isolate the voice from music
  with vocalremover.org first) (A17, B07).
- [AUTO already: `tools/voice_design.py`, `ad.py vo`. Not yet: a text-prep lint for the rules above, see §13]

## 6. Pace and retention (A12, A06, B05, B08)

- **Open a loop in the first seconds and stack new loops** (each reveal raises a new question); **hold the product back** until
  the viewer is waiting for the answer, or they go into skeptic mode (A12).
- **Don't front-load effort.** A fast hook followed by an energy drop loses trust; be "obsessive about every frame" (A12).
- **Visual variety: "never let your eyes get comfortable."** For ads, something changes every 2–3 s (b-roll, new text, new
  angle, a punch-in, a product shot) (A12); Dr. Squatch style = new visual about every 2 s (A06); the Dog Friendly Co cuts run
  a clip every 1–3 s (B05, B08). **Match pace to age:** Gen Z every second; people in their sixties lose track with hectic
  edits (A12). [AUTO: C002 cadence audit in `plan` and `verify`, ceiling `max_static` 3.5 s]
- **Every visual switch needs a purpose:** close-up for emotion, wide for scale, reaction for authenticity (A12).
- **Progress psychology:** a visible timer before a result ("see results in 15 seconds"), a progress bar that fills per
  testimonial, a countdown before a VSL reveal (A12). [NOT BUILT: §13]

## 7. B-roll (B05, B06, B07, B08, B09, A15)

- **B-roll shows what is being said** and breaks the talking-head monotone (B06). A literal match is best; in a VSL an abstract
  match is fine if it carries the idea (B09). [AUTO: `rawedit.py broll` keyword match + JUDGE]
- **Lead with the pain point** right off the bat; after the turning point the b-roll shows the solution working (B07, B08).
  **Force-show the mechanism** on the mechanism line (B03, B05). [JUDGE]
- **Same creator in UGC/organic** (her own b-roll reads as one person's journey; agency saw better results) (B06, B07). Dog
  Friendly Co VO ads mix creators and use **before/after pairs filmed in the same place** to read as an instant change (B08).
- **Clip length = line length.** A clip that ends before its line is a flash with no information; a visual longer than ~3 s
  becomes two clips (B05). Stretch a slightly short clip by duration, keeping slow-downs mild (88–92 % is invisible) (B05).
  [AUTO: `set-broll` slows a clip up to 12 % short, C006]
- **Start and end each clip on VO phrase boundaries** (B05). [AUTO: b-roll offset inside the beat]
- **Split screen** for the first contrast: top = bad (dog pulling), bottom = good (calm walk), each half 1080×960, seam at 960,
  both halves inside the safe zone (B07); results as before-top/after-bottom (A05). [AUTO: `set-broll --split`]
- **Screen direction:** if the same action is filmed from the other side, flip it so the hand and clip stay on one side (B07).
  [AUTO: `set-broll --flip`]
- **Keep the creator on screen while b-roll plays:** cut her out and key her small over the b-roll (a TikTok-reaction look
  that reads as self-edited), and toggle the layout per scene: keyed small over b-roll, full frame, over a still, none (B02).
  [AUTO: `set-broll --pip` = a rounded picture-in-picture box, right side, above the captions; only useful when the creator's
  face is on camera]
- **Hook visual from a relatable feeling:** search TikTok for the feeling ("when your coffee gets cold"), mute its audio, put
  the creator over it (B02). Pinterest stills that look like something she took; the same object across shots (B02).
- **Negative claims show the competitor in a bad light** (a Yeti/Stanley clip on "metallic taste"), then switch back to the
  product when the script pivots (B02). **Time-of-day labels** (6am, 9:30am, 2pm, 7pm) visualise "lasts all day" (B02).
- **When there is no visible problem/solution demo, sell identification and lifestyle:** "50 % of selling this cup is just
  lifestyle"; close on aesthetic shots of the avatar using it (B02). Don't fake product footage you don't have (B02).
- **Social proof collage:** four creators/breeds in quadrants (scale 50 %, centres 270/810 × 480/1440) on the "400,000 owners"
  line (B05). [NOT BUILT: §13]
- **Authority inserts:** a graph, article screenshot or meme over the speaker's upper-middle on a claim, with one pop SFX (B06);
  a yellow Multiply highlighter on key words of screenshots; quick cuts between several screenshots (B09). (Only stats you can source.)
- Sourcing: brand footage first; then TikTok keyword search (plain words: "dog pulling", "lead pulling"; switch VPN country if
  results are weak) and Google's "Short videos" tab; avoid famous creators; pick by first frame — POV, stable on the subject,
  action visible; remove burned-in text (Vmake) (A15, B05, B08, B09). Upscale low-res clips (Topaz; 360×640 is unusable, upscale
  4×; Iris for faces) and keep upscaled clips short (A16, B09). [NLE/paid apps; our library already has 395 clean clips]

## 8. Music (A14, B04, B05, B07, B09)

- Music "gives soul to the ad"; same script + different music = a different ad (A14, B07). **Start from the brief's message**
  and the buyer: what music do they already consume? (A14). Dog-friendly default = calm and friendly; the winning reference
  used upbeat rock to push pace (B03/B04). Old-dog sadness gets sad music (A14). No music is valid for a raw, sensitive talk (B06).
- **Instrumental only** so vocals never fight the VO (B04, B07). [AUTO: music_lib separates vocals from trendy/popular songs; the instrumental plays under VO]
- **Audition properly:** click through the whole waveform, not the intro; search by mood words, not genre ("upbeat positive",
  drop "advertising", which brings an ad feel); keep going until it fits "100 % without hesitation" (B04).
- **Land the beat drop at the start of the hold** (B04, B07; text-only: first hold card on the drop, B08). [AUTO: C003
  `render --music-drop <s>|auto`, `hold_beat`]
- **EQ the music, then lower it:** notch the mids where speech sits (Simple Parametric EQ 1500 Hz, Q 4, −15 dB) and then
  −6 to −8 dB, or about −20 dB for an untreated organic bed; EQ first, volume second, or the mix goes flat (B04, B05, B07).
  [AUTO: C005 `music_eq`; S008 music 8 dB under the voice, checked by `audio_check.py`]
- **Drop the music completely on the line that must land, bring it back after** (Oats Overnight: music stops on "that's
  delicious", returns for the CTA) (A14). **Change the music at the story pivot** (hectic problem → calm lo-fi solution,
  CarePod) (A14); one track with several moods mapped to sections (B09); hectic hooks, tranquil hold (A08). [AUTO: C007
  `music_stops`; section changes = JUDGE (pick a track with the mood change, or two tracks, not built)]
- End on the track's natural ending under the CTA, or a fade (B04, B09). [AUTO: 1.5 s fade]
- Sources: Artlist (mood filters, exclude moods with minus), Epidemic, Extreme Music, TikTok Creative Center → Trends → Songs
  by country (7/30/120 days) (B04, B07). For us: the free local library `library/music/` (`tools/music_lib.py`, added
  2026-11-05): `trendy/`, `popular/` and `library/<mood>/` (Mixkit seed), every track measured (tempo, key, energy, drop)
  and mood-tagged (happy, sad, intense, calm, funny, inspiring, suspense, holiday, heartfelt). Plans set `music_mood` (+
  `music_kind`); both editors pick the least-used fit, songs with vocals play as their Demucs instrumental (§8 instrumental
  rule) unless `music_vocals: true`, and hook variants reuse the base track. `tools/music.py` (kie) beds cost credits: ask.

## 9. Motion (B06, B08, B09, B05)

- **Hide jump cuts by alternating scale:** 100 → 110, a very abrupt cut 112; below ~103–106 is invisible; don't ping-pong
  106/112 all ad long (B06). **Emphasis zoom (112) on the key sentence** (B06). [AUTO: C001 `punch_in`, C001b mid-line
  `auto_punch`, beat `zoom`]
- Subject at the frame edge → a **directional punch-in** toward it (B05). [AUTO: beat `zoom_anchor` [x, y]]
- **Fake dolly** on the most important claim: scale 80 → 50 % (a slow push/pull), subtle (B08). Zoom several stills together
  (one adjustment layer, 100 → 112 %) (B09). Reverse a clip for the product intro (pouches fly back up) (B09). Mosaic for "the
  secret", invert for "the bad thing" (B09). Parallax from a still (subject 100→115 %, background 100→106 % over 10 s) (B09).
  [NOT BUILT except via ffmpeg one-offs; §13]
- Keep organic/UGC bodies simple: "no fancy effects" (B07); the only animation in B08 was one dolly.

## 10. Text, captions and safe zones (A03, B05, B06, B07, B09, A07)

- **Safe zone:** everything important (hook text, captions, product, faces) inside the green zone; nothing under the right
  button column or the bottom band (caption, name, "Learn more"). Small spill left/right is tolerated, never top or bottom.
  One 9:16 export covers Feed, Stories and Reels; 4:5 only for horizontal footage (A03). Keep a 20–40 % safe-zone overlay while
  editing and **turn it off before export** (A03, B06, B08). [AUTO: C010 captions bottom at y 1220, hook box y ≥ 300;
  `verify` checks the geometry against Meta's 14 % top / 35 % bottom / 6 % sides]
- **UGC captions:** auto from the transcript, then restyled: white, black ~4–5 px outer stroke, no shadow ("shadows look cheap"),
  round join, two balanced lines, 35-character max per card (5–8 words), lower half of the safe zone (B05, B06, B07). Proof
  every card against the script: creators ad-lib (B06). **Skip captions on the hook line and the CTA line** where the hook box /
  CTA card already speak (B05). A slightly late caption change can even add UGC authenticity (B06). Chunk by phrase the way
  native captions do — "people don't read captions, they scan them": "You know that feeling / When you take the last sip of
  your coffee / And it's ice cold", each as two short lines (B02). Organic ads skip transitions, animations and SFX (B02).
- **VSL captions:** 1–3 words, screen centre, Proxima Nova Bold ~80, no stroke, a large soft black shadow (B09); emphasis
  words big and bold, secondary words smaller (B05 reference).
- **Don't make a PowerPoint:** baseline captions carry everything; emphasis graphics only on shocking stats, crucial points
  and main benefits, simple enough for a fifth grader (A07). Black or high-contrast word cards ("GONE.") for the line that
  must hit (B09).
- **CTA card:** "Join 400,000+ happy dog parents / Shop @dogfriendlyco" over a happy, beautiful scene (beach sunset with the
  dog) — end where the buyer hopes the product leads (B07, B08). The brand/URL line appears only with the last VO line (A17).
  [NOT BUILT: §13]

## 11. SFX (A14, B06, B07, B09)

- A sound supports a **visible on-screen event**: key in lock, cash sound on "15 % off", a seatbelt click each time the harness
  clips in (B07), a pop on the graph reveal (B06). Benefits get a tick/ding, negatives a buzzer, transitions a whoosh; list
  items escalate in pitch (A14). A riser into the key word, with reverb so it does not end abruptly (B09). A whoosh where a cut
  feels like something is missing (B09).
- **Minimal in organic/UGC:** one or two per ad; the course's own team says heavily SFX'd ads "just don't work for us" (A14).
  Room reverb on an SFX so it sits in the speaker's room (B06). SFX is the last layer (B07, B09).
- [AUTO: `tools/sfx.py` library (pop, whoosh, swipe, riser, ding, tick, buzzer, click, cash, impact, camera, record-scratch;
  peak −3 dBFS) + `plan.sfx` in `rawedit.py`, C011]

## 12. Export and QA (B06, B09, A03)

- Turn the safe-zone overlay off; end the export 2 frames before the end so no black frame ships; review the timeline AND
  the exported file (rendering adds artifacts) (B06, B09). [AUTO: `verify` black-frame head/tail check; MASTER review = owner]
- 1080×1920, 30 fps (B03, B06). [AUTO]

## 13. Not built yet (candidates, in order of value)

1. **Text-only organic mode** (captions-as-script over b-roll + music, cards on the beat, ≥3 s hook cards) — B08 and A04 show
  it ran for Dog Friendly Co. Needs: card PNGs, beat grid from the music, b-roll per card.
2. **CTA end card** (offer line + happy-scene b-roll) and **progress bar / timer overlays** (A12).
3. **Social-proof collage** (2×2 quadrants) for "thousands of owners" lines (B05).
4. **ElevenLabs text-prep lint** for the AI pipelines (§5 rules: stage directions, caps, merged lines, phonetic domains).
5. **Fake dolly / still zooms / reverse / mosaic** helpers for VSL-style b-roll.

## Tools and sites named in the course (reference only)

Premiere Pro, After Effects, Final Cut Pro, CapCut, Figma (hook PNGs), Milanote (briefs), ElevenLabs, ChatGPT (music keywords,
pronunciation fixes), Artlist, Epidemic Sound, Extreme Music, Envato Elements, Pexels, TikTok Creative Center, Atria, Meta Ad
Library, Topaz Gigapixel / Video AI, Vmake (text/watermark remover), vocalremover.org, SnapAny / ssstik / tikdownloader / igram /
y2mate (downloaders), Premiere Composer (free SFX), Shazam.
