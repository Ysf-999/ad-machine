---
name: animated-ad-machine
description: Produce animated video ads end to end on kie.ai using the Marketing Mafia course's animation methods — (A) material/claymation-style ads (clay, felt, Pixar-style 3D, lego, plush, paper cut-out, miniature diorama and the course's other material styles) built from a locked master character, scene stills, silent Kling 3.0 clips with SFX, an ElevenLabs voiceover, speed-mapped edit and captions; (B) talking-character ads (an anthropomorphic object, organ, fruit or creature that speaks its own lines in Veo 3.1). Use when the user asks for a claymation ad, animated ad, cartoon ad, material/stop-motion style ad, Pixar-style ad, talking character / talking fruit / talking organ ad, or any non-UGC animated test ad. For live-action drama use drama-ad-machine; song-led animation song-ad-machine; illustrated explainers finn-xplains-video; Vox / whiteboard / chalkboard their own skills.
---

# Animated Ad Machine

## Learned rules and taste (read first)
Before planning any ad: run `.venv/bin/python -I tools/feedback.py rules animated-ad-machine` and obey every rule (they are owner corrections), then `tools/taste.py brief animated-ad-machine` for the reference ads. Set `"skill": "animated-ad-machine"` in the project's plan.json so notes and rule versions are tracked. After the owner reviews, log his notes with `ad.py <project> notes` and promote general ones with `feedback.py promote`. The full loop is in `FEEDBACK_LOOP.md`.

Sources (read when unsure): `course/_gdocs/animations.txt` (Manual Claymation/Animated Ad Workflow) and `course/_gdocs/talking-fruit.txt` (talking-character method). The operator does not supply briefs, scripts, references or style guidance — Claude writes and sources everything and asks only for approval. Never mention commercial use or licensing.

## Environment
- Project: `projects/<ad>/` with `FRAMES/ CLIPS/ VO/ EDIT_KIT/`, `plan.json` (beats, prompts, approvals) and `jobs.jsonl`.
- Tools: `tools/kie.py` (upload/run/credit, resume by saved task id), `tools/batch.py` (parallel runs), `tools/qc.py`, `tools/assemble_anim.py` (this skill's assembler). Python `.venv/bin/python`; ffmpeg on PATH. Keys in `.env`.
- Report real `creditsConsumed` per job; check `kie.py credit` before each paid stage.

## Models (kie.ai — refresh schemas from https://docs.kie.ai/llms.txt in a new session)
- **Images: Nano Banana Pro** — model `nano-banana-pro`, input `{prompt, image_input:[≤8 urls], aspect_ratio:"9:16", resolution:"2K", output_format:"png"}`. The course: "the only image gen that locks identity reliably across many scenes".
- **Silent clips: Kling 3.0** — model `kling-3.0/video`, input `{prompt (≤2500 chars), image_urls:[start] or [start,end], sound:true (for SFX), duration:"3"–"15" (set per beat by `ad.py vo`), mode:"std"|"pro", multi_shots:false (required)}`. Output follows the start frame's 9:16.
- **Talking clips: Veo 3.1** — model `veo-3-1`, input `{model:"veo3_fast", prompt, image_urls:[start] (or [start,end]), generation_type:"FIRST_AND_LAST_FRAMES_2_VIDEO", aspect_ratio:"9:16", resolution:"720p", duration:8, enable_translation:false}`.
- **Voiceover: ElevenLabs** TTS (`eleven_multilingual_v2`), key `ELEVENLABS_API_KEY`.

## Mode A — Material / claymation ad (the course's standard: "95% of the time, silent clip with SFX, voiceover overlay later")

**A1 Script (no spend) — GATE.** Write a 20–60 s VO script for the product and angle (pull the angle from `brand/brand.json` — `problem`, `audience`, `how_it_works` — plus any customer research you have, and keep claims to what the product really does). Then the course's Stage 1: for every line write WHAT THE VIEWER SEES — show the meaning, not someone reading the line (✅ "clay glucose graph spiking → clay brain shrinking", ❌ "a person talking about blood sugar"). One visual = one clip, 4–8 s each; 60 s ≈ 12–15 clips. Pick the style from the course list (clay/Aardman, felt stop-motion, plush/toy, puppet, plastic doll, action figure, vinyl toy, wooden doll, paper cut-out, cardboard craft, lego/brick, miniature model, diorama, Pixar-style 3D, wax, porcelain, balloon, gel plastic, metal robot, glass) to suit the audience. Present the beat table; wait for approval.

**A2 Master character (images) — GATE.** Course master prompt (swap the style words for non-clay styles):
> Claymation character reference. [age, hair, body type, ethnicity, features]. Wearing [specific outfit]. Aardman-style stop-motion clay animation aesthetic, visible fingerprint texture on the clay, slightly imperfect surfaces, matte lighting, no CGI gloss. Front-facing, neutral warm expression, plain grey backdrop. Vertical 9:16 framing. Hand-sculpted clay model photographed for stop-motion animation, not a CGI render.

Optional negative block (course): amateur clay sculpture, messy fingerprints, uneven childish proportions, crude modeling, photorealistic textures, flat lighting, stock photo look, CGI hyperrealism, 2D illustration, anime style, harsh shadows, overly glossy plastic, messy composition.
Generate 3–5 variations, pick one → `FRAMES/master_character.png`. Also build a style-matched product still from the operator's real product photos (`brand/product-photos/`), e.g. "the exact product from the photos rebuilt as a clay prop, same layout and colours".

**A3 Scene start frames (images) — GATE.** One start frame per beat with Nano Banana Pro. Consistency trick from the course: `image_input` = master character as File 1 **plus the last 4 frames generated**, and end each prompt with: "Same character as reference image, keep face / hair / clothing identical, no character redesign, no facial feature changes. Keep colour grade and colours consistent, same [claymation] animation style." Cutaway/mechanism shots (inside the couch fabric, hair under a microscope…) are encouraged — "this is what the power of good animation can do that UGC can't". For a seamless clip→clip transition, also make an end frame for clip N identical to clip N+1's start frame ("Subject is from File 1. Match the lighting and color grade of File 2. …"). Show the storyboard; wait for approval.

**A4 Silent clips (Kling 3.0) — pilot 1 clip, then batch.** Course templates:
- Single frame: "Keep character facial consistency, no character redesign, no facial feature changes. [CAMERA MOVEMENT]. [WHAT HAPPENS — 1 sentence]. Sound effects: [SFX]. No music. No dialogue. No talking. Handmade stop-motion clay animation throughout, non-CGI, non-cinematic."
- Seamless (start+end frame): "Smooth seamless transition between the first frame and the last frame. [WHAT THE MOTION LOOKS LIKE]. Sound effects: [SFX]. No music. No dialogue. No talking. Handmade stop-motion clay animation throughout, non-CGI, non-cinematic."
- Camera: default static ("Locked-off tripod, completely still"); use slow push in for detail/product, quick push in or snap zoom for hooks, "camera dives into the scene" for outside→inside cuts. Overusing movement makes ads feel cheap.
QC each clip with a frame strip (character drift, product shape, extra limbs, text artefacts); re-roll only real defects as `_v2`.

**A5 Voiceover.** ElevenLabs: pick a voice that fits the avatar (shared library, or a premade voice if the library is unavailable), render the script, keep it at natural speed.

**A6 Assemble (`tools/assemble_anim.py`).** Lay the VO first; speed-map each silent clip so it ends exactly on its line (course: 1.5–3×, "then you have control of the pacing"); keep the clips' SFX under the VO; burn captions from the VO's word timestamps; optional end card from the real product photo; `loudnorm I=-14`. Output `MASTER.mp4` + `EDIT_KIT/`.

## Mode B — Talking character ad (course: "HOW TO GENERATE VIRAL AI ANIMATIONS")
1. **Character:** an anthropomorphic version of the problem or product (e.g. a dog-hair clump, a dust bunny, an organ, a fruit). Course prefers cloning a reference image over inventing ("copying is better than creating from scratch for ai") — source one yourself or design it; render the master in Nano Banana Pro as "A high-quality 3D animated scene featuring the anthropomorphic [character]…".
2. **Lines:** about 20–25 words per 8 s clip (fewer for a 4 s clip). Keep the prompt simple — the course uses just: `[character] says: "[line]"`.
3. **Scenes:** same character in new scenes via Nano Banana Pro with the master as `@img1` ("The same @img1 … is now [state], [where] …"), then Veo 3.1 first-frame for each.
4. QC with `tools/qc.py` (words vs line), assemble with captions.

## Spending
Pilot one image and one clip before batching; report measured credits per image / per clip and extrapolate before the batch.

## Pipeline — use this instead of hand-running the tools
One command per stage; all state lives in `<project>/plan.json` + `jobs.jsonl`. `PY=.venv/bin/python`:
```
$PY -I tools/ad.py projects/<ad> status
$PY -I tools/ad.py projects/<ad> voice "<description>"   # ElevenLabs Voice Design: 3 previews in VO/ to listen to
$PY -I tools/ad.py projects/<ad> voice-pick 2    # keep preview 2 as the ad's voice_id
$PY -I tools/ad.py projects/<ad> vo              # ElevenLabs VO, pauses cut to 0.15 s, per-beat timings + clip durations
$PY -I tools/ad.py projects/<ad> frames          # keyframes (master + last-4 chain), resumable
$PY -I tools/ad.py projects/<ad> clips           # Kling clips for every beat with a frame
$PY -I tools/ad.py projects/<ad> qc              # Haiku vision QC -> QC/qc_report.md (text only)
$PY -I tools/ad.py projects/<ad> review          # REVIEW.html: keyframes + clips + QC + approve/redo
$PY -I tools/ad.py projects/<ad> redo 7 clip "product too big"   # bump that beat, patch prompt, regenerate
$PY -I tools/ad.py projects/<ad> redo 5 frame "make the cushion darker"   # EDITS the current frame (2 rounds), --fresh re-rolls
$PY -I tools/ad.py projects/<ad> stitch --endcard brand/product-photos/<hero photo>.jpg
$PY -I tools/ad.py projects/<ad> promote 7 clip product-result-reveal "clay, couch"   # save an approved asset to library/
$PY -I tools/ad.py library                       # list approved assets; reuse one with "lib": "<id>" on a beat
```
**From the Ad Creators Lab / Trench / Boris audit:**
- **Run `vo` before `clips`.** It sets each beat's `duration` from its on-screen window (×1.3, 3–15 s) instead of a flat 5 s, so clips play near 1× and Kling bills fewer seconds. It warns when a beat is on screen >5.5 s: split it into 2 beats (one action per clip drifts less). Set `duration` yourself to override; `vo_max_gap: null` in plan.json keeps natural pauses.
- **Stitch output flags** `!! CAPPED` (clip ending cut at 3×) and `!! FREEZE` (last frame held). Treat either as a defect: split the beat or redo the clip at the right duration.
- **Fix frames by editing, not re-rolling:** a `redo <n> frame "<note>"` sends the current frame as image 1 with "change only this". After 2 edit rounds it re-rolls from the masters; `--fresh` forces a re-roll.
- **Library:** once a product shot (the result reveal), character or end card is owner-approved, `promote` it. Later ads set `"lib": "<id>"` on the beat; frames/clips reuse it instead of generating, and `redo` refuses to overwrite it. Match the style before reusing (clay clip in a clay ad).
- **Voice: design it, don't pick a stock voice** (Camilo, course + masterclass). `vo` warns when it falls back to the stock voice. `voice`/`voice-pick` create voices through the ElevenLabs API, which needs a paid ElevenLabs plan (on a free plan the call returns 403 `feature_not_available`); until then set `voice_id` to a shared-library voice that fits (drama SOP has the search call). Description recipe: age + gender, accent, energy/mood, persona ("sounds like a storyteller"), pace, and the recording setup ("high-quality studio mic" for narration; "on a phone in a car" for creator-style). Talking characters: one designed voice for every clip.
- **plan_review** now also checks the hook frame (problem and audience clear in the first second, muted) and one idea + one named feeling per beat (`emotion`).
**Context hygiene — the main reason this exists.** Never `Read` frame images or strips in the main session unless the operator asks you to look at one specific thing. Flow: run `qc`, read only `QC/qc_report.md`, run `review`, and act on the pasted "Copy notes for Claude" text. Images that enter the session are re-sent on every later turn.

**Product kit.** `brand/product-photos/` holds the real photos; `brand/brand.json` holds `product_look` and `how_it_works` (quote them in any product-in-use prompt). Build style-matched product renders per style and keep them in the project (or `library/` once approved). Every scene that shows the product held or in use gets a hand-holding-product scale reference. Demo shots are tight close-ups built as start+end frames (`scene_XX_end.png`) so the result is fixed. Check product frames with `tools/product_check.py` before paying for video.

**Visual plan + review pass.** Write the beats, then run a second pass over them as a reviewer (fresh subagent, text only) asking: does every line have a *literal* visual, is the product shown correctly per `product_look` / `how_it_works` in `brand/brand.json`, any scene the model will struggle with (hands manipulating objects, readable text)? Fix the plan before spending on images.
