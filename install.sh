#!/bin/bash
# One-time setup on a Mac (Apple Silicon). Safe to run again: it skips what is already done.
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"
say() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }

say "Checking the basics"
command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
command -v uv >/dev/null || brew install uv
command -v node >/dev/null || brew install node
command -v claude >/dev/null || echo "  ! Claude Code not found. Install it: https://claude.com/claude-code  (then run 'claude' once to log in)"
command -v composio >/dev/null || echo "  ! Composio CLI not found (needed for Frame.io, Google Drive, Slack). See https://docs.composio.dev for the CLI install"

say "Python tools (.venv)"
[ -d .venv ] || uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt

say "Cloud tools (.modal-env)"
[ -d .modal-env ] || uv venv --python 3.12 .modal-env
uv pip install --python .modal-env/bin/python -r requirements-modal.txt

say "HyperFrames (motion graphics)"
(cd tools/hyperframes && npm install --silent)

say "Your settings files"
[ -f .env ] || { cp .env.example .env; echo "  created .env  -> paste your API keys into it"; }
[ -f brand/brand.json ] || { cp brand/brand.example.json brand/brand.json; echo "  created brand/brand.json  -> describe your brand and product"; }
[ -f cloud/controller/config.json ] || { cp cloud/controller/config.example.json cloud/controller/config.json; echo "  created cloud/controller/config.json  -> cloud limits and Slack"; }

say "Work folders"
mkdir -p projects footage/raw footage/transcripts library/music taste feedback
touch feedback/log.jsonl

say "Claude Code skills (linked into ~/.claude/skills)"
mkdir -p ~/.claude/skills
for d in skills/course/* skills/extra/*; do
  [ -f "$d/SKILL.md" ] || continue
  n="$(basename "$d")"
  if [ -e ~/.claude/skills/"$n" ] && [ ! -L ~/.claude/skills/"$n" ]; then echo "  skip $n (you already have a skill with that name)"; continue; fi
  ln -sfn "$ROOT/$d" ~/.claude/skills/"$n" && echo "  linked $n"
done

say "Done. Next: open SETUP.md and do steps 2-6."
