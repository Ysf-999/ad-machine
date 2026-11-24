# Beginner setup and sanity pilot

Read this for first-time setup or a change of platform/runtime that invalidates earlier verification. Work in the operator's current project. Check existing setup and inputs first; explain only the next thing they need to do. Do not hand a beginner a long technical checklist to execute themselves.

## Access and a resumable client

KIE is the default aggregator; start with the current [KIE index](https://docs.kie.ai/llms.txt) and the bundled [KIE execution reference](kie-api.md). When the operator explicitly selects a different platform, read its own API documentation and confirm text-to-image, reference-image editing, and the requested image-to-video route. Verify that image editing actually accepts reference images; a text-only endpoint is insufficient. Keep model IDs, request fields and credentials specific to that platform.

Only ask for an account/key when no usable access is already configured. Use the onboarding wording in Stage 0. Save the key as `KIE_API_KEY` for KIE or the chosen client's documented environment variable in the project-root `.env`; preserve unrelated entries. Load it as data with an environment loader, not as executable shell content. Keep `.env` out of version control, logs and deliverable archives. Confirm only that the key was saved, never its value. An `OPENAI_API_KEY` is optional because transcription can run locally.

Use an existing working client/connector where possible. Otherwise build a small project-local adapter for submission, status and download. Before submitting, append the intended request without secrets to `jobs.jsonl`. Immediately after receiving a task ID, append and flush its asset/version, provider, model, request identifier and task ID to disk **before** polling, downloading or starting another generation. Persist later state changes and paths as well.

On restart, read the journal and resume existing IDs. Retry safe status/download requests with bounded backoff; keep accepted but unfinished jobs pending after a local timeout. A failed generation may receive the already-authorized targeted retry, recorded as a new attempt linked to the previous ID. An ambiguous submission must be reconciled through the provider's supported history/status mechanisms; if no ID can be recovered, leave it marked uncertain and resolve it before a new paid submission. Do not invent idempotency support or treat an empty local ID as proof that nothing was created.

## Set up the local tools yourself

Create these project directories without overwriting existing files:

| Folder | Purpose |
| --- | --- |
| `ANCHORS/` | Character, set and product reference images |
| `STILLS/` | Ordered scene images |
| `CLIPS/` | Generated animation clips |
| `DROP/` | Operator-supplied voiceover, product photos and other inputs |

Keep pilot assets in a separate `work/setup-pilot/` folder and retain project state/journal at the root. Copy supplied assets into `DROP/` only when helpful; preserve their originals and hashes.

Check `ffmpeg` and `ffprobe`. Install missing tools yourself when the environment permits. If an operator action is needed, provide just the applicable command: `brew install ffmpeg` on macOS with Homebrew, `sudo apt install ffmpeg` on Debian/Ubuntu, or `choco install ffmpeg` on Windows with Chocolatey. If that package manager is absent, resolve its installation from its official instructions instead of assuming it exists. Recheck both executables after installation.

Prepare local Whisper in a project virtual environment using a compatible Python; Python 3.11 is a conservative starting choice, not a reason to replace an already working runtime. Read [OpenAI's local Whisper setup](https://github.com/openai/whisper#setup) for current dependencies. Example on macOS/Linux after locating Python 3.11:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -U openai-whisper
.venv/bin/whisper --help
```

On Windows, use the equivalent `.venv\Scripts\python.exe` and `whisper.exe`. Reuse a functioning environment; do not repeatedly upgrade it. Check import, CLI word-timestamp support and model loading. Select a model the machine can run, record its name, and cache weights for reuse. First installation/model download needs internet; local transcription thereafter needs no OpenAI key or audio upload. If a runtime dependency fails, resolve it locally before declaring transcription ready.

For the narration/lyric truth-pass, use an available second audio-capable model to check the recording independently when access is already authorized. Otherwise use the single-model plus operator ear-check path in [timing and delivery](timing-and-delivery.md). A second model is useful corroboration, never a requirement to buy another API subscription.

## Prove the chain on a tiny scale

A fresh generation setup must pass this pilot before its first real ad. Resolve the desired output mode first. Prepare the concrete pilot batch and current price estimate; use existing authorization/budget when sufficient, otherwise ask only for that concrete spend. A request to author or install this skill does not itself launch the pilot.

1. Generate one simple Finn-style anchor with the text-to-image route. Save and inspect the actual file.
2. Use that exact anchor through image-to-image to change one pose or setting while preserving identity and visual treatment. Check both the recorded reference input and the resulting still.
3. Animate the derived still with one simple action for the shortest useful supported duration. Save the actual returned clip; inspect motion, reference fidelity and decoding.
4. Make a 10-second test edit containing the anchor, derived still and short animation. Allocate still holds to fill the time; avoid stretching the test animation just to reach ten seconds. Strip generated sound, then mux a 10-second excerpt from an available local music file. If there is no music file, create a simple local instrumental test file. Music is for this setup check; it does not become the production voiceover or add a music requirement to real ads.
5. Decode and play the finished test. Verify text-to-image, actual image-to-image reference use, animation, downloaded assets, dimensions/FPS, ten-second picture coverage and audible music. Review [timing and delivery](timing-and-delivery.md) for export/frame-grid checks. If a speech fixture or user voiceover is available, also run a short local transcription and inspect its word timestamps; instrumental music cannot verify speech recognition accuracy.

An explicit images-only mode verifies steps 1–2 and stops before video calls/rendering. A still-video mode verifies steps 1–2 plus the ten-second music assembly using stills. Record animation as **not tested**, and complete its pilot before the first animated production. Prompt-only scope defers the paid pilot until generation is requested. These cases do not count as verification of unexecuted routes.

Fix the failed link and repeat only its dependent steps; resume known task IDs and keep earlier valid outputs. Do not proceed into production with the required route unverified. Record `setup` in `project.json`: provider/models, tested capabilities, runtime versions, task IDs, evidence paths, checks passed and any remaining dependency. A previously passed pilot does not need repeating for every ad; refresh affected checks when the provider, models or runtime changes materially.

Only then give the Stage 0 intake handoff. If verification is partial, name the verified mode instead of claiming the full chain passed. Wait for the voiceover, relevant product/reference images and audience description that are still missing. Continue immediately when those inputs and production authorization already exist.
