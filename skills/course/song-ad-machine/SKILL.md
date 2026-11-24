---
name: song-ad-machine
description: Produce an animated song-led video ad (any illustration style) from an operator-made song — timestamp the song, build four anchor masters, generate the full storyboard and animated clips on kie.ai, then edit. Use when the user asks for a song ad, music-video ad, jingle ad or an animated film cut to a song.
---

# Song Ad Machine

## Learned rules and taste (read first)
Before planning any ad: run `.venv/bin/python -I tools/feedback.py rules song-ad-machine` and obey every rule (they are owner corrections), then `tools/taste.py brief song-ad-machine` for the reference ads. Set `"skill": "song-ad-machine"` in the project's plan.json so notes and rule versions are tracked. After the owner reviews, log his notes with `ad.py <project> notes` and promote general ones with `feedback.py promote`. The full loop is in `FEEDBACK_LOOP.md`.

Read `SOP.md` in this folder in full before doing anything; it is the binding procedure. Never generate before the gate that authorizes it.

## Local environment (this machine)
- Project root: the repo root (run everything from there); put each ad in `projects/<ad-name>/`.
- Keys in `.env` (`KIE_API_KEY`, plus others the SOP asks for). Never print them.
- Python: `.venv/bin/python` (httpx, openai-whisper, mlx-whisper, pillow); `ffmpeg`/`ffprobe` on PATH.
- Reuse shared tools in `tools/` (kie client, assembler) instead of rewriting them.

## Updates (override SOP.md where they differ)
- **The song step is automated.** Do not send the operator to ChatGPT and Suno. Use `tools/music.py song|times|hook` then `tools/song_plan.py`, then the normal `ad.py` stages (`plan_review`, `frames`, `clips`, `qc`, `review`, `stitch`). Exact commands and the pilot's measurements are in the `singing-ad-storyboard` skill's Local environment section. Never run `ad.py vo` on a song ad.
- **Lyrics do not rhyme** (standing owner rule): sing a normal script. This replaces SOP step 2.
- **Style box:** pick the genre for the buyer, not the product (old-school pop or R&B for older buyers). Never name an artist or track; describe the sound. Match the singer to the narrator with `--gender`.
- **Lyric truth-pass:** diff Whisper against the intended lyric, not only two transcribers against each other. A brand or hard-word mismatch rejects the take.
- **The ad opens on the first sung word.** Suno still put 8.8 s of intro on the pilot despite the style text, so `song_plan.py` trims it. Never open on an instrumental.
- **Shot rhythm** (five proven singing ads): cuts follow the lyric, the first line holds one shot, about 2.8 s a shot, 1.7 s on the top scorer. `skills/extra/singing-ad-storyboard/scripts/beat_grid.py` builds the grid. Check it against R017 before the gate.
- **QA is text** (`ad.py qc`, REVIEW.html), replacing the SOP's self-read contact sheets and strips.
