# AI Ad Machine: agent instructions (Claude Code + Codex)

An automated AI video-ad system: it writes, generates, edits, checks and delivers 9:16 video ads for the brand
described in `brand/brand.json`. The owner gives light QA only. Everything about the brand and product (name,
look, how it works, things never to show, offer line) comes from `brand/brand.json` and the photos in
`brand/product-photos/`. Never invent product facts; if a field is empty, ask the owner once.

## How to work
- One short session per ad. Drive everything through `tools/ad.py <project-dir> <stage>`:
  `vo -> frames -> clips -> qc -> review -> notes -> redo / redo-failed -> stitch`. Also `rules`, `lock`, `unlock`,
  `realign`, `soundoff ["HOOK"]` (muted Stories/Reels cut -> `MASTER-soundoff.mp4`, never touches MASTER).
  If a stage is missing, extend `ad.py`; do not run one-off commands in chat.
- Run tools with `.venv/bin/python` from this folder. API keys live in `.env`: never print, copy or log them.
- Do not open frames or image strips to look at them unless the owner asks about one specific thing. QA is text:
  `ad.py qc` (vision checker), then read `QC/qc_report.md`. The owner approves visually in `REVIEW.html` and pastes
  back the "Copy notes" text.
- Every visual plan gets a reviewer pass before any image is generated: `tools/plan_review.py <project>`.
  Run the course's sanity pilot before a new kind of ad.
- Generation stages (`frames`, `clips`, `vo`, `plan_review`) take minutes. Run them in the background and poll the
  log every 30-60 s. Jobs resume from their saved task id, so a killed job is re-run, not restarted from scratch.
- Stages need outbound network (kie.ai, ElevenLabs, Claude). If a call fails with "Could not resolve host", stop and
  tell the owner.
- Never state a price, cost or credit estimate you have not measured. Check kie.ai pricing before spending.

## Before producing any ad
0. Read `brand/brand.json` and `feedback/OWNER_TASTE.md` (the owner's taste rules, T-rules). T-rules win over every
   other rule. Source: `feedback/taste_rules.json`; they grow from the owner's review notes.
1. `ad.py <project> rules` and `tools/taste.py brief <skill>`; set `"skill"` in `plan.json`.
2. Read `feedback/RULES_universal.md` and `feedback/RULES_<skill>.md`. Do not remove a rule without an owner note
   saying it is wrong.
3. For anything that shows the product, check frames with `tools/product_check.py` against `brand/product-photos/`
   before paying for video.

## Before ANY delivery (Frame.io, Drive or chat)
`.venv/bin/python tools/preflight.py <project> [--file X.mp4]` runs on the finished video: 9:16, tilted text, repeated
shots, cuts in the hook, freezes, banned clips, loud audio tail, av_check, caption sync, banned phrases from
`brand.json`. It writes `PREFLIGHT.md`: every taste rule plus every earlier note on this ad as boxes to answer
`[x]` / `[n/a]`. Fix every FAIL. `frameio.py push` refuses until PREFLIGHT matches the exact file.

## Hard rules
- Captions come from Whisper plus voice onsets on the real audio, never TTS timestamps. Every `stitch` ends with
  `caption_sync_check.py` PASS. A FAIL is not deliverable.
- Same-voice consecutive beats render as ONE take. Never rerun `ad.py vo` on a finished ad for a clip-only change.
- Videos are always 9:16. Text and boxes are always straight and centred.
- The product's outline must never change inside a clip. Never show anything in `brand.json` `never_show`.
- Launched ads are locked (`ad.py <p> lock`). Never redo, re-render or edit a locked ad. Hook variants start unlocked.
- Mark a batch Approved only after the owner confirms ALL hooks. "Make more variants" is not approval.

## After owner feedback
Log feedback as it arrives, before fixing: `tools/feedback.py add <project> "<owner's words>" --src chat [--beat N] [--skill S]`.
Review-page pastes go through `ad.py <p> notes`. Every note is auto-tagged against the taste rules: `REPEAT Txx` means a
known mistake came back (fix it and add a check if one could have caught it); `NEW #id` means learn it now with the
`learn` skill (`feedback.py taste-add "<title>" "<rule>" --re "<regex>" --ids <id>`). A clip he rejects goes into
`footage/BANNED_CLIPS.json`. `feedback.py top` = most repeated this week. Full loop: `FEEDBACK_LOOP.md`.

## Real-footage editor
`tools/rawedit.py` edits REAL creator takes (no kie spend): a-roll + b-roll from the owner's footage library
(`footage/INDEX.csv`, clips cached in `footage/raw/`). Skill `raw-ugc-editor`; rules `feedback/RULES_raw-ugc-editor.md`.
Stages: `new -> transcribe -> pack -> (write keep ranges) -> plan -> broll / set-broll -> storyboard [gate] -> render
-> verify -> fcpxml`, plus `captions`, `variant` (new opening, same body), `mirror`. Voiceover mode:
`rawedit.py new <ad> --vo <voice.wav>`. `tools/moments.py build` splits library clips into searchable moments;
`moments.py search "<what you need to see>"` finds b-roll. `tools/shot_check.py <project>` checks every planned shot
against its line before rendering.

## Editing knowledge
`knowledge/video-editing-course/EDITING_KB.md` is the editing playbook. Read it before editing ANY ad: hook text on screen
from frame one, a visual change every 2-3 s, b-roll matching, music (drop on the hold, EQ notch), captions and Meta safe
zones, SFX. Course notes: `course/` and `TRANSCRIPT_FINDINGS.md`. Course skills: `skills/course/`.

## Music, SFX, motion graphics
Music is local: `library/music/` (`tools/music_lib.py`; add your own tracks). In a plan set `"music_mood"`. SFX:
`library/sfx/` (`tools/sfx.py`). Motion graphics: `tools/hf <cmd>` (HyperFrames CLI). Song ads:
`tools/music.py song|times|hook` -> `tools/song_plan.py` -> the normal stages.

## No paid Claude API needed
Every tool that calls Claude imports `tools/claude_client.py`: it uses `ANTHROPIC_API_KEY` if set, otherwise headless
`claude -p` on the owner's Claude Code login (plan usage, no API bill). New tools must use it too. Force a path with
`CLAUDE_BACKEND=cli|api`.

## Cloud controller and ad board
Ads can run in the cloud through `cloud/ctl.py` (run with `.modal-env/bin/python`). Setup: `cloud/docs/SETUP_CLOUD.md`;
full guide: `cloud/docs/CONTROLLER.md`. `submit <recipe> <ad,ad,...> --go [--batch "<name>"]` starts one cloud pipeline
per ad; `status`, `collect` (downloads and runs the Mac final checks), `notes`, `revise-plan`, `reviews`, `usage`.
`ctl.py dash` opens the ad board (In progress / Frames to approve / Ready for review, Approve buttons, Usage page).
Paid recipes need the per-ad kie cap in `cloud/controller/config.json` (`kie_cap_per_ad`); the Modal monthly cap is
`modal_cap_usd`. If a cap is hit, tell the owner.

## Where things are
`brand/` your brand + product photos · `projects/<ad>/` one folder per ad (`plan.json`, `MASTER.mp4`, `REVIEW.html`) ·
`skills/` Claude Code skills (linked into `~/.claude/skills` by `install.sh`) · `feedback/` taste rules, learned rules,
note log · `footage/` real clips · `library/` music, SFX, fonts · `tools/` all scripts · `cloud/` cloud controller + board.
