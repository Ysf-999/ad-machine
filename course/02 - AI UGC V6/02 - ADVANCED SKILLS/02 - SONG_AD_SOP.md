# SONG AD MACHINE — SOP (animated song films, any style)

A song ad is a short animated music film: an original song carries the entire sales message (story, mechanism, brand), and the picture is a chain of beautiful, perfectly consistent animated shots cut to the lyric map. Nobody lip-syncs and nobody reads a script on camera — the song does all the talking, which makes this format immune to the pronunciation and dialogue problems that plague talking-head AI ads. Any animation style works — soft-plush pastel, Pixar-toy 3D, claymation, paper-craft, felt stop-motion, watercolor storybook — as long as it is ONE style, locked in anchors and inherited by every frame.

---

## HOW THE OPERATOR MAKES THE SONG (before Claude — three steps)

1. **Write the OG script** as a normal ad script (not as a song). Problem lived → mechanism of the problem → discovery + mechanism of the solution → brand once, late → close. Ordinary ad-copy laws apply; lyrics are still ad copy, so compliance lines too.
2. **Go to ChatGPT** and say: **"turn this into a song that rhymes but keep all of it verbatim where you can."** Check the output kept your key lines, mechanism language, and the brand mention intact.
3. **Go to Suno** → Custom mode → paste the lyric output into the LYRIC box → type whatever style you want in the style box (genre + era + mood + vocal; "clear diction, vocal above the instruments" helps) → leave everything else as it is → regenerate as many times as you want until the sound is right. **Pick the take where every word is clearly intelligible.** Download it.

Then **drop the song file into Claude Code together with this SOP**, plus 1–3 clean product photos and one line on who the ad is for. Claude takes care of everything else below.

*(A dialogue-song works extremely well: a second spoken voice interjecting "Wait, what?" / "Get to the point" between sung lines — the interjections become comedy beats and pre-handle objections. If the operator instead wants help writing the script or lyrics from scratch, Claude writes them on the skeleton above — but the default flow is: they arrive with script and song done.)*

---

## FOR CLAUDE — THE MACHINE (binding instructions; never skip a gate; never generate before the gate that authorizes it)

### STAGE 0 — SETUP + INTAKE (works from absolute zero)

When this file is handed to you, assume the operator knows NOTHING beyond having Claude Code open. Walk them through the contract in plain words, one item at a time, and do everything you can yourself:

1. **Generation access (the one thing only they can provide).** They need an account on any AI media platform that serves, via API: an image model with text-to-image AND image-to-image (i2i is the backbone), and an image-to-video model. One aggregator platform covering both is easiest. Tell them exactly: *"Sign up, top up a small starting balance, copy your API key, and paste it here (or tell me and I'll put it in a `.env` file for you)."* Store it as `.env` in the project root; never hard-code it. Then read the platform's API docs yourself and build/verify the client: create task → poll → download, retries, **every task id persisted to disk the moment it exists** (resume by id, never resubmit blind).
2. **Everything else you set up yourself:** check ffmpeg (give them the one-line install command if missing) · install a local word-timestamp transcription tool (e.g. via pip) · use any available second model for the lyric truth-pass, and if none exists, fall back to single-model + operator ear-check on every flagged word · create the project folders (`ANCHORS/ STILLS/ CLIPS/ DROP/`).
3. **SANITY PILOT (mandatory on a fresh setup, before the first real ad):** one anchor still → one i2i-derived still → one short animation of it → a 10-second assembly muxed with any music file. This proves the entire chain — key, client, i2i, animation, ffmpeg — on a tiny scale. If any link fails, fix it here, not mid-production.
4. Then say, in substance: *"Setup verified. Send the song file to this chat when you're ready — along with your product photos and one line on who this is for — and I'll take it from there."* Then wait.

### STAGE 1 — SONG IN: TIMESTAMP + DIRECTION

The moment the song file arrives:
1. **Transcribe with word timestamps** and persist the map to disk. Run a **second model's verbatim pass and diff** — transcription models mishear ingredient and brand names in opposite ways; where the two agree is the caption truth. Show the operator the timestamped lyric sheet, flag any word the models disagreed on, and note the outro trim point (AI songs love repeating outros; the edit will cut them).
2. **Direction.** Two paths, operator's choice:
   - **They have an idea** ("one consistent character who does X, Y, Z") → restate it as a concrete film concept and confirm.
   - **They want ideas** → propose 2–3 concepts built from the song's content: recommended pattern = ONE cute non-speaking mascot personifying the hero ingredient's SOURCE, colored to echo the product/brand color, guiding us through **the problem zone itself rendered as a landscape** (the mascot walks on it, shows it failing, goes INSIDE it via a cross-section "engine room" where the mechanism lives, applies the product, fixes it, celebrates). Serene giant + tiny guide is a proven pairing.
3. **Style interview.** Offer the style menu with a recommendation for the song's mood (plush-pastel for gentle tracks, Pixar-toy for bouncy comedy, claymation for handmade quirk...). Lock the chosen style as a reusable STYLE block of concrete visual words (palette, surface texture, light quality, shape language, "NOT photoreal") — pasted into every prompt from here on.
4. **Character count.** Recommend ONE mascot unless the song is a true duet — one character is one identity to defend; every extra face multiplies drift. A dialogue-song's interjection voice needs no body. Multiple characters = one sheet each + never mix face-bearing references between them.

**GATE: operator approves direction + style + cast in writing before any pixels.**

### STAGE 2 — ANCHORS (four masters everything inherits from)

1. **CHARACTER SHEET** — one image, THREE poses (front wave, side-profile action, proud pose), identical design, plain background, the exact color named in words that can't drift ("clear bubblegum pink, belly lighter creamy pink — NOT silver, NOT gray"). Every future mascot shot is i2i from this sheet.
2. **WORLD ANCHOR** — one master still defining the whole look. **No uninvited characters** — a stray creature in a world anchor propagates into every child. A broken anchor is never pushed forward (ANCHOR-FAIL = HOLD).
3. **PRODUCT LOCK, BRANDED** — the real product photo stylized ONCE into the film's look via i2i, **wearing its real label**. The label is the ONE exception to the no-text law — it carries the brand and the correct spelling of any hard ingredient word every time the product appears. Prompt rules: reproduce the reference label; all text appears EXACTLY ONCE, front face only; NO mirrored/reversed lettering, NO doubled words; quote the exact strings and spell the failure-prone word letter-by-letter. **Zoom-audit at full resolution, letter by letter** (classic first-attempt fails: a mirrored ghost of the brand, a doubled letter). Re-roll until perfect.
4. **CROSS-SECTION / MECHANISM SET** — the engine room where the mechanism lives, as cozy literal objects (mesh as knitted yarn, cushions as velvet pillows — one already failing, because that's the story).

**GATE: operator approves the anchors (or names swaps). Show them; don't describe them.**

### STAGE 3 — ALL IMAGES AT ONCE (the storyboard)

1. **Shot map:** one row per lyric line + instrumental bars: line, start/end, the shot under it, anchor parents, intended motion. Laws: **line-intent** (the shot shows the line's MEANING); interjection lines get reaction shots; chorus repeats get the same MOTIF with variation, never the identical shot; **the product must be USED on camera** (an application montage — the mascot physically applies it to each named problem zone, a visible trace sinking in); **before/after pairs on the problem zones, never split-screen** — the AFTER is derived i2i FROM the before ("IDENTICAL scene and every surrounding detail — with ONE change"), so the change can play in one continuous scene; **the transformation law (no-bulge):** improvement reads through surface QUALITY — dull→glowing, rough→smooth, dips LEVEL OUT even with surroundings — never inflating or rising above them; **prop-material continuity** (a glossy prop stays glossy in the next cut).
2. **Generate every shot as a numbered still** (S01, S02, ... in timeline order) via i2i from its parents — all at once, concurrently, product-featuring stills waiting only on the branded lock. **Everything is 9:16 vertical** (stills, clips, the final film) unless the operator explicitly says otherwise — never ask. Guard block on every prompt: NOBODY else in frame, no other creatures, no readable text anywhere (product shots swap in: "the label is the ONLY text, kept exactly as the reference, legible, once"), real object weight, nothing floating. Chains ≤2 deep from an anchor.
3. **Self-audit on small contact sheets** (small renders expose drift), fix your own fails first, then **present the full numbered storyboard sheet.**

**GATE — the redo loop:** the operator says **"good to go"** or names numbers — **"redo image 12"** (optionally why). Re-roll exactly those, re-present, repeat until "good to go." Numbers make this unambiguous; never renumber between rounds.

### STAGE 4 — ALL CLIPS (animation)

1. **Pilot first: 3–4 clips** testing different muscles — the hook/character shot, a world/light shot, **one product application (the label must stay legible through the motion)**, **one transformation fill animated FROM the before still** ("the dip gently smooths and evens out... NOT bulge, NOT inflate; the visible change is quality — dull becoming clear, healthy, glowing"). Operator verdict on motion, then batch.
2. **Prompt recipe, every clip:** HOLD block ("[style] held exactly as the start frame; light unchanged; no morphing, no new characters, no text appearing") + ONE motion + camera language ("slow push-in", "locked and calm") + diegetic sound cue, sound generation ON (silent generations move worse; the song replaces audio later anyway).
3. **The improvisation law:** the video model animates everything it can and improvises on anything unpinned — skies become curtains, hollows tear open, forming objects become glass bottles, characters float. You cannot pre-guess every mutation; when one appears, **re-roll naming the observed mutation as a ban** ("the sky stays a sky — no curtains"). Named bans work where generic "no morphing" fails.
4. **Batch shape:** detached background job; **submit everything first, persisting each task id at submit, then poll**; skip existing files; report and pause on account errors.
5. **Frame audit, every clip** (~1 frame/second strips, reviewed in sheets), three buckets: **clean** (most) · **late-clip drift** — first seconds clean, tail wanders → NOT a re-roll; record the clean span ("use first 2.5s") for the edit · **hard fails** — broken early or in a way the beat can't avoid (wrong product form, tone-breaking imagery, identity drift on a face, label garble) → re-roll with the mutation named. Zoom product labels at full res.
6. **Nothing stays still — HARD RULE (known glitch guard):** the machine has a failure mode where the edit quietly fills gaps with raw stills or slow-zoom (Ken Burns) images — they read as frozen photos between living clips and instantly feel cheap. This is BANNED from anything the operator sees. EVERY source in the edit must be a video clip: any slot that would be a static image (before/after reveals, mechanism master, beauty shots, the product end-card, gap fillers) gets an **ambient-motion clip** — light shifts, texture stirs as if breathing, motes drift, very slow camera — plus a state guard ("the skin state does NOT change" on befores; "stays exactly as smooth and glowing" on afters; "label stays exactly as the start frame" on the card). Before assembly, sweep the slot table: any slot whose source is an image file is a BLOCKER — animate it first, then cut.
7. **Present the numbered clip audit sheets.** **Same redo loop: "good to go" or "redo clip 7."**

### STAGE 5 — THE EDIT (operator's choice, offer both)

Ask: **auto-stitch, manual, or both?**
- **AUTO-STITCH:** build the cut from the timestamp map — a slot table of (song_start, song_end, clip, in-point) with every audit trim note baked in. Each shot enters on its line (±0.3s drift feels natural); long notes hold longer; instrumentals carry journey/montage beats; the strongest visual lives in the first seconds; **the brand lyric line has the branded product on screen**; the film ENDS on the product in-world (hero shot / end-card clip) with the operator's CTA text burned over it in the edit if they want one; no visible re-use (a clip may appear twice only as two clearly different spans); cut the outro at the planned trim with a video fade + longer audio fade. **The song is the master audio; clip sound off or far underneath.** Captions (truth-passed text only) burned in the edit, never inside images. Verify with a one-frame-per-slot contact sheet with the lyric overlaid on each frame — every line on its intended shot. **Then run the motion audit on the rendered film:** for each slot, extract two frames ~1.5s apart inside the slot and diff them — near-identical frames = a static segment slipped through (the known stills glitch); animate that source, re-render, re-check. Only a cut where every slot demonstrably moves gets delivered.
- **MANUAL (CapCut) MODE:** build the **DROP FOLDER** — every clip copied and renamed `NN_slot_name.mp4` in timeline order so **alphabetical sort = the edit**, plus `00_SONG`, `00_LYRIC_TIMESTAMPS.txt`, and `00_README_cue_map.txt` listing per file its song timecode, its lyric, and its trim note ("USE FIRST 2.5s — face morphs after"; "brand beat"; "two shots in one: wide 0–2.5s, macro 3–5s"). The operator drags the folder onto a timeline and edits without asking a single question.

Deliver with an honest defect list either way.

---

## LAW INDEX (quick reference)

One style block, pasted everywhere · character sheet is the identity, i2i everything from it, chains ≤2 deep · no uninvited characters in anchors; anchor-fail = HOLD · label = the only text in the world, audited letter-by-letter, held by name in every derived prompt · line-intent shot map; interjections get reactions · product must be USED on the zones; before/after = same-frame i2i pairs; transformation = level + quality glow, never bulge; no split screens ever · two-model lyric truth-pass before captions · numbered stills and clips; QC loop = "good to go" or "redo N"; never renumber · one motion per clip + hold block + camera language + sound on · the model improvises on anything unpinned — re-roll by naming the observed mutation · late-clip drift is normal: cut the clean span, don't re-roll · every task id persisted at submit; resume by id · frame-audit strips on everything; zoom product labels · nothing static in the final cut EVER — every slot is a clip, stills/Ken Burns banned, pre-assembly sweep + post-render frame-diff motion audit catch it · song is master audio · brand line = product on screen · auto-stitch or alphabetical drop folder with cue-map README, operator's choice.
