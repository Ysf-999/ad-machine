# Setting up the cloud side (Modal)

These steps put the cloud controller on **your own** Modal account. Do them once, in order, from the repo root
(the folder that holds `tools/`, `cloud/`, `brand/`). Commands are for macOS + zsh. Plan about 20-30 minutes, most of
it waiting for the Whisper model to download and upload.

Everything Modal-side is named `<prefix>-<role>`. The prefix is `"app_prefix"` in `cloud/controller/config.json`
(default `admachine`). The examples below use `admachine`; if you pick another prefix, use it everywhere instead.

| Modal object | Name | What it is |
|---|---|---|
| App | `admachine-ads` | the deployed controller (`cloud/controller/app.py`) |
| Volume | `admachine-adjobs` | projects, code snapshots, shared clip store (created by itself) |
| Dict | `admachine-ads-status` | live state of every run (created by itself) |
| Volume | `admachine-whisper-ct2` | the Whisper model for captions (you create it, step 6) |
| Secret | `admachine-generation` | `KIE_API_KEY`, `ELEVENLABS_API_KEY` |
| Secret | `admachine-claude` | `CLAUDE_CODE_OAUTH_TOKEN` |

## 1. Install Modal into its own environment

`./install.sh` already does this. By hand:

```sh
uv venv --python 3.12 .modal-env
uv pip install --python .modal-env/bin/python -r requirements-modal.txt
```

Every cloud command below runs with `.modal-env/bin/python` (or `.modal-env/bin/modal`). Code that needs to start
this Python again uses the `MODAL_PYTHON` environment variable when set, else the Python it is running under.

## 2. Log in to Modal

Make an account at modal.com, then:

```sh
.modal-env/bin/modal token new
```

A browser window opens; approve it. The token is saved in `~/.modal.toml`.

## 3. Your settings file

```sh
cp cloud/controller/config.example.json cloud/controller/config.json    # install.sh does this too
```

Open it and check these (without a `config.json` the example's values are used):

- `app_prefix`: `admachine`, or your own short lowercase name (letters, digits, dashes).
- `modal_cap_usd` / `modal_stop_usd`: `"10.00"`. The monthly Modal spend the controller admits (estimated from
  Modal's list prices; Modal's Usage page is the real bill). Also set a spending limit in Modal's own settings.
- `kie_cap_per_ad`: `1500`. The most kie.ai credits one ad may use in one run.
- `kie_pack_usd` / `kie_pack_credits`: what you pay for a kie.ai top-up and how many credits it gives (usage page).
- `slack_user_id`: empty = Slack off. To get DMs, put your Slack member id (Slack profile, "Copy member ID") and link
  Slack in Composio (`composio link slack`); notes go through `bin/slack-post`.
- `claude_auto` / `claude_job_paid`: `false`. Leave them off until the rest works (see `CONTROLLER.md`,
  "Unattended Claude jobs").
- Optional: `composio_drive_account` (which Composio Google Drive account `cloud/deliver.py` uploads to; empty = the
  default one).

## 4. The generation secret (kie.ai + ElevenLabs)

Put the two keys in a temporary file so they do not land in your shell history:

```sh
umask 077; cat > /tmp/gen.env <<'EOF'
KIE_API_KEY=paste-your-kie-key
ELEVENLABS_API_KEY=paste-your-elevenlabs-key
EOF
.modal-env/bin/modal secret create admachine-generation --from-dotenv /tmp/gen.env
rm /tmp/gen.env
```

Only the `run_gen` worker (voice, stills, clips, redos) gets this secret.

## 5. The Claude secret (your Claude Code login, not an API key)

The cloud runs plan review, shot check, QC and stitch with the `claude` CLI on your Claude subscription. Make a
long-lived token and store it:

```sh
claude setup-token        # prints a token that starts with sk-ant-oat...
umask 077; printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' 'paste-the-token' > /tmp/claude.env
.modal-env/bin/modal secret create admachine-claude --from-dotenv /tmp/claude.env
rm /tmp/claude.env
```

Only the `run_claude` worker gets it. No `ANTHROPIC_API_KEY` is used in the cloud.

## 6. The Whisper model volume

The workers time captions with `faster-whisper` on a CTranslate2 copy of `openai/whisper-large-v3-turbo`
(details: `WHISPER_MODEL.md`). Convert it once on your Mac in a throwaway environment (needs about 5 GB free while
it runs), then upload it:

```sh
uv venv --python 3.12 /tmp/ct2-env
uv pip install --python /tmp/ct2-env/bin/python ctranslate2==4.6.0 transformers==4.48.3 torch==2.6.0 "huggingface-hub[cli]==0.36.2"
/tmp/ct2-env/bin/huggingface-cli download openai/whisper-large-v3-turbo \
    --revision 41f01f3fe87f28c78e2fbf8b568835947dd65ed9 --local-dir /tmp/whisper-src
/tmp/ct2-env/bin/ct2-transformers-converter --model /tmp/whisper-src --output_dir /tmp/whisper-ct2 \
    --copy_files tokenizer.json preprocessor_config.json --quantization float16
ls /tmp/whisper-ct2    # README.md config.json generation_config.json model.bin preprocessor_config.json tokenizer.json vocabulary.json
```

The worker checks each file's sha256 against `MODEL_SHA` in `cloud/worker/ad_job.py` and refuses a mismatch. Print
yours and compare:

```sh
python3 -c "import hashlib,pathlib;[print(repr(p.name)+':',repr(hashlib.sha256(p.read_bytes()).hexdigest())+',') for p in sorted(pathlib.Path('/tmp/whisper-ct2').iterdir())]"
```

If any line differs from `MODEL_SHA`, replace the dict's values with yours (same seven names). Then upload the files
to the root of a new volume:

```sh
.modal-env/bin/modal volume create admachine-whisper-ct2
.modal-env/bin/modal volume put admachine-whisper-ct2 /tmp/whisper-ct2/ /
.modal-env/bin/modal volume ls admachine-whisper-ct2     # the seven files, model.bin about 1.6 GB
rm -rf /tmp/ct2-env /tmp/whisper-src /tmp/whisper-ct2
```

## 7. Deploy the controller

```sh
.modal-env/bin/python cloud/ctl.py deploy
```

(The same as `cd cloud && ../.modal-env/bin/modal deploy controller/app.py`.) The first deploy builds the worker image
(Debian, Python 3.12, faster-whisper stack, static ffmpeg 7.0.2, `claude-agent-sdk` with the `claude` CLI) and takes a
few minutes. It fails at once if a secret or the model volume from steps 4-6 is missing or named differently.
Deploy again only when `cloud/controller/app.py` changes; tool and pipeline code travels with every submit.

## 8. First test

```sh
.modal-env/bin/python cloud/ctl.py status      # "no open runs": the client talks to your app
.modal-env/bin/python cloud/ctl.py dash        # opens the ad board in your browser
```

Then a free end-to-end run on a finished real-footage or AI project (`projects/<ad>/plan.json`): `check` is the
offline readiness recipe and spends no kie credits.

```sh
.modal-env/bin/python cloud/ctl.py submit check <ad> --go
.modal-env/bin/python cloud/ctl.py wait
.modal-env/bin/python cloud/ctl.py collect
```

The guide to every command, recipe and safety rule is `CONTROLLER.md`.

## Optional: the watcher (collects finished runs by itself)

A launchd job runs `ctl.py watch --once` every 10 minutes and at login. Install it yourself (Claude sessions do not
install background jobs). From the repo root:

```sh
PREFIX=admachine            # your app_prefix
REPO="$PWD"
mkdir -p cloud/.scratch
cat > ~/Library/LaunchAgents/com.$PREFIX.watch.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.$PREFIX.watch</string>
  <key>ProgramArguments</key><array>
    <string>/bin/zsh</string><string>-c</string>
    <string>cd "$REPO" &amp;&amp; "$REPO/.modal-env/bin/python" cloud/ctl.py watch --once</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StartInterval</key><integer>600</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$REPO/cloud/.scratch/watch.log</string>
  <key>StandardErrorPath</key><string>$REPO/cloud/.scratch/watch.log</string>
</dict></plist>
EOF
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.$PREFIX.watch.plist
launchctl print gui/$(id -u)/com.$PREFIX.watch | head -20      # check it is loaded
```

Log: `cloud/.scratch/watch.log`. Turn it off: `launchctl bootout gui/$(id -u)/com.$PREFIX.watch`. The PATH line must
reach `claude`, `composio` and `ffmpeg`.

## If something fails

- `NotFoundError` for a secret or volume: the name does not match `<prefix>-...` (step 3 prefix vs steps 4-6).
- `GLOBAL_HASH_MISMATCH model ...` in a run log: your converted model differs from `MODEL_SHA` (step 6).
- `GLOBAL STOP`: the monthly cap was reached or a paid worker crashed. `CONTROLLER.md`, "Money and safety", says how to
  lift it.
- The ffmpeg download in the image build fails: the pinned static build moved. Change the URL, size and sha256 in
  `cloud/controller/app.py` to another static ffmpeg 7.0 build you trust and deploy again.
