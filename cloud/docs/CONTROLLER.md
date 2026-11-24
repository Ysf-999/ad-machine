# Cloud ad controller

One deployed Modal app, `<app_prefix>-ads` (`admachine-ads` by default; names in `cloud/names.py`), makes and edits ads in the cloud. The Mac sends the work up and does the final
checks when it comes back. Between those two moments the Mac can sleep or be closed.

Run every command from the repo root as `.modal-env/bin/python cloud/ctl.py <command>` (the Python that has `modal`).
First-time setup: `docs/SETUP_CLOUD.md`. Settings: `cloud/controller/config.json` (copy `config.example.json`).

## The loop

1. `submit <recipe> <ad,ad,...> --go [--batch "<name>"]` uploads what changed and starts one cloud pipeline per ad. It
   returns in seconds. Up to 24 ads per submit, and any number of submits: batches run side by side.
2. `status` shows every open run grouped by batch. `wait` blocks until they finish.
3. Finished runs are collected with `collect` (or by the watcher: while runs are open it looks every 45 seconds, so a
   finished ad is on the Mac about a minute later, while the Mac is awake): sha256-checked download, budget settled, then the Mac final checks one ad at a time (`rawedit verify` for
   real-footage ads, `preflight` for all). When `slack_user_id` is set, the watcher can DM the owner on Slack (GLOBAL STOP, refused pushes, long waits).
4. Answer the boxes in `PREFLIGHT.md`. The watcher then pushes the ad to Frame.io by itself: every pass, `auto_push()` pushes each ad the board shows as "Uploading next" (preflight on this file, every
   box answered, no FAIL), once per render, and posts the links on Slack. `"auto_push": false` in config.json turns it off.
5. Owner notes: `ctl.py notes` pulls Frame.io comments into the feedback log, `ctl.py revise-plan` turns the open notes
   into a batch file with every timed note matched to its beat or shot. Decide the fix for each note in that file, then
   `submit --from <file> --go` starts all the revisions at once.

## Recipes

| Recipe | Steps in the cloud | Spends kie |
|---|---|---|
| `raw` | shot check, then render + audio pad | no |
| `ai` | plan review, voice, stills, clips, then QC + assemble + master QC | yes |
| `ai-frames` | plan review, voice, stills, stills QC, then stop for the owner's frame review | yes |
| `ai-frames-revise` | redo the named stills, stills QC, stop again | yes |
| `ai-clips` | clips for the approved stills, then QC + assemble + master QC | yes |
| `ai-resume` | whatever stills and clips are still missing, then QC + assemble + master QC (voice kept) | yes |
| `ai-revise` | redo the named beats of a finished ad, then QC + assemble + master QC | yes |
| `ai-finish` | QC + assemble + master QC | no |
| `inserts` | stills + clips + QC (AI b-roll for a real-footage ad) | yes |
| `check` | offline readiness check | no |

The frame review works the way it does locally: `ai-frames` stops when the stills exist, `collect` builds and opens
`REVIEW.html`, the owner's notes become `--redo "<ad>:<beat>:frame:<note>"` items for `ai-frames-revise` (as many
rounds as he wants), and `ai-clips` makes the clips once he is happy. `ai` skips the review and goes straight through.
A song ad (its voice track already exists) uses `ai-frames` or `ai-resume`; the voice step is skipped, never re-made.

A step runs in the one worker kind that holds only what it needs: `run_plain` (no secret, network blocked), `run_gen`
(kie + ElevenLabs), `run_claude` (Claude login token). A fourth tiny function, `pipeline`, runs the steps in order and
writes the run's state to the Modal Dict `<app_prefix>-ads-status`. Up to 16 renders, 10 generations and 10 Claude steps run
at once; more than that waits in Modal's queue. An unpaid step whose worker crashed is tried once more.

## Batch files

`submit --from file.json --go` starts ads with different recipes in one go:

```json
{"batch": "Kitchen notes v3", "jobs": [
  {"ad": "kitchen-demo-h1", "recipe": "raw"},
  {"ad": "unboxing-15s", "recipe": "ai-revise", "redo": [[3, "clip", "slower swipe"], [5, "frame", "grey couch"]]},
  {"ad": "not-yet", "recipe": "raw", "skip": true}
]}
```

`revise-plan [ad ...]` writes such a file to `cloud/controller/revise-<time>.json` from the open notes in the feedback
log. Every job starts as `"skip": true` with its notes listed (`where` says which beat or shot is on screen at the
note's second). AI ad: fill `redo`. Real-footage ad: change the named shots in `plan.json`. Then set `"skip": false`.

## The ad board

`ctl.py dash` opens one local page (`cloud/.scratch/dashboard/index.html`): tabs, only work in progress and work
waiting for the owner, nothing approved, no notes section (revision notes are left on Frame.io).

- **In progress**: running in the cloud (with the step line), stopped by a check ("Claude to fix": the row says it is
  not the owner's job), frames he already answered on ("Frames approved" / "Frame notes sent"), or on Frame.io with notes
  that are not applied yet ("Revision to do"). No video button here: the video on the Mac is the previous version.
  A row only says a Claude is working while one is (see "Unattended Claude jobs"): a batch after "Revisions done" or a
  "Claude to fix" row with no activity for 30 minutes shows **Stalled — no Claude working on it**, and a job that
  stopped with a question shows **Needs you** with its sentence.
- **To approve**: clip picks waiting for him (see below), and AI ads stopped at their starting frames (a finished `ai-frames` / `ai-frames-revise` run, or a
  Mac-made ad with `REVIEW.html`, frames and no clip yet). The row shows the frames, an **Approve frames** button (two
  presses) and **Leave notes**, which opens the ad's `REVIEW.html`.
- **Getting ready**: finished, final checks open or not uploaded to Frame.io yet (dropped after 7 days untouched).
- **Ready for review**: on Frame.io, with the link, an **Approve** button (two presses) and **Approve all N** on a batch.
  Each video that is not approved also has a quiet **Revisions done for this video** link under its buttons (see below).
- **Sent to Drive**: approved batches on Google Drive, with **Copy link**, **Open in Drive** and an **In the media buyer
  sheet** tick. Unticked rows never drop off and are what the tab counts; a ticked row folds into a closed **In the sheet**
  dropdown (once it is in the sheet it needs no tracking) and leaves the page after 30 days.

A locked ad is never shown. `ctl.py dash --hide "<ad or batch>"` takes something off
the board (`controller/board-hidden.json`), `--unhide` puts it back, `--hidden` lists them; the owner can also hide a row
himself in the page (kept in his browser). Built by `cloud/dash.py` from files only (run registry, each project's
`frameio.json`, `PREFLIGHT.md`, `MASTER.mp4`, `REVIEW.html`, `FRAMES/`), so it never starts, changes or uploads anything
and the pipeline never waits for it. The watcher, `status`, `submit` and `collect` rewrite it; the page reloads itself
every 30 seconds and keeps the open tab. Test ads (`zz-*`, `cloud-test*`) show only while they run.

## Frame approvals from the browser

The owner no longer pastes anything. "Approve frames" on the board and "Send to Claude" on a `REVIEW.html` post to a
small helper on this Mac (`cloud/frame_review.py serve`, 127.0.0.1:8790, started by `ctl.py dash` and by the watcher;
restarted by itself when the file changes). It writes `projects/<ad>/FRAME_REVIEW.json` (newest decision),
`FRAME_REVIEW.log.jsonl` (all of them) and `FRAME_REVIEW.txt`; notes that ask for changes are logged through
`tools/feedback.py ingest` like any other revision. Requests need the token in `controller/board-token`, which only
local pages carry. Log: `cloud/.scratch/frame-review.log`.

- **Ad made by the controller** (newest run is a finished `ai-frames` / `ai-frames-revise`): approving starts
  `ctl.py submit ai-clips <ad> --go` by itself (the button says "Approve and start clips"); frames to redo, each with a
  note, start `ai-frames-revise` with his notes as the `--redo` notes. The exit of that submit is written back into
  `FRAME_REVIEW.json`; a refused submit shows on the board as "Claude to fix". Not yet proven on a live paid run.
- **Any other ad** (built by hand on the Mac): the decision waits. `ctl.py reviews` lists it, `ctl.py status` prints one
  line about it, the board shows it under In progress. Act on it without asking him again. It clears by itself when
  newer frames exist (a redo was done) or clips exist (the approval was used); `ctl.py reviews --done <ad>` otherwise.
- A decision is refused (with a sentence he can read) when a frame has no choice, or when the page is older than the
  frames on disk. The board rebuilds a `REVIEW.html` that is older than its frames.
- `REVIEW.html` remembers choices and notes per file version (name + time): a redone frame starts with an empty box.
  If the helper is not running the page copies the notes to the clipboard instead, as before.

## "Revisions done" (one button per batch, one per video)

One button tells Claude that the owner has left his revision notes as Frame.io comments. It sits on the batch header (Ready for review and
In progress) of every Frame.io batch, two presses. The helper (`/revisions`) records the press in
`controller/revision-requests.json` (+ `.log.jsonl`), then pulls the Frame.io comments of the videos he sent into
`feedback/log.jsonl` (`frameio.py pull <ad>` per ad, so one deleted file cannot stop the rest) and counts the open notes
per ad. State: pulling -> waiting (or no-notes, shown on the header) -> working -> done.

- **Which videos.** The request's `ads` list is exactly what he sent, and nothing else is revised.
  The batch button sends every video of the batch on Frame.io that is not approved and not locked (an approved video is
  never sent; if none is left the button is not shown and a press answers "nothing to revise"). The row link
  **Revisions done for this video** (Ready for review and "Revision to do" rows, two presses, `/revisions` with
  `{ad}`) sends that one video and pulls only its comments; a video with no notes on Frame.io is not sent and its row
  says so.
- **A press while the batch's request is still open adds to it**: the videos already in it keep their press time
  (`ad_pressed` holds the press time of each added video). A video added while a job or a session is already working
  (`late`) is not given to that running job. When that round is marked done (`reviews --revised`, or the watcher sees
  every new version up) the late videos become the next round: state `waiting` again with their own press time and a
  fresh count of tries, and the watcher starts a Claude job on them on its next pass. A job that is started again
  (the watcher after a stop, or **Start Claude on it**) lists every video of the request.
- Each video he sent shows **Revisions sent** under In progress until its new version is pushed to Frame.io. A video
  he did not send stays where it was, and an approved video always stays **Approved** (dimmed, not counted).
- `ctl.py status` prints "REVISIONS DONE" and `ctl.py reviews` lists the notes per ad with the next steps. A session
  starts without asking: `ctl.py reviews --working "<batch>"`, apply the notes to the videos the request lists (never an approved video), preflight, push,
  then `ctl.py reviews --revised "<batch>"`.
- The press starts a headless Claude on this Mac by itself (next section). No Claude session has to be open.
- A session that wants to do a batch by hand instead: `ctl.py reviews` says when an unattended job already has it
  (leave it alone); `ctl.py reviews --working` refuses while that job runs. `claude_job.py stop "<batch>"` first.

## Unattended Claude jobs

`cloud/claude_job.py` runs `claude -p` on the owner's Claude login (his plan; the paid API key is removed from the job's
environment) with no session open. Permission mode `auto`, his own Claude Code settings, hooks and deny list apply.

What starts one:

1. **"Revisions done"** (batch button or a video's own link): after the helper has pulled the Frame.io notes (state
   `waiting`, at least one open note) it starts the revision job of that batch on the videos in the request's `ads`
   only; it never touches an approved video. The job does `reviews --working`, reads the notes, fills the `revise-plan`
   batch file, submits, waits, collects, fixes every FAIL, answers PREFLIGHT, pushes each new version to Frame.io and
   ends with `reviews --revised`.
2. **The watcher**, every pass (`claude_job.sweep`): a pressed batch with no job yet (the helper could not start one),
   a pressed batch whose job stopped and nothing has moved for `claude_stall_min` minutes, and a finished ad that shows
   "Claude to fix" or "Final checks" with nothing moving for that long (only ads made after `claude_auto_from`, an epoch you set in config.json to switch this on; unset = never).
3. **By hand**: the **Start Claude on it** button on a stalled batch header, or `claude_job.py start "<batch>"`.

Rules the code keeps:

- One job per batch: the runner holds `controller/claude-jobs/<batch>.lock` for as long as it lives. A second start
  answers "running".
- At most `claude_max_jobs` (2) at once, at most `claude_job_tries` (3) automatic starts per press, each stopped after
  `claude_job_timeout_s` (3 h, the whole process tree).
- A batch pressed before the feature was on has no `auto` mark and is never taken over by the watcher; it gets the
  button. A batch another Claude session is working on (project files, cloud runs or that session's tool calls on
  `projects/<ad>` in the last 30 minutes) is left alone.
- A finished ad stuck at a check is only picked up when its whole batch is free: no open "Revisions done" request
  under that batch name (even if this hook is not in the request's list), no open cloud run of the batch, and no
  activity on ANY ad of the batch for 30 minutes. Its job has its own key, `fix: <batch>` (record
  `controller/claude-jobs/fix@<batch>.json`), so it never shows on the batch header as the revision job.
- A job spends no kie credits unless `"claude_job_paid": true` is in config.json. Without it the job does every free
  fix and reports each note that needs a paid redo, with the command, on the board ("Needs you").
- A job that cannot finish runs `claude_job.py blocked "<batch>" "<why>"`; the board shows that sentence under "Needs
  you" and nothing restarts it until he presses **Start Claude on it**.
- The Mac is kept awake while a job runs (`caffeinate -i -s`, idle sleep only: a closed lid on battery still sleeps).

Commands (`.modal-env/bin/python cloud/claude_job.py ...`, or `ctl.py jobs`):

    status                       every job: running / done / failed / timeout / blocked, with its log
    start "<batch>"              start the revision job of a batch by hand
    stop "<batch>"               stop a running job
    sweep --dry                  what the watcher would start now, without starting it
    smoke                        a 15-second test job (runs `ctl.py jobs`): proves the unattended start works

Record `controller/claude-jobs/<batch>.json`, log `cloud/.scratch/claude-jobs/<batch>-<time>.log` (stream-json, every
tool call), runner log `cloud/.scratch/claude-jobs/runner.log`. Off: `"claude_auto": false` in config.json (the board
still says Stalled truthfully). Model and effort are the owner's Claude Code defaults unless `claude_job_model` /
`claude_job_effort` are set.

## Final approval -> Google Drive -> media buyer sheet

Approving what is on Frame.io uploads it to Google Drive and gives the owner the link, plus a tick for "it is in the
media buyer sheet".

- **Approve** (board, Ready for review) posts to the helper (`/approve`), which writes `projects/<ad>/APPROVED.json`
  (+ `.log.jsonl`): the Frame.io file id he approved and the note ids on it at that moment. A newer upload voids it.
  **Take back** works until the upload starts. **Approve all N** sends exactly the rows he sees under that batch.
- Approval is per batch (all hooks): when every ad of the Frame.io batch is approved, the helper starts
  `cloud/deliver.py "<batch>"` as its own process (an ad pushed alone is a batch of one under its own name). It:
  pulls the last Frame.io comments and stops if a note arrived after Approve; stops if `MASTER.mp4` was re-rendered after
  the approved upload; makes a Drive folder named after the batch in the Google Drive linked to Composio (`composio_drive_account` in
  config.json picks an account; empty = the default one), uploads each MASTER as
  `<ad>.mp4`, checks every md5 against the Mac file, shares the folder "anyone with the link can view"; then runs
  `tools/frameio.py clean` (pulls comments, deletes the batch) and logs the link (shown on the board).
- Records: `cloud/controller/deliveries.json`, one entry per batch (state queued / uploading / delivered / failed, url,
  files with md5, in_sheet, renamed). Log: `cloud/.scratch/deliver.log`. While it runs the rows show **Uploading to
  Drive** under In progress; a stop shows **Drive upload stopped** with the reason and **Try again** (or **Approve
  again** on the ad that got a late note, once he has read it).
- **In the media buyer sheet** (`/sheet`) only records his tick. Naming stays his: once he ticks, a session
  renames the Drive folder and files to his Ad Name from the naming sheet (read only) and runs
  `deliver.py --renamed "<batch>"`. `ctl.py reviews` lists ticked batches still to rename, stopped uploads and failed cleans.
- Not automatic: pasting the Drive link into the sheet (`deliver_sheet_link`, not built).

## Clip and hook picks (never Frame.io)

Options for one slot (a product clip, a hook visual, a b-roll pick) go in a local picker page, not on
Frame.io, and nothing is drawn on the picture to tell them apart. `tools/option_picker.py <project> --slot "<slot>"
<clip> <clip> ... --why "<line spoken over the slot>"` writes `OPTIONS.json` + `OPTIONS.html`; the board lists it under
**To approve** ("Pick clips"). "Send to Claude" posts to the same helper (`/options`), which writes `OPTIONS_PICK.json`
(+ `.log.jsonl`) and logs each pick to `feedback/log.jsonl` (taste rule T29). `ctl.py reviews` lists unused picks;
`ctl.py reviews --done <ad>` marks one used. New option files make a new set: old picks stop counting.
`tools/frameio.py push` refuses an option project (name with opt/option/pick, or one holding `OPTIONS.json`) and any
file shorter than 10 s.

## The shot check (before any real-footage render)

`tools/shot_check.py <project>` grabs 3 frames of every planned shot from the SOURCE clip, pairs them with the words
spoken over that shot, and has Claude judge each against the taste rules (line match, product before the reveal, a tool
that must fail, burned-in text, warped footage, anything in `brand.json` `never_show`). It writes `SHOT_CHECK.md`.

- A blocking issue stops the run before the render. Fix the shot, or accept a known limit in `plan.json`:
  `"shot_check_ack": {"<file stem>@<in-point>": "why this is acceptable"}`. Then submit again.
- The prompt carries the owner's current taste rules for the shot stage (`tools/taste_rules.py`, from
  `feedback/taste_rules.json`), so a rule learned from a note today is checked on the next run.
- Verdicts are remembered per shot: a re-run only asks about shots whose clip, in-point, words, note or rules
  changed (`--force` asks all again). Opus at effort medium.
- Set `"reveal_shot": <index>` in the plan when no shot note names the product.
- A fault of the footage itself (burned-in graphic, warped, too blurry) is logged to `footage/moments/flags.jsonl` on
  collect. `moments.py search` then ranks that clip window lower and prints `FLAGGED: ...` beside it.

## The shared clip store

Footage, music and transcripts live once on the Volume under `/adjobs/_store/<path inside the repo>`. Each project
carries an `assets.json` listing the files it needs; `submit` uploads only files the store does not have yet. The
pipeline code travels the same way, to `/adjobs/_code/<version>/`, so a tool change needs no redeploy.

## Paid work is crash-safe

- Voice, stills and clips are separate steps; the project is saved after each one.
- While a paid step runs, the worker checkpoints every kie task id, every finished file and the run's task counter to
  the Volume within seconds. A worker that dies loses nothing that was paid for.
- After a failure, `collect` then `submit ai-resume <ad> --go` (or `ai-frames` / `ai-clips`) continues: saved task ids
  are polled, only what is still missing is generated. `collect` prints the exact command.
- A provider task that fails is not charged. The worker makes one second pass for the missing beats on its own; if
  some are still missing the run fails and names them (`not delivered: 3:clip`).
- The paid worker is never started twice for the same step automatically.

## Money and safety

- Modal: every call is admitted against `cloud/controller/ledger-<month>.json` before it starts, at its worst case
  (a reserve per real-footage or AI ad while it is in flight, released when it finishes). A finished run's reservation is released the next time `status`, `collect` or the
  watcher looks at it. Cap and stop line are in `cloud/controller/config.json` (`modal_cap_usd`, `modal_stop_usd`).
  These are ESTIMATES from Modal's listed rates; Modal's Usage page is the bill. When a submit would pass the limit,
  the ads that fit are started, the rest are named and not started.
- kie: each ad's run may use at most `kie_cap_per_ad` credits (config.json, 1500). `--kie-cap N` overrides it for one
  submit. The client works out the worst case from measured prices (still 25, Kling std clip 24 per second, at least
  120), counting only stills and clips that do not exist yet, and refuses when it is above the cap. The cloud worker
  has a hard count of paid tasks for the whole run (planned tasks plus a little room for the second pass). Other clip
  modes have no measured price: pass `--clip-bound N` from a measured pilot, never a guess.
- GLOBAL STOP (`cloud/controller/GLOBAL_STOP.json`) is raised when a paid worker crashes without a result, when the
  month's Modal estimate reaches the stop line, or when a call cost more than it was admitted for. Tell the owner. To
  lift it: move that file into `cloud/controller/stops/` with a note, and set `"global_stop": false` in the ledger.
  A paid step that ends cleanly but incomplete fails only that ad.
- `submit` refuses: a LOCKED ad, an ad with an uncollected run or a submit of it in progress in another session, a
  real-footage plan that uses a banned clip window (`footage/BANNED_CLIPS.json`), a redo note that names a beat the
  plan does not have, a cloud copy that is ahead of the Mac (so nothing paid
  is made twice), a second voice run, clips before every beat has a still, a revision before every beat has a clip,
  and a Mac with under 3 GB free (`mac_min_free_gb`; collect downloads ~150 MB per ad).
- Several Claude sessions and the watcher can use the controller at the same time: the run registry and `collect` are
  locked, and each ad can only have one open run.
- If `plan.json` was edited on the Mac while the cloud was working, `collect` keeps the Mac version and saves the
  cloud's as `plan.cloud.json`.
- Nothing in the controller approves an ad or uploads to Drive. It pushes to Frame.io only ads whose preflight is fully answered (auto_push).

## The watcher

`ctl.py watch --once` collects whatever has finished and runs the Mac checks. Slack notes go through `bin/slack-post`
(Composio) as a DM to `slack_user_id` in config.json; leave it empty and Slack is off. With no open runs it
does nothing and makes no network call. While runs are open, one `--once` pass keeps looking every 45 seconds
(`watch_fast_s`) for up to 9 minutes (`watch_linger_s`), then the next launchd start takes over. A Slack note that
could not be posted is kept (`controller/slack-unsent.jsonl`) and sent on the next pass; a GLOBAL STOP is posted once.
Each pass rewrites the ad board and starts the unattended Claude jobs that are due (`ctl.py jobs --sweep` does that
part alone). `ctl.py watch` (no flag) does the same in one long-running process.

To have it run by itself every 10 minutes and at login, the owner installs a launchd job once (Claude sessions are
not allowed to install background jobs). The exact steps (label `com.<app_prefix>.watch`) are in
`docs/SETUP_CLOUD.md`, "Optional: the watcher". Log: `cloud/.scratch/watch.log`. On a Mac where it is not installed,
a session runs `ctl.py collect` (or `watch --once`) itself.

## What still needs the Mac, and what needs a Claude session

- **A Claude session** (a person starts it): writing the script and plan, picking shots for a new ad.
- **No session, but the Mac awake**: deciding the fix for each owner note, answering PREFLIGHT, fixing a failed check,
  pushing to Frame.io (the unattended job); collecting finished runs and the Mac final checks (the watcher); the
  board and its buttons (the helper on 127.0.0.1). With the Mac asleep, cloud runs keep going and are collected when it
  wakes; a "Revisions done" press cannot happen at all, because the board is served from the Mac.
- **Mac only by nature**: the Apple Vision tilt check (T13), MLX caption timing (the authority for caption sync), the
  Frame.io login, the 35 GB footage library, `feedback/log.jsonl` and the taste rules.

## Final checks in the cloud (off by default)

With `"cloud_checks": true` in config.json a submit adds one unpaid step to `raw`, `ai`, `ai-resume`, `ai-clips`,
`ai-revise` and `ai-finish`: `rawverify` (real-footage ads) and `preflight` in the plain worker (no secret, no
network). `preflight` there is `tools/preflight.py <ad> --media-json`: the checks that need only the finished video
(format, repeated shots, hook cuts, freezes, tail, length, caption blocks, av_check, caption sync). The result comes
back in the run's last step (`checks`) and in `projects/<ad>/.cloud/media-checks.json`, tied to the file's fingerprint.

- The checks are advisory: a FAIL, a crash or a refused step never fails the run. `collect` prints
  "cloud final checks: PASS / FAIL / NOT RUN".
- The Mac still runs its full checks on collect and writes one line per run to `controller/check-parity.jsonl`
  (`agree`, `cloud_only`, `mac_only`). `cloud_only` not empty = the cloud raised a FAIL the Mac did not.
- `"trust_cloud_checks": true` (only after the parity file shows agreement): on a cloud PASS the Mac skips `rawedit
  verify` and runs `preflight.py --media-from`, which does only its own part (tilt, banned clips, sale line, flash
  clips, reuse) and refuses results that are not for this exact file.

The run is "done" only after the check step, so it reaches the Mac that much later (on a 90 s ad the check step takes
about as long as the render).

To use it:

1. One submit: add `--checks` (`ctl.py submit raw <ad> --go --checks`). Collect prints the cloud result and writes
   the parity line.
2. Every submit: set `"cloud_checks": true` in config.json.
3. Leave `trust_cloud_checks` off until several real ads agree in `controller/check-parity.jsonl`.

## Render time (real-footage ads)

Every cloud render writes `projects/<ad>/.cloud/render-timing.json`: wall time, time inside ffmpeg, time inside Whisper
and the slowest steps. On the cloud's 4 CPUs a 93 s ad takes 11-14 minutes the first time; about 60% of that is
caption timing (one Whisper call per voice beat). The result of each call is saved in `SEGMENTS/_whisper/` on the
Volume (never sent to the Mac), keyed by the beat's audio, the settings and the model. A re-render reuses it for every
beat whose voice audio is unchanged, which brings a clip-swap or caption revision down to about 5 minutes. A changed
voice line, changed Whisper settings or a new model is transcribed again. To wait for runs use `ctl.py wait`.

## Files

`cloud/ctl.py` Mac client · `cloud/controller/app.py` deployed app · `cloud/worker/pipeline.py` recipes + orchestrator ·
`cloud/worker/ad_job.py` worker · `cloud/dash.py` ad board · `cloud/frame_review.py` board helper · `cloud/claude_job.py`
unattended Claude jobs · `tools/shot_check.py` · `cloud/tests/` · state in `cloud/controller/`
(`config.json`, `runs.json`, `ledger-<month>.json`, `kie-<month>.jsonl`, `revise-*.json`). `ctl.py history` lists
collected runs. After changing `controller/app.py`, `SHAPE` in `ctl.py` or `STAGE_TIMEOUT` in `pipeline.py`, run
`ctl.py deploy` (the three must agree).

## The usage page

The small **Usage** button at the top right of the ad board (it shows the kie balance) opens `cloud/.scratch/dashboard/usage.html`,
built by `cloud/usage.py`. `ctl.py usage` rebuilds and opens it; the board rebuilds it on every write, and the page itself asks the
board helper (`POST /usage`) for a live kie balance when it opens and rebuilds itself when its numbers are older than two minutes.

What it shows. The rule: **exact or not shown**. A number that is not on record shows a dash; nothing is
estimated or filled in.

- **kie balance**, read live from kie (`GET /chat/credit`), worth in dollars, and how many days it lasts at the last 7 days' spend.
  Every reading is kept in `controller/usage/balance.jsonl`. It turns amber under 3 days of spend, or under `kie_low_credits` if
  that is set in `config.json`.
- **Dollars** = credits x the owner's real price: `kie_pack_usd` / `kie_pack_credits` in `config.json` (example: $500 buys 105,000 credits).
  Change those two numbers if the pack price changes.
- **Batches**: per batch and per video, first pass / revisions / total (dollars and credits), rounds, make time.
  *First pass* = everything spent on a video up to its first Frame.io push; *revisions* = everything after. *Rounds* = Frame.io
  versions after v1. A video that never went to Frame.io has **no split**: its spend is in the total only and its rounds show a
  dash. Shared work (a hub folder) is first pass until the batch's first video reached Frame.io, revisions once every video in
  the batch has, and no split in between.
- **A finished video** needs proof on disk (`videos_in`): `MASTER.mp4`, or `DELIVERY.md` next to an `EDIT_KIT` (archived ads had
  their master moved out), a Frame.io push, a Drive delivery, or finished hook cuts kept in one folder (`MASTER-h1.mp4`,
  `<ad>-h2.mp4`: each counts). Everything else (tests, clip options, hubs, statics, older work whose finished file is
  not in its folder) sits in a closed "Other work, no finished video on record" group and stays out of the per-video averages.
- **Format** comes from the ad's own plan (the skill that made it, else the plan's fields, else a folder name that states it),
  never from which kie models it used.
- **By format**, **Timeline** (spend per day), **Claude and cloud**.
- **Make time** = kie tasks running + cloud runs (Modal ledger `wall_seconds`) + Claude working on the ad, overlaps counted once.
  Waiting for the owner is never counted. The kie and cloud parts are exact times; the Claude part is read from the saved sessions
  by rule (a session counts toward an ad while its tool calls work in that ad's folder), so it is a close measurement, not a
  stopwatch. It shows a dash for work that began before the first saved Claude session.

Where the numbers come from: every task id in `projects/<ad>/**/*jobs*.jsonl` (any depth) and `product-kit/`, deduplicated and kept
in `controller/usage/kie-tasks.json`, so an archived project keeps its history (`ctl.py usage --archive` re-reads the archive folder,
`ADMACHINE_ARCHIVE`, default `~/Library/Mobile Documents/com~apple~CloudDocs/Archive/ad-projects`). **Each task is then checked against kie's own record** (`GET /jobs/recordInfo`, free; answers kept in
`controller/usage/kie-verified.json`): kie's credits and kie's start and finish times replace the log's, which also dates older tasks that were logged
without times. A task the log never saw finish counts only once kie has said what it cost. Each rebuild checks the new
tasks by itself; `ctl.py usage --verify` checks everything. The page footer says how many are checked.
Also read: `frameio.json` (pushes, versions, clean), `deliveries.json`, `feedback/log.jsonl` (note counts), the Modal ledgers, and
the Claude Code transcripts in `~/.claude/projects` (`controller/usage/claude-index.json`: tokens and working spans per ad; only new
transcript lines are read each time, `ctl.py usage --index` reads everything). After new ads are taken in from the archive the
index must be rebuilt (move `claude-index.json` away, then `--index`), or their Claude time stays empty.
Claude runs on the owner's plan, so tokens and time are shown, never dollars.
Not tracked: ElevenLabs credits, and kie use outside the video projects (for example static images): it lowers the balance
but is not under a batch.
