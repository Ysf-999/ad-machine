# Setup guide

Do these in order. Steps 1–5 get you making ads on your Mac (about an hour). Steps 6–7 are optional extras you
can add later.

You need a Mac with Apple Silicon (M1 or newer) and about 30 GB of free disk space.

---

## Step 1. Make your accounts

You pay for these yourself. Each one has its own key or login.

| Account | What it's for | Needed? |
|---|---|---|
| **Claude Code** (Pro or Max plan) at claude.com/claude-code | The brain: writes scripts, runs every tool, checks frames. Uses your plan, so no API bill. | Yes |
| **kie.ai** | Makes the images, video clips and songs (Seedance, Kling, Veo, GPT Image, Suno). Pay per credit. | Yes |
| **ElevenLabs** | Voiceovers and voice design | Yes |
| **GitHub** | To get this code and receive updates | Yes |
| **Modal** at modal.com | Runs many ads at once in the cloud, plus the ad board's cloud side | Optional (Step 6) |
| **Composio** at composio.dev | Connects Frame.io, Google Drive and Slack without writing code | Optional (Step 7) |
| Frame.io, Google Drive, Slack | Review links, final delivery, alerts on your phone | Optional (Step 7) |

Top up kie.ai with a small amount first (for example $20) until you've seen what one ad costs you.

## Step 2. Download and install

Open the **Terminal** app and paste these lines one at a time:

```sh
# 1. Homebrew (skip if you already have it)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Get the code (accept the GitHub invite email first)
git clone https://github.com/Ysf-999/ad-machine.git ~/ad-machine
cd ~/ad-machine

# 3. Install everything
./install.sh
```

`install.sh` sets up Python, the cloud tools and the motion-graphics tool. It creates your three settings files
(next step) and links the skills into Claude Code. If it says Claude Code is missing, install Claude Code, run
`claude` once to log in, then run `./install.sh` again.

## Step 3. Add your keys

Open the `.env` file in the `ad-machine` folder (in Finder press **Cmd+Shift+.** to show hidden files, or run
`open -e .env` in Terminal). Paste your keys after the `=`:

```
KIE_API_KEY=your kie key        (kie.ai > API Keys)
ELEVENLABS_API_KEY=your key     (elevenlabs.io > Developers > API Keys)
ANTHROPIC_API_KEY=              (leave empty: Claude runs on your Claude Code login)
```

`.env` never goes to GitHub. Don't share it or paste it into a chat.

## Step 4. Describe your brand

Open `brand/brand.json` and fill in every line in plain words: your brand, website, product, what it looks like
on camera, how it works in a demo, what a full demo shot shows, the problem it solves, who buys it, anything it
must never be shown doing, and your offer line.

Then put 3–6 clear photos of your real product in `brand/product-photos/` (front, back, in use). Before paying
for video, the checkers compare every generated frame against these photos and your description. This matters
more than anything else for getting the product right.

## Step 5. Make your first ad

In Terminal:

```sh
cd ~/ad-machine
claude
```

Then just tell Claude what you want, for example:

> Make a 30-second drama ad for my product. Start with a sanity pilot.

or

> Make a claymation animated ad about [the problem]. Show me the starting frames before making video.

Claude picks the right skill, writes the script, and shows you the starting frames for approval. It then makes
the clips and puts the ad together, then runs the final checks (`preflight`). You review it in the `REVIEW.html`
page it opens; press **Copy notes** and paste your notes back into the chat. Every note you give is saved and
turned into a taste rule, so the system makes the same mistake less over time (`feedback/OWNER_TASTE.md`).

Other things you can ask for: song ads, UGC talking-head ads, whiteboard or chalkboard explainers, editing your
own creator footage into an ad ("edit this video into an ad: <path>"), new hooks on an ad that works, or a
sound-off cut for Stories.

**Real footage:** put your creator clips in `footage/raw/` and list them in `footage/INDEX.csv` (ask Claude to make
the index for you). Then run `tools/moments.py build` once so the editor can search them for b-roll.

**Music:** add tracks you're allowed to use to `library/music/<mood>/` (happy, sad, calm, intense, funny…). Ask
Claude to run `tools/music_lib.py` to index them.

## Step 6 (optional). Cloud and the ad board

The cloud lets you start a whole batch of ads at once and close your laptop. The **ad board** is a dashboard
with tabs for In progress, Frames to approve and Ready for review, plus Approve buttons and a Usage page with your
kie spend per ad.

Follow `cloud/docs/SETUP_CLOUD.md`. It takes about 20 minutes: log in to Modal, add your keys as Modal secrets, upload the
Whisper model, deploy. Spending is capped at $10/month by default (`cloud/controller/config.json`).

Then open the board:

```sh
.modal-env/bin/python cloud/ctl.py dash
```

and ask Claude things like "submit these 3 ads to the cloud as a batch".

## Step 7 (optional). Frame.io, Google Drive, Slack

1. Install the Composio CLI (see composio.dev docs) and run `composio login`.
2. Link what you want: `composio link frame_io_v4`, `composio link googledrive`, `composio link slack`.
3. Frame.io: run `.venv/bin/python tools/frameio.py setup --name "<Your Brand> Ads"` once. Finished ads then go to
   Frame.io for review, and your comments there come back as notes (`frameio.py pull --all`).
4. Slack alerts: put your Slack member ID (Slack > your profile > ⋯ > Copy member ID) in
   `cloud/controller/config.json` as `"slack_user_id"`.

---

## Making it yours

- Taste rules: `feedback/OWNER_TASTE.md`. They start with general craft rules and grow from your notes. Ask Claude
  to "add a taste rule: ..." any time.
- Cloud limits: `cloud/controller/config.json` (`kie_cap_per_ad`, `modal_cap_usd`).
- Change anything else by asking Claude in this folder. It reads `AGENTS.md` for how the system works.

## Getting updates

If the original repo gets improvements: `git pull`. Your settings, keys, footage and projects are ignored by git,
so a pull never overwrites them.

## If something breaks

- "KIE_API_KEY missing": check `.env` (Step 3).
- "Could not resolve host": you're offline, or a VPN or firewall is blocking it.
- A step is slow: frames and clips take minutes. Claude runs them in the background and checks back.
- Anything else: paste the error to Claude in this folder and ask it to fix it.
