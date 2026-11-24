---
name: raw-ugc-editor
description: Edit REAL creator footage into a finished 9:16 ad for the brand in brand/brand.json — one raw creator take (a-roll) from the footage library (footage/INDEX.csv), pauses and retakes cut on silence, punch-ins on every jump cut, b-roll pulled from the footage INDEX by what the line says (split screen, flip, creator picture-in-picture), a native hook box from frame one, word-timed captions in the safe zone, music with its drop on the hold and EQ'd under the voice, cued SFX, a storyboard to approve before rendering, seam/caption/audio/cadence/safe-zone verification, FCPXML for Resolve or Premiere, and hook variants (message test or visual test) on an approved body. Built on an agency editing course (knowledge/video-editing-course/EDITING_KB.md). Use when the user asks to edit a creator video, cut a UGC take, make an ad from raw footage / creator clips / the footage folder, add b-roll to a talking video, tighten a talking head, export a timeline, or make new hooks on a real-footage ad. Not for AI-generated video (use ugc-talking-head, drama-ad-machine, animated-ad-machine).
---

# Raw UGC editor (real footage)

> **Owner taste + auto-learning (mandatory).** `feedback.py rules` prints `feedback/OWNER_TASTE.md` first:
> the owner taste rules (T-rules), most repeated first. They win over every other rule and grow from the owner's own notes.
> Every owner revision (chat, Frame.io, review page) is logged the moment it arrives (`feedback.py add` / `frameio.py pull`)
> and learned at once with the `learn` skill: no approval step. Before ANY delivery (Frame.io push, Drive, chat) run
> `.venv/bin/python tools/preflight.py <project>`, fix every FAIL and answer every box
> in PREFLIGHT.md (taste rules + every earlier revision on this ad and its sibling hooks). `frameio.py push` refuses otherwise.


Tool: `tools/rawedit.py`, run from the repo root with `PY=.venv/bin/python`. Everything lives in
`projects/<ad>/` and plugs into the normal loop: `ad.py <ad> rules | notes | lock`, `feedback.py promote`.
The agent never watches video. Whisper words + ffmpeg silences are the clock; stills and text are what you read.

## Before planning (always)
1. `$PY tools/feedback.py rules raw-ugc-editor` — obey every rule (S-rules = seeded numbers, C-rules = the
   editing course, R-rules = owner rulings; owner rulings win).
2. Read `knowledge/video-editing-course/EDITING_KB.md` (the editing playbook: hooks, pace, b-roll, music,
   captions, SFX, safe zones; three of its breakdowns edit Dog Friendly Co pet ads) and the measured pacing
   in `taste/_bench/*/BENCH.md` if you have benchmarked any ads. `$PY tools/taste.py brief raw-ugc-editor`.
3. Brand standing rules from `brand/brand.json`: `default_offer` for offer lines, `never_show`, `banned_phrases`; no discount codes
   unless the offer has one, no claims you cannot back.

## Workflow (two stop gates: the plan, then the master)
Edit in layers and finish each before the next (B02): a-roll → music → b-roll → motion → text → SFX.
```
$PY tools/rawedit.py new <ad> --aroll "<INDEX file-name substring or Drive id>"   # fetches the take (Drive, no auth needed)
$PY tools/rawedit.py <ad> transcribe && $PY tools/rawedit.py <ad> pack             # TAKES.md: phrases with word indices + gap sizes
```
`pack` also runs the mirror check (tools/mirror_check.py: Apple Vision OCR on 6 frames as shot vs flipped). Selfie takes
are often mirrored; a clear "mirrored" verdict sets `aroll.flip` and render/storyboard hflip the take. "unclear" = force it
with `rawedit.py <ad> mirror --on|--off`; "unknown" = no readable text, leave it. `verify` flags any a-roll or b-roll whose
text would read backwards on screen (including a b-roll `--flip` for continuity on a clip with text). Safe-zone top is y 285
(Feed's 4:5 crop of 9:16), not the 14% Reels band.
Read TAKES.md and write `keep` in plan.json: `[[w0,w1], ...]`, one range per beat, in play order. Keep the last complete
take of a line, drop false starts, "um" runs, asides to the camera operator, and any claim that breaks the standing rules.
Pick the opening the way hook-lab would (the strongest line first; reordering is allowed). Keep a short gap before a punch
word. Set in plan.json: `hook_card` (the hook text: number/result + who it's for, readable in half a second, never the caption
text), `cta_beat` (number or "last"), optionally `music_stops` (the one line that must land), `sfx`, beat `zoom` 1.12 on the key
sentence. Then:
```
$PY tools/rawedit.py <ad> plan        # silence-anchored EDL + audit: short pieces, mid-sentence cuts, STATIC stretches > 3.5 s
$PY tools/rawedit.py <ad> broll       # per beat: intent (literal must-show + meaning) -> moment search -> rerank; up to 3 picks
$PY tools/rawedit.py <ad> set-broll <beat> m:<id> [--in s] [--off s] [--dur s] [--split m:<id2>] [--flip] [--pip]
$PY tools/rawedit.py <ad> storyboard  # STORYBOARD.html + PLAN.md  -> GATE 1: owner approves the plan
$PY tools/rawedit.py <ad> render [--music <file>|mood:<mood> --music-drop auto|<s>] [--no-captions]   # 5-10 min; background or long timeout
$PY tools/rawedit.py <ad> verify      # VERIFY.md: seams, caption sync, audio, edit checks, spoken-vs-planned -> fix, GATE 2
$PY tools/ad.py projects/<ad> soundoff ["HOOK"]   # muted Stories/Reels cut: hook box from frame one + caption coverage
                                     # -> MASTER-soundoff.mp4 + QC/soundoff_checks.md (no copy if MASTER already passes)
$PY tools/rawedit.py <ad> fcpxml      # only if someone will finish by hand in Resolve/Premiere (punch-ins are not exported)
```
**B-roll = moment cards.** `tools/moments.py` split every library clip into described moments (Haiku, from
frame sheets; this session never sees frames) and embedded them. A moment id `m:<fid10>@<start>` carries its in-point (for a
`demo-take`: `swipes_from`, the start of the demo action), its end (never across a hard cut) and T05 take data (show/flip
time, result time `strand_at`, result size `strand`, complete).
`broll` writes `beat.intent` and `beat.suggest`; `set-broll` with a moment id needs no `--in`. Check by hand:
`$PY tools/moments.py search "<what the viewer must see>" [--kind demo-take] [--product|--no-product] [--take] [--surface couch]`, `moments.py show <id>`.
Search skips banned clips, boosts the owner's T06 favourites and clips from our ads that Meta spent on (`tools/results.py`),
and penalises weak results, on-screen text, shaky and over-used clips. Cards flag a competitor's product (`product_brand: other`):
never use it as ours, and never blur logos unless the owner asks (T04).
`broll --keywords` = the old INDEX keyword match.
Fix every `WARN static` before the storyboard: b-roll on the line, a split, or let `auto_punch` add mid-line punch-ins.
A b-roll shot longer than ~3 s should be two clips (C006). Lead with the pain point, force-show the mechanism, solution after
the turning point, same creator for organic (C014). `--pip` only when the creator's face is on camera (C015).

**What render does automatically (C-rules, all numbers in `plan.rules`):** 100/110 % punch-in on every jump cut and mid-line
punch-ins on long pieces; b-roll slowed up to 12 % to fill its line; voice chain (high-pass, compressor, de-esser, loudness);
music EQ notch at 1500 Hz, 8 dB under the voice, drop landed on the hold, stops under `music_stops`, 1.5 s end fade; SFX from
`library/sfx/` (`tools/sfx.py list`: pop, whoosh, swipe, riser, ding, tick, buzzer, click, cash, impact, camera, record-scratch;
use `"lead": -1.2` so a riser ends on the word); the hook box from frame one (3-5 s); captions last, bottom at y 1220.

SFX: one or two per organic/UGC ad, each on a visible event (the product's result reveal, a graph pop) (C011).
Music: free local library, no credits. Set `"music_mood"` in plan.json (happy, sad, intense, calm, funny, inspiring, suspense,
holiday, heartfelt; match the buyer and the story, KB §8) and optionally `"music_kind"` (trendy | popular | library), or pass
`render --music mood:sad`. `tools/music_lib.py list --mood sad` shows the candidates and a one-line fit for each. Songs with
vocals play as their instrumental under the voice; hook variants reuse the base track. New tracks: `music_lib.py add "<link>"
--kind trendy` or drop files in `library/music/trendy|popular/` then `music_lib.py scan`. `tools/music.py` (kie) costs credits — ask.

Deliver: MASTER.mp4, CUT.mp4 (no captions/hook box), EDIT_KIT/ (edl.json, captions.ass/.srt, hook_card.png, fcpxml), VERIFY.md quoted.

## Voiceover mode (remake an ad / VO-led edit)
For an ad whose picture is all b-roll over a voice (e.g. remaking a finished ad with new footage):
1. Pull the voice: `.venv/bin/python -m demucs --two-stems vocals -n htdemucs <ad audio>` -> `vocals.wav` (no music).
2. `rawedit.py new <ad> --vo vocals.wav`, `transcribe`, `pack`, keep ranges per sentence (join tight gaps), `plan`, `words`
   (prints every word's output time to place shots on).
3. Footage: `tools/broll_web.py mixkit|tiktok|file <dir> <slot> ...` then `describe <dir>` (Haiku logs moments per clip; the
   agent never views frames). Product demo shots only from the owner's own footage library. Pexels/Pixabay block scraping: don't bypass, ask the
   owner for a free API key if needed. TikTok links come from web search, downloaded via SnapTik.
4. In plan.json: `shots` (a free picture timeline, several per sentence: at/src/in/speed/flip/zoom/push/anchor/fit),
   `cards` (review quote with stars, offer, guarantee: real reviews only, verbatim), `sfx` with `at`, `hook_card`,
   caption rules (`caption_font` "Montserrat ExtraBold", `caption_max_words` 3, `caption_hold` 0.2).
5. `render --music <file> --music-drop <s>`, `verify`. Measured caption fixes go in `word_fix` (never hand-edit captions.ass).
Fixed on the first remake: back-to-back VO beats butt at the word gap (no replayed tail), the voice is rebuilt sample-exact
(AAC segment joins drifted 21 ms per seam, 0.3 s by the end), URLs and hyphenated words stay one caption token.

## Variants (C012: message OR visual, never both)
- Message test: `rawedit.py <ad> variant <ad>-h2 --hook-card "new text"` then `plan` + `render` (identical cut).
- Visual test: `rawedit.py <ad> variant <ad>-h2 --keep "a-b"` (new opening take, same hook text) then plan/storyboard/render.
Lock the approved body first (`ad.py projects/<ad> lock`).

## After the owner reviews
STORYBOARD.html has approve/redo + notes per beat and timestamped notes on the master; "Copy notes for Claude" then
`$PY tools/ad.py projects/<ad> notes`. Feedback given in chat: log each correction as it arrives with
`feedback.py add <ad> "<owner's words>" --src chat --skill raw-ugc-editor`. At the end of the round run `/learn` (skill `learn`):
it proposes rules and code changes from every open note and applies only what the owner approves.
An owner note that contradicts a C-rule wins: promote it and say which C-rule it overrides.

## What this is not
No AI generation, no kie spend. If a line needs footage the library lacks, say so and list the nearest clips; do not
substitute another product's clip for ours. Keep the creator's real words; never dub. Not built yet (KB §13): text-only
organic mode, CTA end card, progress bar/timer, 2x2 social-proof collage.
