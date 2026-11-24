---
name: drama-ad-machine
description: Fully produce a live-action AI "drama ad" (story-driven UGC-style film with a cast, voices and an end card) end to end — intake, script, cast pack, ElevenLabs voices, pilot, background batch generation on kie.ai Seedance 2.5, Whisper QC and ffmpeg assembly into MASTER.mp4. Use when the user asks for a drama ad, story ad, mini-film ad, Seedance 2.5 ad, or wants an AI video ad generated automatically from a product and angle.
---

# Drama Ad Machine

## Learned rules and taste (read first)
Before planning any ad: run `.venv/bin/python -I tools/feedback.py rules drama-ad-machine` and obey every rule (they are owner corrections), then `tools/taste.py brief drama-ad-machine` for the reference ads. Set `"skill": "drama-ad-machine"` in the project's plan.json so notes and rule versions are tracked. After the owner reviews, log his notes with `ad.py <project> notes` and promote general ones with `feedback.py promote`. The full loop is in `FEEDBACK_LOOP.md`.

Read `SOP.md` in this folder in full before doing anything; it is the binding procedure (Parts 0–7). Follow its stages and gates exactly: no paid generation before the gate that authorizes it.

## Local environment (this machine)
- Project root: the repo root (run everything from there). Create each ad in `projects/<ad-name>/` with the SOP's folder layout.
- Keys live in `.env` (`KIE_API_KEY`, `ELEVENLABS_API_KEY`). Never print or echo them.
- Python: `.venv/bin/python` (has httpx, openai-whisper, mlx-whisper, pillow). `ffmpeg`/`ffprobe` are on PATH.
- Shared scripts built on first run (`batch.py`, `assemble.py`, `kie.py`) go in `tools/` and are reused by every project.
- Run batches in the background, never in the foreground.
