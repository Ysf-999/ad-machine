# Audio timing, scene coverage and delivery

## Measure before allocating scenes

Run `scripts/voiceover_timing.py probe` on the actual local recording. The canonical measured duration is `decoded_samples / sample_rate`. This is an exact rational count of the selected stream's decoded playback samples, including leading/trailing silence. Container metadata is also reported, but is not silently substituted for that measurement. Keep all original audio; non-speech pauses are still timeline content.

The helper does not transcribe or align words. Use user-supplied timecodes when they match the current audio. If timecodes are missing, incomplete or from a different recording, use the Whisper workflow below for the affected material. With script only and no recording, scene timing remains provisional and no sample-based timing check can be claimed.

A video with several audio tracks needs an explicit voiceover track choice (`--audio-stream` uses zero-based audio-track order). Measure that track, not the longest stream or the video container. Record the selection. The helper is read-only and requires FFmpeg/ffprobe on PATH; if they are missing, locate the available runtime or report the missing dependency rather than estimating.

## Use OpenAI Whisper when timestamped text is missing

This applies both to audio without text and audio accompanied by an untimed script. With available API access, use the hosted route below. **Without an OpenAI key, or when local processing is preferred, use local Whisper automatically.** No extra account is required. Preserve the same original recording and verified timing-map format in either route; record which engine/model produced the draft timings.

### Hosted route when API access is available

Use OpenAI's transcription endpoint, `POST https://api.openai.com/v1/audio/transcriptions`, with **`whisper-1`**, `response_format="verbose_json"`, and `timestamp_granularities=["word", "segment"]`. Follow the [official speech-to-text guide](https://developers.openai.com/api/docs/guides/speech-to-text); verify current limits before execution. Do not substitute another hosted speech model or the translations endpoint.

Example using the OpenAI Python SDK and an existing `OPENAI_API_KEY`:

```python
from openai import OpenAI

client = OpenAI()
with open("/absolute/project/voiceover.wav", "rb") as audio_file:
    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        response_format="verbose_json",
        timestamp_granularities=["word", "segment"],
    )
# Preserve transcript.model_dump_json() as the raw transcription result.
# Review transcript.words and transcript.segments against the recording.
```

Use an ISO 639-1 `language` hint when known; transcribe in the spoken language. A short optional `prompt` can supply names or unusual terms, but does not force-align a script. Preserve supplied wording in its own original file and reconcile recognition errors against the audio. Never invent inaudible words or replace the supplied script with an unchecked transcript.

The documented upload limit is 25 MB; accepted formats include MP3, MP4, MPEG, MPGA, M4A, WAV and WebM. For larger files, prepare a smaller working copy with unchanged playback timing, or split at sentence/pause boundaries. Keep exact original start offsets for chunks, convert returned local timestamps to the original timeline, and resolve duplicated words in any overlap. Check chunk joins for missing speech and timing shifts. Keep the original recording for measurement and assembly; the final Whisper word endpoint is not the full audio duration.

Use existing transcription authorization and credentials from the environment or project-root `.env`; never expose the key or include it in deliverables. Only the voiceover or necessary chunks go to OpenAI for this route; image generation remains on the chosen media platform. If hosted access is missing or unusable, use the local route instead of blocking on an API key. Creating or updating this skill does not run transcription.

### Local route without an OpenAI key

Use the official `openai-whisper` package prepared during [setup](setup-and-intake.md). Choose a multilingual model that fits the machine; `small` is a practical CPU starting point, while a capable machine can use `turbo` or a larger model. Improve the model choice if the recording's language or recognition quality requires it. Do not call a local checkpoint `whisper-1`, which is the hosted API model name.

Example CPU invocation from the project root; adapt the executable path to its actual virtual environment:

```bash
.venv/bin/whisper "/absolute/project/DROP/voiceover.wav" --model small --device cpu --fp16 False --task transcribe --word_timestamps True --output_format json --output_dir "/absolute/project/work/transcription"
```

These options are defined in [Whisper's transcription implementation](https://github.com/openai/whisper/blob/main/whisper/transcribe.py). Preserve raw JSON. Read word start/end values from each segment's `words` list and normalize them into the shared timing map. Use the complete recording or preserve original offsets for any chunks; do not shift the timeline by trimming silence. Model decoding is approximate and still needs the checks below. If local execution also fails, repair the runtime or flag the actual missing dependency; never replace missing word timings with estimates presented as verified.

### Spoken-word truth-pass and timing verification

When an independent audio-capable second model is available within existing access, have it listen to the same recording or flagged excerpts without anchoring its answer to the first transcript. Compare words and flag disagreements, omissions, names, numbers, low-confidence passages and speech detected in silence. An already available local model with different weights can provide this second pass. Keep any cloud use within existing upload/spend authorization. A text-only model can flag suspicious text but cannot verify what was spoken.

If no suitable second model is available, use single-model transcription and **an operator ear-check on every flagged word**. Show each flag with its timestamp, short playable excerpt and candidate reading; record the operator's correction or confirmation. Do not invent a confirmation, silently clear a flag, or finalize dependent captions while it remains unresolved. Even with two models, agreement does not replace listening to uncertain words and timing cues. Preserve supplied script/lyrics verbatim and surface discrepancies with the recording rather than rewriting the source.

Save the raw result and one verified timing map tied to the original audio hash, with word/phrase text, global start/end times, and corrections or unresolved regions. Listen through the recording while checking the transcript. Inspect the waveform and replay every planned cut, action, reveal and caption boundary; correct early/late timings and false speech in silence. Use further alignment or listening when a boundary remains uncertain. Supplied valid timestamps remain authoritative unless the user authorizes a correction. Convert verified seconds to the nearest source sample once. Never distribute words evenly through a sentence or label unchecked ASR timing as exact.

## Scene timing format

Use half-open intervals `[start_sample, end_sample)`, in the order they play. Example for a three-second, 48kHz recording (illustrative numbers only):

```json
{
  "source_sha256": "Use the actual hash from timing.json",
  "scenes": [
    {
      "id": "S001",
      "start_sample": 0,
      "end_sample": 72000,
      "spoken_text": "The exact first phrase.",
      "characters": ["C01"],
      "visual_purpose": "Show the action described by the phrase",
      "image_prompt": "The complete expanded image prompt",
      "reference_ids": ["C01-front"],
      "transition": "hard_cut"
    },
    {
      "id": "S002",
      "start_sample": 72000,
      "end_sample": 144000,
      "spoken_text": "The exact remaining phrase.",
      "characters": [],
      "visual_purpose": "Show the consequence in an object close-up",
      "image_prompt": "The complete expanded image prompt",
      "reference_ids": [],
      "transition": "hard_cut"
    }
  ]
}
```

Store all actual scene prompts and references in this one board. Add `image_path`/URL after generation. Only animated scenes need a motion prompt, video model/request duration, video path and trim interval. Captions may be kept separately in SRT/ASS because their phrase boundaries differ from scene cuts. Do not duplicate the narration across separate conflicting authorities.

For each meaningful cut, reveal, action or caption cue, record the matching word/phrase, verified global source sample, and intended visual event in the scene board. Map it to the shared output-frame grid, accounting for any explicitly planned anticipation or reading hold. Each scene must depict the subject, action and relationship of its spoken passage; a visually attractive but unrelated frame needs revision. This is cue-based editing, not a requirement to generate a new scene for every word or video frame.

Run:

```bash
python3 scripts/voiceover_timing.py check /absolute/project/timing.json /absolute/project/scenes.json > /absolute/project/frame-plan.json
```

This checks the board's source hash against the timing record and rechecks the local audio file, rejecting replacement since measurement. The original audio must remain accessible at `source_path`; update that path if the unchanged file was moved. It validates unique scene IDs and complete, positive, ordered scene coverage with no gaps/overlaps, then returns global frame boundaries for assembly. It does not check script meaning, approve artwork, transcribe speech, call KIE, or prove creative quality.

## Exact audio versus a video frame grid

At frame rate `F`, use `ceil(decoded_samples × F / sample_rate)` total video frames. Allocate each boundary from its global sample timestamp, then subtract neighboring boundaries for scene frame counts. Never round each scene's duration independently; that accumulates drift.

The last image covers the complete audio tail. The CFR video endpoint may be less than one frame longer than the exact audio duration. Report this difference rather than falsely claiming sample-exact video duration or cutting the last syllable. Audio codec padding can also affect container metadata; inspect decoded audio, stream timestamps and the audible ending when it differs. Keep the locked voiceover at normal speed and untrimmed. No automatic silence removal, time-stretch or voice replacement.

Place internal visual cues on the same global frame grid as scene boundaries. Record the requested sample and actual frame time; their rounding difference must stay within one output frame. This measures frame-grid rounding only, not the accuracy of Whisper's word boundaries. For animation, describe each key action's time relative to the retained clip, then inspect the generated action's actual landing frame after trimming. A timed motion prompt does not guarantee timed output: adjust the visual edit or repair the affected clip when the action misses its cue, leaving the voiceover unchanged.

## Assemble only when requested

- **Images only:** numbered images, character/set references actually used, ordered prompts/reference mapping and timing map. No video jobs and no final video render.
- **Still-image video:** convert each image to its allocated frame count, normalized dimensions and FPS, then concatenate with hard cuts. Preserve composition when fitting the canvas; choose intentional crop or padding. A requested crossfade must overlap within the existing timeline, never add runtime.
- **Animated video:** inspect and trim the generated visuals to the allocated scene frames. Normalize their dimensions, FPS, timebase and pixel format. Strip every generated audio track before adding the user's original voiceover. Do not loop visibly mismatched motion to hide a short clip; repair that clip or use an explicitly accepted still hold.

Apply editable captions after picture assembly. Preserve supplied wording, punctuation and casing unless the user asks otherwise. Keep titles and numbers editable when their exact spelling matters. Fit captions to mobile-safe margins and avoid covering the key action. Preserve intended color range/aspect ratio; a typical delivery is H.264 MP4 with yuv420p video and an appropriate audio track. Honor the actual requested format and delivery-size limit.

## Review every frame against the audio

Decode the entire export with FFmpeg to detect corruption. Probe actual duration, video frame count/FPS, dimensions and audio streams. Review all decoded output frames in order, using frame stepping or consecutive frame sheets at readable size; enlarge uncertain frames. Check for identity drift, malformed hands/props, flicker, blank or duplicated frames, broken text, unintended crop changes, and incorrect scene content. Deliberate still-image holds are valid repeated frames.

Play the complete export with the original audio while following the verified timing map. For every cut, reveal, key action and caption boundary, inspect the frame before, at and after the cue and replay its surrounding phrase. Confirm that the visible event lands on the intended spoken cue, the image remains relevant throughout the passage, captions match the words heard, and no cue drifts later in the video. Check the opening, pauses, chunk joins if used, and final syllable/audio tail. Confirm legibility and absence of unexpected generated sound. Frame sheets alone cannot establish audio sync; normal-speed playback alone can miss single-frame defects.

Repair the affected image, clip, edit or caption timing, then review the changed frames and neighboring cues in the actual re-export. Keep a concise record of reviewed frame ranges, cue corrections and unresolved issues. Only claim full frame review when every output frame was covered, and verified synchronization when audiovisual review was completed. Automated timing checks and Whisper timestamps alone do not prove either.

Deliver the playable final file and concise validation result, including any real duration difference. Keep a copy of the original voiceover plus editable timing/captions/assets so revisions do not require regenerating accepted work.
