# Learned rules — raw-ugc-editor (real creator footage + b-roll library)

Read before every edit: `feedback.py rules raw-ugc-editor`. Owner-review rules arrive through `feedback.py promote`.
The S-rules below are SEEDS, not owner rulings: numeric starting points taken from an agentic-editing article,
i-hate-editing's HARD-RULES.md and our own assemble_ugc.py. The owner can strike any of them; each one is also a default in
`tools/rawedit.py` (`plan.rules`) so a changed rule is a changed number, not a re-write.

- **S001** Cut edges live in silence. Never cut inside a word; never place an edge on a Whisper word onset (onsets sit on the consonant and clip the attack). In-edge = 0.10 s before the word, inside the pause; out-edge = 0.15 s after the last word's end, never into the next word. [i-hate-editing rule 18; article step 2]
- **S002** Collapse every pause longer than 0.45 s inside a kept range (that is the jump cut). Keep pauses that would leave a piece under 1.2 s. [article; jump-cut-pacing skill]
- **S003** No piece shorter than 1.2 s. If the plan makes one, merge it with its neighbour. [article]
- **S004** Jump cuts land at phrase ends. A mid-sentence jump cut is flagged in `rawedit.py plan` and needs a reason. [article step 3]
- **S005** Captions are 2-3 words, uppercase, no background box, never duplicate the hook card, and start 0.06 s AFTER the word onset (late is invisible, early reads as broken). Timed from Whisper on the rendered voice track, never from the source take. `caption_sync_check.py` must PASS. [i-hate-editing captions.md; R001]
- **S006** Captions composite last; nothing is drawn over them. B-roll is composited inside the beat before captions. [i-hate-editing rules 1, 20]
- **S007** 30 ms audio fade at every segment boundary. Extract per segment, then concatenate losslessly. [i-hate-editing rules 2, 3]
- **S008** Final mix -14 LUFS, true peak <= -1.5 dBTP. Music sits 8 dB under the voice (6-12 acceptable), measured by `audio_check.py` in the voice's pauses. [article; assemble_ugc.py]
- **S009** Speed changes happen inside the segment render, never on the finished cut (captions, music and seams are all timed from the rendered timeline). [i-hate-editing rule 9c]
- **S010** Probe DISPLAY dimensions. Phone clips report 1920x1080 with a rotation flag; sizing from the stream makes a vertical ad letterboxed. [i-hate-editing rule 9d]
- **S011** The plan is approved before anything renders: TAKES.md -> keep ranges -> `plan` audit -> STORYBOARD.html. Fixing text is cheaper than fixing a render. [article step 3]
- **S012** Verify before presenting: re-transcribe 3 s around every seam (repeated word, chopped attack, pop), diff spoken vs planned, run the caption sync and audio checks. "It rendered" is not done. [i-hate-editing rules 11-13]
- **S013** B-roll comes from the b-roll INDEX (quality 3 first, no flags, Type = B-roll), matched to what the line says (couch line -> couch clip). Never show a clip of another product as if it were ours. The product must be on screen by 3 s unless the hook is the creator's face (ads without the product in the first 3 s flop).
- **S014** One approved body, many openings: `rawedit.py variant` swaps only beat 1 and keeps the body identical. Lock the approved master first. [article step 7; R014]
- **S015** Offer and claims follow `brand/brand.json` (`default_offer`, `never_show`, `banned_phrases`; no discount codes unless the offer has one). A creator's own spoken claim that breaks them is cut, not kept. [R016]

## Course seeds (C-rules)
From the "Video Ads Mastery" + "Video Editing Breakdowns" course (Ecom Talent agency; 3 of the breakdowns edit **Dog Friendly Co**
ads with real spend). Full playbook with sources: `knowledge/video-editing-course/EDITING_KB.md`.
Like the S-rules these are SEEDS: each is a number in `rawedit.py DEFAULT_RULES` / `plan.json` that the owner can change or strike.

- **C001** Alternate the scale on every a-roll jump cut: 100 % / 110 % (`punch_in`); a very abrupt cut 112 %; under ~103-106 % nobody sees it; never ping-pong all ad long. **C001b** a talking piece longer than the cadence ceiling gets a mid-line punch-in at a word gap every ~2.8 s (`auto_punch`), same take, no cut. Emphasis zoom 112 % on the key sentence (beat `"zoom": 1.12`); subject near an edge = directional punch-in (`"zoom_anchor": [x, y]`). [B06, B05]
- **C002** Something changes on screen every 2-3 s (b-roll, punch-in, text, angle). `plan` and `verify` flag any stretch longer than `max_static` 3.5 s. The ceiling is 3.5 not 2 because older buyers drop off hectic edits; tighten it for a young audience. [A12, A06, B05, B08]
- **C003** The music's beat drop lands at the start of the hold (beat `hold_beat`, default 2): `render --music-drop <s>|auto`. [B04, B07, B08]
- **C004** Voice chain before loudness: high-pass 80 Hz, compressor ~3:1, de-esser, then loudnorm (`voice_chain`). Course chain: Multiband "Broadcast" -> De-esser -> Hard Limiter -6 dB; VO peaks -3 to -6 dB. [B03, B06, B09]
- **C005** EQ the music before lowering it: notch 1500 Hz, Q 4, -15 dB (`music_eq`) so speech has its own space; then the S008 level (8 dB under). [B04, B05]
- **C006** B-roll covers its whole line: a clip up to 12 % short is slowed to fit (88-92 % is invisible); a visual longer than ~3 s becomes two clips; start and end clips on phrase boundaries; never stack two flashes over one sentence. [B05]
- **C007** Drop the music completely under the line that must land (`music_stops: [beat]`), bring it back after. Use once or twice per ad, not every line. [A14]
- **C008** A deliberate, slightly bigger pause before the CTA so the story feels finished (`cta_beat`, `cta_pause` 0.35 s). Keep a short gap before a punch word too ("…for years… gone."): choose keep ranges that keep it. [B03, B09]
- **C009** Hook text: a native rounded white box with black sentence-case text, on screen from FRAME ONE with no animation, top of the safe zone, perfectly STRAIGHT (tilted boxes read as crooked: never rotate text or boxes), readable in half a second, at least 3 s and at most 5 s on screen. It never repeats the caption. [A11, B05, B06, B07]
- **C010** Safe zone: captions, hook box, product and faces stay inside Meta's zone (top 14 %, bottom 35 %, sides 6 %); captions sit with their bottom at y 1220 (`caption_margin_v` 700). One 9:16 export covers Feed, Stories and Reels. [A03]
- **C011** SFX only on a visible event (a product click, graph pop, riser into the key word, whoosh where a cut feels empty); one or two per organic/UGC ad; library `library/sfx/` via `tools/sfx.py`, cue with `plan.sfx`. [A14, B06, B07, B09]
- **C012** Hook variants test the message OR the visual, never both: `variant --hook-card "…"` (same cut, new text) or `variant --keep "a-b"` (new opening, same text). A winner becomes the baseline; make three more of the winning type. [A11]
- **C013** Before presenting: no black frames at the head or tail, safe zone clear, cadence clear (all in `verify` "Edit checks"), and watch the exported file, not only the timeline. [B06, B09]
- **C014** B-roll matches what the line says (literal first); lead with the pain point, force-show the mechanism on the mechanism line, show the solution after the turning point; same creator for an organic ad; before/after pairs from the same place; flip a clip whose screen direction fights its neighbour (`set-broll --flip`); first contrast can be a split screen (`set-broll --split`). [B05, B06, B07, B08]
- **C015** Keep the creator on screen during b-roll when her face is on camera: a small rounded picture-in-picture, right side, above the captions (`set-broll --pip`); vary the layout per scene (PiP, full frame, none). Not for POV takes where she is off camera. [B02]
- **C016** Captions are chunked by phrase the way native captions are ("people scan them"), two short lines max, never wider than the frame (they wrap). Organic ads: no transitions, animations or SFX beyond the punch-ins. [B02, B05]

## Owner rulings (R-rules, win over S and C rules)
- **R001** Keep the open loop: never show the product before the line that reveals it. Before that, lines about the old way show a
  generic hand, the old method, or the problem itself, with our product nowhere in frame.
- **R002** The demo is ONE uncut take (moment kind `demo-take`): the action runs straight into the visible result in the same
  shot; cut right when the result shows. Skip any b-roll that is not one take (edited clips). Speed up only slightly and only if
  needed. Mark such shots `"one_take": true` (overrides C002 cadence for that shot).
- **R003** Demo takes must show a BIG, obvious result; a faint or small result is too weak. Rate the result before choosing;
  prefer 3+/5.
- **R004** Review cards look like a real review widget: initials avatar, first name + last initial, Verified Buyer, stars, clean
  modern font (SF Pro), the real review verbatim. Never a plain quote box.
- **R005** Product sound is REAL or nothing: the clip's own audio (slightly, only where nobody talks) or silence. Never synthetic
  SFX standing in for the product's own sound. Other transitions and SFX are welcome (punch, flash, shake, riser+impact on the
  reveal, pops on cards).
- **R006** Check every demo window frame by frame (`broll_web.py cuts`, scene-score spikes > ~0.12); creator clips that look
  continuous often hide cuts.
- **R007** Lines about the problem show the problem itself, not a cute face (no pet or baby close-ups there).
- **R008** Failed-alternative demos ARE shown when the line names them, on the real problem, really failing; never show another
  product as if it were ours. No clip that has its own burned-in text anywhere in the used window: check text on 720 px stills of
  CUT.mp4 (contact sheets miss script fonts). Card backgrounds stay calm (one quiet shot, soft blur ok).
