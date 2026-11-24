# cloud/: cloud controller and ad board

Runs ads in the cloud on Modal, in parallel, while the Mac sleeps, and shows everything that needs you on one local
page (the ad board). The tools in `tools/` run unchanged inside Modal workers; the Mac uploads the work, then downloads
the result and runs its own final checks.

Set up first: **`docs/SETUP_CLOUD.md`** (Modal login, secrets, Whisper model volume, deploy, first test).
Full guide to commands, recipes, the board and the money rules: **`docs/CONTROLLER.md`**.

## Main commands (from the repo root)

```sh
.modal-env/bin/python cloud/ctl.py submit <recipe> <ad,ad,...> --go [--batch "<name>"]   # start one cloud pipeline per ad
.modal-env/bin/python cloud/ctl.py status            # every open run, grouped by batch
.modal-env/bin/python cloud/ctl.py wait              # block until open runs finish
.modal-env/bin/python cloud/ctl.py collect           # download finished runs (sha256-checked) + Mac final checks
.modal-env/bin/python cloud/ctl.py dash              # the ad board (opens in the browser)
.modal-env/bin/python cloud/ctl.py usage             # the usage page: kie credits / dollars / time per batch
.modal-env/bin/python cloud/ctl.py notes             # pull Frame.io comments into the feedback log
.modal-env/bin/python cloud/ctl.py revise-plan       # open notes -> a batch file for `submit --from <file> --go`
.modal-env/bin/python cloud/ctl.py watch --once      # what the optional launchd watcher runs
.modal-env/bin/python cloud/ctl.py deploy            # (re)deploy controller/app.py
```

Recipes: `raw` (real footage: shot check, render), `ai`, `ai-frames` / `ai-frames-revise` / `ai-clips`, `ai-resume`,
`ai-revise`, `ai-finish`, `inserts`, `check` (free readiness check). `.modal-env/bin/python cloud/ctl.py` with no
command prints all of them.

## Settings

`controller/config.json` (copy `controller/config.example.json`; without it the example's values are used): Modal
monthly cap (`modal_cap_usd`, $10), kie credits per ad per run (`kie_cap_per_ad`), `app_prefix` for every Modal name,
`slack_user_id` (empty = Slack off), kie pack price for the usage page, unattended-Claude switches. Runtime state
(`runs.json`, `ledger-<month>.json`, `board-token`, `revision-requests.json`, `deliveries.json`, `usage/`,
`claude-jobs/`, `GLOBAL_STOP.json`) is created in `controller/` on first use and is git-ignored.

## What is in here

The live system:

| File | Role |
|---|---|
| `names.py` | settings loader + every Modal name (`<app_prefix>-ads`, `-adjobs`, `-ads-status`, `-generation`, `-claude`, `-whisper-ct2`) |
| `controller/app.py` | the deployed Modal app: worker image and the functions `run_plain`, `run_gen`, `run_claude`, `pipeline`, `admin` |
| `ctl.py` | Mac client: submit, status, collect, watch, notes, revise-plan, reviews, jobs, usage, deploy |
| `worker/pipeline.py` | recipes and the per-ad step runner (runs in the `pipeline` function) |
| `worker/ad_job.py`, `adjob_boot.py`, `adjob_check.py` | one worker step: copies the project in, runs `tools/ad.py` / `rawedit.py` stages, saves back to the Volume |
| `worker/overnight_budget.py` | the Modal spend ledger (cap, stop line, reservations) |
| `transcription.py`, `whisper-settings.json` | faster-whisper adapter and frozen settings used in the cloud |
| `dash.py` | the ad board page |
| `frame_review.py` | the board's local helper on 127.0.0.1:8790 (approve frames, revisions done, approve, picks) |
| `claude_job.py` | unattended headless Claude jobs on the Mac (revisions, fixes) |
| `deliver.py` | approved batch -> Google Drive (Composio) -> off Frame.io |
| `usage.py` | the usage page |
| `audit.py` | offline inventory of tools, venvs and `com.<app_prefix>.*` launchd jobs |

Earlier prototype layer, kept with its tests but not used by `ctl.py`: a durable SQLite job queue with leases and
gates (`orchestrator.py`, `reliability.py`, `workflow.py`, `simulation.py`, `mock_budget.py`), signed approvals and
revisions (`approval.py`, `revisions.py`), mock paid adapters (`providers/`), content-addressed storage and a
storage-backed worker protocol (`storage.py`, `worker/protocol.py`, `worker/controller.py`, `worker/entrypoint.py`),
an isolated offline stage runner (`runner/`, `worker/isolation.py`, `worker/fonts.py`, `hygiene.py`, `cli.py`),
a private review service (`review_auth.py`, `review_service.py`, `callback_service.py`, `volume_cli.py`), the Claude
backend shim (`llm.py`) and OCR experiments (`ocr/`). `Dockerfile` and `worker/modal_app.py` are unbuilt templates for
that prototype. Docs: `docs/WORKER_PROTOCOL.md`, `docs/PAID_ADAPTERS.md`, `docs/REVIEW_SECURITY.md`,
`docs/ISOLATION.md`, `docs/LLM_BACKENDS.md`; also `docs/FONTS.md`, `docs/WHISPER_MODEL.md`.

## Tests

```sh
cd cloud && PYTHONPATH=.:..:../tools ../.venv/bin/python -m unittest discover -s tests
```

A few tests need the repo's `.venv` (with `static_ffmpeg`) and a `.env` file to exist; nothing in the suite calls
Modal, kie, ElevenLabs or Claude.
