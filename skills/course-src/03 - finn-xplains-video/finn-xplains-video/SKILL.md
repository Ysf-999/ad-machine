---
name: finn-xplains-video
description: Create Finn Xplains style illustrated explainers and advertorials from a supplied script or voiceover. Use for beginner setup, cast and character sheets, timed scene image prompts, KIE image generation, optional Grok Imagine 1.5 or Kling 3 animation, and assembly with optional character and scene approval. Also use to continue or revise those stages. Not for generic video analysis, live-action UGC, or song-led animation unless this style is explicitly requested.
---

# Finn Xplains Video

Turn the user's words into a coherent illustrated story. “Finn Xplains” is the user's name for the supplied reference aesthetic: white round-headed characters, detailed ink-and-watercolor environments, simple explanatory graphics, held compositions, and sharp editorial cuts. Preserve the current script, voice, product, and references.

## STAGE 0 — SETUP + INTAKE (works from absolute zero)

On a fresh setup, assume the operator knows nothing beyond having Claude Code or their coding agent open. Explain the contract in plain words, **one item at a time**, and do the setup yourself wherever possible. First inspect existing files, access and inputs so the operator never has to repeat completed work. Read [setup and pilot](references/setup-and-intake.md) for the execution details. Updating this skill alone does not run setup or paid jobs.

1. **Generation access — the thing the operator provides.** Default to KIE, which covers the image and optional video routes. Another operator-chosen API platform is acceptable if it supports text-to-image, image-to-image and, when animation is wanted, image-to-video. Explain that image-to-image keeps characters and scenes consistent. If access is missing, say: “Sign up, top up a small starting balance, copy your API key, and paste it here (or tell me and I'll put it in a `.env` file for you).” Store supplied credentials in the project-root `.env`, never hard-code them or echo them back. Read the chosen platform's current docs yourself and build or verify its create → poll → download client. **Persist every task ID to disk immediately when received; resume by ID, never resubmit blind.**
2. **Set up everything else.** Check FFmpeg/ffprobe and install missing tools; if installation needs the operator, give the one-line command for their operating system. Prepare local Whisper with word timestamps; an OpenAI API key is optional. Arrange an independent second-model check of the spoken words when available, otherwise single-model transcription plus an operator ear-check of every flagged word. Create `ANCHORS/`, `STILLS/`, `CLIPS/`, and `DROP/` in the project. Follow the reference for environment and transcript checks.
3. **Sanity pilot — mandatory on a fresh generation setup before the first real ad.** Run one anchor still → one image-to-image derived still → one short animation → a 10-second assembly with a music file. Verify the actual outputs and fix any failed link here. Respect an explicit images-only or no-animation choice: verify only the selected chain and mark animation unverified until enabled. Prompt-only work needs no paid pilot. Keep the tiny batch within existing authorization and budget; record evidence so a restart does not repeat it.
4. **Intake handoff.** Once the selected setup is actually verified, say in substance: “Setup verified. Send the voiceover file to this chat when you're ready — along with your product photos and one line on who this is for — and I'll take it from there.” Then wait for missing inputs. If they already supplied those inputs and requested production, continue without asking again. For a non-product explainer, request relevant reference images instead of product photos.

## 1. Establish the requested result

Read current inputs and existing approvals before asking anything. Resolve these choices before a mode-dependent pilot; during beginner intake ask one unanswered item at a time. In an established project, combine remaining choices in a short question:

- **Output:** images only; a video edited from still images; or an animated video. Default to still-image editing when the user asks for the reference's original treatment. Do not interpret “images instead” as permission for video generation.
- **Scope:** prompts/board only, generate assets, or deliver the assembled video. Do the requested work; prompts are not generated assets, and assets are not a completed video.
- **Reviews:** offer character-sheet and scene-image review independently. Default to both reviews when unspecified; “do it yourself,” “no approvals,” or an equivalent clear instruction waives creative pauses. Once decided, retain the choice.

Use the supplied aspect ratio. Otherwise default to 9:16. Use GPT Image 2 through KIE for images unless the user chooses another image model or platform during setup. In animated mode, honor Grok Imagine 1.5 or Kling 3 selection; if neither was chosen, use Grok Imagine 1.5 for simple single-scene motion. For an explicitly chosen alternative platform, verify supported models before selecting an equivalent route; KIE-specific request fields do not transfer automatically. Do not silently substitute a different provider or model.

Keep a small `project.json` in the current task's project folder: input paths/hashes, mode, scope, review choices, model choices, and completed/current stage. Record actual approvals against the relevant asset IDs/versions. This is resumable working state, not another approval document for the user.

## 2. Lock the words and measure the audio

When voiceover is available, run the bundled helper from this skill's directory:

```bash
python3 scripts/voiceover_timing.py probe /absolute/path/voiceover.wav --fps 30 > /absolute/project/timing.json
```

Requires Python 3.10+, FFmpeg and ffprobe. It decodes the selected audio stream at its original sample rate, counts samples including silence, and reports duration, source hash, and frame rounding. Read [timing and delivery](references/timing-and-delivery.md) before constructing the timed board or final export.

- Report the measured duration in seconds and `MM:SS.mmm`, plus the sample count/rate in the working record. Never call a word-count estimate exact.
- Preserve the original recording. Do not trim pauses, time-stretch, regenerate the voice, or alter wording unless requested.
- Use supplied timestamped text when it matches the current recording. When usable timestamps are missing, including when the user supplies only untimed text, use **OpenAI Whisper (`whisper-1`)** with word and segment timestamps when API access is available. **Without an OpenAI key, use local open-source Whisper with word timestamps; do not stop to require an OpenAI account.** Also honor an explicit local-only preference. Use the applicable route and the spoken-word truth-pass in [timing and delivery](references/timing-and-delivery.md). If no text is supplied, transcribe the recording in its original language. Preserve any supplied script verbatim; use Whisper to recover timing, not rewrite it.
- Verify transcript and timing against the recording, listening around edits, names, numbers, pauses, and every planned visual or caption cue. Whisper timestamps are a starting point for alignment, not proof of frame accuracy. If the recording differs from the script, retain both and resolve which words govern captions before final caption export; picture timing still follows the recording.
- With script only, proceed with visual planning and label timing provisional. Exact timing and final synchronization wait for the recording. Do not create a voice without authorization.

**Ready:** actual audio duration and verified phrase/word cues are available, or the board is explicitly provisional.

## 3. Choose the cast and visual world

Read [visual direction and prompt patterns](references/visual-direction.md). Inspect the [reference sheet](references/reference-frames.jpg) on the first use; inspect any new user references too. The reference establishes treatment, not new-project facts, characters, brand, offer, or historical setting.

Choose the smallest cast that makes every script role and relationship clear. Count recurring identities separately from anonymous extras; explain the chosen count in one sentence. A recurring protagonist, helper, antagonist, and crowd are options, not a fixed formula. Zero characters is valid for a product/diagram-only script. Do not add a visible narrator just because the audio has a narrator.

For each recurring character, lock ID, role, silhouette, proportions, face, wardrobe/palette, signature prop, and expression range. Create a separate character-sheet prompt per identity. Add a shared scale lineup only when characters appear together. Create set or product reference prompts only when repeated appearances need those anchors.

Generate requested reference images through [KIE](references/kie-api.md), or the explicitly chosen and verified platform, then inspect them. Use clean single-character views as scene references; do not use a multi-person sheet as an ambiguous identity source. Save the actual file and provider URL for each reference.

**Character review, if enabled:** show the generated sheet(s), identify what is being approved, and stop dependent scene-image generation until approval. A prompt-only request can stop at prompt approval, explicitly distinguished from approval of generated artwork. Character approval does not approve unseen scenes.

## 4. Build the timed scene board and image prompts

Map complete spoken thoughts to visual beats. Choose the scene count from meaning, visual changes, and delivery pace; use the reference's typical 1–4 second holds as a starting point, not a rigid grid. Let a readable diagram hold longer. Include pauses and the final audio tail in coverage. Use a change of place, subject, comparison, consequence, or reveal to justify a cut.

Create one readable board, also saved as `scenes.json` for timing checks. Each scene needs:

- ID, source start/end samples (or explicitly provisional times), duration, and exact spoken text.
- Visual purpose, character/set/product IDs, composition and relevant continuity.
- One complete image prompt and ordered reference mapping, with each image's role explained.
- Intended cut or image-state change; separately editable caption text/timing.
- The exact spoken word/phrase and verified source sample for each meaningful reveal, action or caption cue. Plan its target output frame using the shared timeline; let a relevant image hold across a complete thought rather than forcing a cut on every word.
- In animated mode only: first-frame asset, motion prompt, requested provider duration, usable trim range, and model.

Every final scene prompt must stand alone: expand the relevant character locks, scene action, spatial arrangement, palette, linework/texture, and aspect ratio. Do not leave “same as above,” unresolved placeholders, or a style name alone as the generation instructions. Images should make the sentence understandable before the caption is read.

Generate scene images through the chosen platform (KIE by default), only within the requested scope and existing generation authorization. Inspect each for cast identity, hands/props, intended action, spatial relationships, fabric/material texture, caption space, and visual connection to the line. Fix only the affected images. Preserve approved characters and sets when repairing a scene.

**Scene review, if enabled:** show generated scenes in order with IDs, timestamps, and matching lines. A storyboard description is not approval of the rendered images. Wait for approval before generating any dependent video clips or final still-video export. Approved images can be delivered as the images-only result at this point.

## 5. Produce the selected mode

**Images only:** deliver ordered images, character references, full prompts/reference mappings, and the scene timing map. Finish here; create no image-to-video prompts or video API jobs.

**Video from stills:** use the scene images directly, hard cuts, and separately rendered captions. Held framing is the reference default. Add subtle movement only if requested or explicitly selected. Skip image-to-video prompting and all video-provider calls.

**Animated video:** read the video section of [KIE API](references/kie-api.md), or the verified adapter documentation for an operator-chosen alternative. Animate each accepted scene from its actual first-frame image. Use one meaningful action, a restrained environmental detail, and a stable camera or one modest camera move. Keep character design, composition, object count, fabric, and painted texture consistent. Characters stay silent under the supplied voiceover unless the user explicitly requests speech. Do not replace the voiceover with generated dialogue.

Use separate clips per editorial scene by default. Match valid provider durations, then trim the visual to the board duration; do not stretch the voice to match the generated clips. For scenes exceeding a model limit, split at a meaningful beat with an explicit cut/continuity plan. Use a verified last frame as the next starting frame only when continuous motion is actually needed. Store and inspect returned clips before calling them usable.

## 6. Assemble and verify the deliverable

When the requested scope includes an assembled video, follow [timing and delivery](references/timing-and-delivery.md). Validate scene coverage, assemble the original voiceover at normal speed, apply captions in editing, then decode and inspect every output frame and play the complete export with sound. Verify cuts, visual reveals, animated actions and captions against their recorded audio cues; repair mismatches and review the affected frames again. Check the first/last seconds, all text, visual identities, and actual final duration. Report any frame-grid or codec-padding difference from the audio duration accurately. Do not claim perfect synchronization from Whisper output or a passing timing check alone.

For prompt-only scope, completion means a complete usable prompt package with its remaining input dependencies identified. For asset scope, completion means actual inspected files. For assembled-video scope, completion means the final playable export, verified duration/sync, and the supporting assets. Report incomplete provider jobs or blocked stages honestly; successful submission is not final delivery.

## Execution and revisions

Use existing provider credentials from the project environment or `.env` without exposing them; never store secrets in the skill or prompts. Prepare concrete batch counts and model settings before a paid request. Honor existing generation authorization and any spending ceiling; ask once only when the proposed spend is not already authorized. Creating this skill or requesting prompts does not authorize paid generation.

Track submitted task IDs and results so resuming does not duplicate charges. On an uncertain submission, reconcile the existing task before resubmitting. A generation failure gets one targeted retry only if covered by the user's authorization; then report the failing scene and alternatives. Do not change models or expand the budget automatically.

On revision, preserve unaffected approved work. A changed character invalidates review of scenes containing that character; a changed scene invalidates its clip. Audio replacement requires remeasurement and realignment, but does not by itself discard still images whose visual meaning remains valid. Continue from the earliest affected stage, with only the reviews the user selected.
