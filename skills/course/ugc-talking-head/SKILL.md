---
name: ugc-talking-head
description: Produce realistic AI UGC talking-head video ads end to end on kie.ai — one creator talking to camera (car, couch, kitchen, bathroom), optional product reveal, optional b-roll, assembled into a finished 9:16 ad. Covers script split into clips, iPhone-real first frames (GPT Image 2), voice reference, Seedance 2.0 / Kling 3.0 / Gemini Omni Flash generation, background batch with resume, Whisper QC, b-roll (Kling or Seedance 2.5) and ffmpeg assembly with grade and speed. Use when the user asks for an AI UGC ad, talking-head ad, creator-style video, testimonial-style AI video, selfie/car/couch video, "make the script into a UGC video", or AI b-roll for a UGC ad. Not for multi-character story films (use drama-ad-machine), two-host podcasts (wan3-podcast-ads) or animated explainers (vox/whiteboard/chalkboard/finn).
---

# UGC Talking-Head Machine

## Learned rules and taste (read first)
Before planning any ad: run `.venv/bin/python -I tools/feedback.py rules ugc-talking-head` and obey every rule (they are owner corrections), then `tools/taste.py brief ugc-talking-head` for the reference ads. Set `"skill": "ugc-talking-head"` in the project's plan.json so notes and rule versions are tracked. After the owner reviews, log his notes with `ad.py <project> notes` and promote general ones with `feedback.py promote`. The full loop is in `FEEDBACK_LOOP.md`.

One believable creator talks to camera; the product enters naturally; b-roll covers the claims; the finished file looks like a real phone video. Built from the Marketing Mafia AI UGC course (Seedance 2.0, Kling 3.0, Google Omni and B-roll modules). Source transcripts: `course/_transcripts/`; gap analysis: `TRANSCRIPT_FINDINGS.md`.

**The one rule that matters most:** the first frame / reference image is "95%" of the result. Seedance was trained on TikTok, so the still must look like a real TikTok frame — colours, light, framing, imperfection. Spend effort there before anything else.

## Local environment
- Project root: the repo root (run everything from there). Each ad lives in `projects/<ad-name>/` with `FRAMES/ PRODUCT/ VOICE/ TAKES/ BROLL/ EDIT_KIT/`, plus `project.json` (choices, approvals, stage) and `jobs.jsonl` (every kie task).
- Keys in `.env` (`KIE_API_KEY`, `ELEVENLABS_API_KEY`). Never print them.
- kie client: `tools/kie.py` (`credit`, `upload`, `run`, `status`). It saves each task id the moment it is created and resumes by id — never resubmit a key that already has a task id.
- Python `.venv/bin/python` (httpx, openai-whisper, mlx-whisper, pillow). `ffmpeg`/`ffprobe` on PATH.
- Shared tools you build once go in `tools/` (e.g. `assemble_ugc.py`, `qc.py`) and are reused, not rewritten per ad.

## Spending rules
- Check `kie.py credit` before every paid stage. Record `creditsConsumed` from each job and report real costs; never quote prices from memory.
- Nothing paid before the gate that authorizes it. The pilot proves the look before the batch.
- The kie key has a Safe-Spend hourly limit; if a job is refused for limits or "Credits insufficient", stop, report, and resume the missing keys after the operator tops up.

## Stages and gates

### S0 — Setup check (no spend)
Confirm `.env` keys, `kie.py credit`, ffmpeg, the project folder. If anything is missing, ask for that one thing.

### S1 — Intake (no spend)
Ask once, only for what's missing:
1. **Product** and 1–3 real product photos (white background preferred over transparent PNG). State the real size ("50 g pouch", "palm-sized pad") so it scales right.
2. **Avatar**: who is talking — age, gender, vibe, where they'd film (car, couch, bathroom, kitchen).
3. **Script** — or the angle/hook to write from. If you have script-review skills (a script checklist, a hook scorer), write and check it with them first; this skill produces video, not strategy. `references/ugc-script-method.md` has the UGC formats (rant, testimonial, expert, PSA…); ignore its `marketing-brain/` file references.
4. **Length** (default 30–60 s) and **model** (default Seedance 2.0 — see model table).
5. **Inspiration** (optional): a TikTok/Pinterest/Ads Library screenshot for the vibe. Pinterest photos may be used as the creator's face (S3 step 1); never reuse a real person's voice from their video.

### S2 — Script into clips (no spend) — GATE
Split the script into clips at sentence boundaries:
- Seedance 2.0: up to 15 s per clip (4 clips = 60 s).
- Kling 3.0: 6 s clips with ~16–17 words; at 7–8 s Kling pauses for a second then rushes.
- Gemini Omni Flash: ~30–33 words per 10 s clip.
Word counts for Seedance are not given by the course — start near 2.5 words/second and correct from the pilot's measured speech rate.

For each clip write: clip id, exact words, action/gesture, whether the product appears, and the full natural-language video prompt (see "Prompt grammar"). Add the "same setup" line to every clip when the location is fixed. Present the table; wait for approval. Apply notes verbatim.

### S3 — Creator frame + product still (images, ~10 credits each) — GATE
The operator never supplies reference images. Claude sources them. Pure text-to-image looks "AI" (soft, too clean); the course's best results start from a **real photo** with only the person replaced (Kling 3.0 module [04:49]–[06:54]).
1. **Pinterest casting — default (Camilo's Seedance × Claude method; owner-approved, real people from Pinterest are fine as the creator).** Write 3–4 creator searches from the avatar (age, look, setting, "iphone candid", e.g. "woman 30s selfie kitchen iphone candid no makeup") plus 1–2 setting/prop searches per scene, then run `<scrapling python> -I tools/pinterest.py search <proj>/PINS/creator "<query>"`. It downloads up to 16 pins and opens `PICK.html` for the operator; **don't Read the pins in-session**. When the operator names a number: `pinterest.py pick <proj>/PINS/creator <n> <proj>/REFS/creator.jpg` (source URL saved next to it). Pick rules: natural light, casual clothes, phone quality, no studio/magazine poses, and **only clean photos** — no stickers, watermarks, text or app UI (Seedance rebuilds them as objects). The creator photo is `@image1` in every Seedance segment; settings/props are extra `@imageN` refs (Max Fusion-style numbering follows upload order, so state the mapping in each prompt).
2. **Real-photo swap — alternative** (when no pin fits, or for Kling/Omni first-frame routes): a stock photo of the real *setting* (Pexels / Unsplash / Openverse) with the AI creator placed in it (step 4). Save the source URL in `project.json`.
3. Pick the photo whose camera height, light direction and room match the script; reject anything that looks staged or over-produced (wide-angle real-estate shots, perfect styling).
4. Place the AI creator into it with `gpt-image-2-image-to-image` (input 1 = real base photo, input 2 = character reference if one exists): "Keep this exact real photo — room, light, grain, camera angle. Add [creator description] sitting/standing [where] … Change nothing else." Add script-specific details (e.g. dog hair on the cushion) in the same pass.
5. Fall back to text-to-image from `references/iphone-realism-guide.md` only when no usable real photo is found; say so.
- No product in hand in the first frame — the product enters during the video.
- Kling route: make 3–4 start-frame variants of the same person/set (vary prop or gesture) with image-to-image using the "Same set, new prop" block, so the talking clips don't all start identically.
- Product: one clean hero still of the real product (from the operator's photo), reused everywhere; never re-describe its colours in prompts.
- Show the frames; wait for approval. Re-roll only what the operator rejects.

### S4 — Voice (optional) — GATE
- Seedance can clone a voice from `reference_audio_urls` (2–15 s mp3/wav). Make that sample with ElevenLabs (prefer a Voice Design voice built for this avatar, `tools/voice_design.py design <proj>/VOICE "<description>"` then `pick` (needs a paid ElevenLabs plan); otherwise a shared library voice matching the avatar; sample text containing the product name and any hard words), then reference it in the prompt as `audio 1`. Never use audio taken from a real person's video.
- Without a reference, Seedance and Kling invent a voice from the description; Kling tends to keep the same voice per face.
- Omni: register the voice with `gemini-omni-audio` and pass `audio_ids`.
- Play the samples for the operator; wait for a pick.

### S5 — Pilot (1 clip) — GATE
Generate the first clip only. Then QC it (S8 checks) and report: real credits used, measured speech rate, defects. Patch every remaining prompt from what the pilot shows. Wait for the operator's go.

### S6 — Batch (background)
Generate all remaining clips with `kie.py run` per clip key, run detached (never in the foreground), concurrency ~4–8. Every task id is persisted on submit; on restart, already-finished keys are skipped and pending ids are polled, not resubmitted. Report SUBMITTED / OK / FAIL lines.

### S7 — B-roll (optional, images then video) — GATE on the image board
1. From the script, write a shot list that literally shows each claim (problem moment, failed solution, discovery, product in use, result). Faceless shots can go into a reusable library under `broll-library/<category>/`.
2. Generate a 9:16 still per shot first — defects (blurred labels, wrong product) are cheap to catch here. Add the realism line: "uneven camera angles, TikTok style, candid as if it was taken with the iPhone 15".
3. Animate each approved still: Kling 3.0 (`std`, 5 s, `sound:false`, "no spoken words", handheld-shaky prefix) by default; Seedance 2.5 whenever readable text, phones or screens appear (Kling turns text "glyphic").
4. X-ray/inside-the-body style shots: candid start still → same shot zoomed with the overlay → animate start→end (first+last frame), trim to 2–3 s at 2×.
5. Use 1–3 s of each clip; salvage awkward clips by trimming.

### S8 — QC (every clip)
- Whisper (`small.en` or mlx turbo) transcript vs the clip's exact words. Mishearings of brand names/numbers are flagged for the operator's ear, not auto-re-rolled.
- 3–5 frame strip per clip: face/wardrobe drift, product shape/label, hands, eyeline, extra people, on-screen text, stuck start frame.
- Re-roll only verified defects as `<key>_v2`, `_v3`…; the assembler always uses the highest version.

### S9 — Assemble
- Normalize every clip (1080×1920 or the clips' native 9:16, 30 fps for ads, AAC 48 kHz), concat in script order, insert b-roll over the matching lines (talking audio continues underneath), `loudnorm I=-14:TP=-1.5`.
- Kling talking clips: speed to 1.1×. Grade toward an iPhone look (course CapCut values: temperature +2, exposure −3, contrast −6 to −8, highlights −3, shadows +3, whites −2; Omni clips want contrast −12 to −16) — approximate with ffmpeg `eq`/`colorbalance` and keep it subtle.
- Output `MASTER.mp4`, `EDIT_KIT/` (numbered clips + `ORDER.txt` for CapCut finishing: captions, hook text, music) and `QC_REPORT.txt`. Optional: Adobe Podcast "Enhance" on the final audio is an operator step.

## Model table (kie.ai — refresh the schema from `https://docs.kie.ai/llms.txt` before the first paid call in a session)

| | Seedance 2.0 (default) | Kling 3.0 | Gemini Omni Flash 1.1 | Seedance 2.5 (b-roll w/ screens) |
|---|---|---|---|---|
| model | `bytedance/seedance-2` (also `-fast`, `-mini`) | `kling-3.0/video` | `google/gemini-omni-flash-1-1` | `bytedance/seedance-2-5` |
| how to feed the person | **reference mode**: `reference_image_urls` (≤9; image1 person, image2 product, image3 prop) — not `first_frame_url`, which looks worse | `image_urls: [start]` (or `[start, end]`) | `image_urls` refs, or `first_frame_url` (+`last_frame_url`) | `reference_image_urls` (≤30) + `reference_video_urls` (screen recording) |
| voice | `reference_audio_urls` (≤3, 2–15 s) | `sound: true` | `audio_ids` from `gemini-omni-audio` | `reference_audio_urls` |
| duration | int 4–15 | string "3"–"15"; use "6" for talking | string "4"/"6"/"8"/"10" | int 4–30 |
| quality | `resolution: "720p"`, `aspect_ratio: "9:16"` | `mode: "std"` (720×1280) or `"pro"` (1080×1920) | `resolution: "720p"`, `aspect_ratio: "9:16"` | `resolution: "720p"`, `aspect_ratio: "9:16"` |
| notes | first-frame and reference modes are mutually exclusive; `generate_audio: true` | prompt ≤2,500 chars | first-frame mode excludes refs/audio/video | `first_frame_url` excludes all refs |

Cheap variants: Omni with a finished Seedance clip as the reference video (`video_list`) swaps in new script lines at roughly "60–70%" of Seedance quality for less — use for script-variation tests once one Seedance clip exists. Use only AI-generated clips as video references.

## Prompt grammar (natural language, one block per clip)
- Reference tags have **no space**: `@image1`, not `@image 1`. Refer to audio as `audio 1`.
- Describe: who (the woman from @image1), where, camera ("handheld selfie" or "static tripod shot"), the exact line in quotes, delivery, gestures, and what must not happen.
- Delivery line (Seedance): "she should talk like she's yapping to a friend, add small natural movements and gestures, looking around, leaning closer, laughing a little".
- Voice line: "She talks fast and casual like venting to her best friend on FaceTime with natural filler using audio 1."
- **Audio-environment line (every talking clip; Camilo, Ad Creators Lab):** name the space and how the phone mic hears it, or the audio comes out clean and "tinny" and reads as AI. Car: "recorded on the phone mic inside a parked car, slightly muffled and close, faint road hum, no music." Kitchen/bathroom: "phone mic in a small tiled room, light natural echo." Living room: "phone mic, soft room reverb from the couch and rug, quiet household ambience." Street: "phone mic outdoors, passing cars and distant city noise under the voice." If the picture looks real but the voice sounds AI, fix the voice first: describe accent, pace and energy in more detail, or pass an ElevenLabs Voice Design sample as `audio 1`.
- Fixed setup line: "she is always sitting in the same car, in the same seat, the same lighting, same angle and the same tripod camera setup."
- Product entry: "reaches down out of frame with the right hand and brings up to the chest the [product] from @image2" — more natural than starting with it in hand.
- Omni base: "natural and realistic arm movements, subtle lean forward, looks directly at the lens the whole time; he/she says in an american 20 year old ugc tone: "[LINE]". Ambient sound. No cuts. No zooms. No transitions. Raw iPhone footage, expressive ugc movements, UGC aesthetic. Vertical 9:16. NO PRODUCT IN HAND. ONE CONTINUOUS SHOT" (prefix "Static tripod shot," for the tripod variant).
- Continuation clips: "[character] in the exact same scene, talking in the exact same tone and voice, rhythm".
- Kling set variants (image-to-image): "Exact same framing as Image 1 — same character, same set, same lighting. Vary only prop and gesture/expression. Deep focus, no blur. ABSOLUTELY NO phones, cameras, screens, social media UI, floating text or digital overlays."
- B-roll realism: "uneven camera angles, TikTok style, candid as if it was taken with the iPhone 15"; prefix motion prompts with "handheld shaky camera movement"; add "no spoken words".

## Revisions
Preserve approved work. A changed face invalidates that face's clips; a changed line invalidates only its clip. Continue from the earliest affected stage with only the gates the operator kept.
