# The feedback loop (how the ad system learns)

Every owner correction should change the system once, not once per ad.

## Auto-learning + preflight (this section wins over the older text below)
- **Owner taste rules** `feedback/taste_rules.json` -> `feedback/OWNER_TASTE.md` (`feedback.py taste`). The starter set is
  brand-neutral craft rules; your own review notes add to it and refine it. Ranked by how many ads each came up on. Read first
  by every skill (`feedback.py rules` prints it first). They win over R/S/C/A rules.
- **Auto-learn on arrival:** `feedback.append` (used by `add`, `ingest`, `frameio.py pull`) tags each note (`tools/taste_tags.py`).
  REPEAT = known rule broken; NEW = learn now (`taste-add` / `taste-edit` / `dismiss`). No approval step. `/learn` = the skill for this.
- **Preflight gate:** `tools/preflight.py <project>` on the finished video + `PREFLIGHT.md` checklist; `frameio.py push` refuses without it.
  It catches tilted text bubbles, repeated shots, too many cuts in the hook, freezes, sound/picture mismatch and banned
  phrases from `brand/brand.json`.
- **Weekly:** `feedback.py top`, `tools/weekly_report.py` (schedule it weekly with cron or launchd if you like):
  repeat ranking, revisions per ad vs the 4 weeks before, kie credit spend (balance snapshots in `feedback/credits_log.jsonl`).
- Note statuses: learned (tagged to T-rules), promoted (R-rules), dismissed (one-offs), like (owner picks/praise), open (NEW,
  must be learned in-session).

## Per ad
1. **Before producing:** `ad.py <project> rules` (learned rules) and `tools/taste.py brief <skill>` (reference ads). Set `"skill"` in plan.json (animated ads infer it from `mode`).
2. **Review:** `ad.py <project> review` opens REVIEW.html. Per beat: approve / redo, a note, and a "general rule" tick. The Whole-ad panel plays MASTER.mp4: press "Add note at current time" for timestamped notes.
3. **Log:** "Copy notes for Claude", then `ad.py <project> notes`. It saves every note to `feedback/log.jsonl` and prints the redo commands.
4. **Fix** the ad (`redo`, `redo-failed`, `stitch`).
   Feedback given in chat is logged too, as it arrives: `feedback.py add <project> "<owner's words>" --src chat [--skill S]`.
5. **Generalise with `/learn`**: every open note (`feedback.py open`) becomes a T-rule (`taste-add`), a refinement (`taste-edit`) or a one-off (`dismiss`). Skill-specific R-rules: `feedback.py promote <id[,id..]> "<rule>" [--scope universal] [--code tools/x.py]`. A rule needs owner wording that's general, or the same correction in 2+ ads. Mechanical rules go into tool code as well as the rules file.
6. **Lock** launched ads: `ad.py <project> lock`. `redo`, `vo`, `frames`, `clips`, `stitch` then refuse to touch them (`--force` overrides). Hook variants of a locked ad start unlocked.

## Is it working?
- `feedback.py stats`: notes per ad against the number of rules at review time. The notes per ad should fall as rules grow.
- `board.py <skill> [--since DATE]`: every master of a style side by side, oldest first, with the rule-set version stamped at stitch time. Judge new ads against old ones. Nothing is re-rendered.

## Taste references
`taste.py add <skill> <video> "why it works" [--narration voice-note]` stores a reference ad with measured cuts, pace and transcript. `taste.py from-ad <project> "why"` saves one of our own winners. 3 to 5 per style is enough. A recorded voice note from the owner explaining a cut or hook is the best input.

## Frame.io review
The owner can review on Frame.io (phone or desktop) instead of copy-pasting from REVIEW.html. `tools/frameio.py`, via a Composio `frame_io_v4` connection (your own Adobe app, OAuth Web App).
- `frameio.py push <ad> [--file X.mp4] [--label L]` uploads a 720p review copy (~4 MB per 50 s; Free plan = 2 GB) into the ad's folder. Later pushes stack as versions, and comments already logged on older versions get ticked completed.
- `frameio.py pull <ad> | --all [--dry]` logs new comments into `feedback/log.jsonl` (`src=frameio`, timestamp in seconds, version noted), then prints redo hints. In Frame.io: a comment ending `#rule` is flagged for /learn; a comment starting `beat 3:` is tied to that beat.
- **One folder per batch:** push every hook with `--batch "<NN Short Name>"`, so the hooks share one folder, each in its own version stack. `frameio.py batch "<name>" <ad> <ad-h2> <ad-h3>` moves already-pushed ads into one. `clean` on any member deletes the whole batch folder.
- `frameio.py clean <ad>` runs once the ad is approved: it pulls the last comments, then deletes the ad's folder from Frame.io to keep the Free plan under 2 GB.
- `frameio.py status`, `frameio.py link <ad>`.

## Batch
- `redo-failed [--stage clips] [--go]`: dry run by default; skips library assets, `plan.approved_beats`, and verdicts older than the clip. Run `qc` first.
- Per-beat redo already works (`redo <beat> frame|clip`), and every job resumes from its saved task id.
