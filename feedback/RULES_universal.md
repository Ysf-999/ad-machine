# Learned rules — all ad styles

Rules learned from owner reviews of finished ads, plus course and agentchad seeds. Read these before starting an ad:
`ad.py <project> rules`. New rules arrive through `feedback.py promote`. Do not remove a rule without an owner note saying
it is wrong. Brand facts (product, offer, banned phrases) live in `brand/brand.json`, never in these rules.

- **R001** Captions land on the spoken word. Never time them from TTS timestamps; `ad.py vo` re-times from Whisper + voice onsets, and `stitch` must end with CAPTION SYNC PASS. A FAIL is not deliverable. Never hand-edit captions.ass; fix the map with `ad.py realign`.
- **R002** No sentence may start with a hard audio cut. Dialogue takes join with room-tone lead/tail and fades, no pause cutting (`vo_max_gap: null`). If an onset sounds clipped, raise `vo_take_lead`, do not re-render.
- **R003** Same-voice consecutive beats render as ONE take. Use `vo_break` only when two beats run together and starve the first clip's window. Re-render a take only when Whisper on the clean VO mishears a word, never for taste.
- **R004** Never run `ad.py vo` on a finished ad for a clip-only change: it re-renders takes and shifts every window.
- **R005** Captions are phrase-chunked (max 4 words), uppercase, and never duplicate the hook card.
- **R006** No dialogue beat plays above about 2.2x speed. If a line is shorter than the 3 s Kling minimum, merge it with the next line or let a reaction hold. Read stitch's CAPPED/FREEZE flags and fix them.
- **R007** Hooks are written with hook-lab (scored, 20/30 or better) and checked with script-checklist. Make the first-second visual swing big, but the hook shot must read instantly: one clear gag, not five things at once.
- **R008** A character speaking on camera is lip-synced: render the Kling clip, stitch once, then run kie `volcengine/video-to-video-lip-sync` (lite) on the window-retimed clip plus the clean VO slice, and save the result trimmed to exactly the window length. Narration over action needs no lip sync.
- **R009** Kling refuses brand and monster IP names ("copyright"). Describe characters generically. Failed tasks cost nothing.
- **R010** Owner judgement beats the checker. The vision checker over-flags some poses and Whisper hallucinates tails at 1 fps. Verify a flag at full resolution before paying to redo, and never re-roll an owner-approved clip.
- **R011** Strict review before delivery: producer QC, then `ad.py masterqc`, then at most two fix rounds. Quote the CAPTION SYNC PASS line and a Whisper-vs-script diff of the master in DELIVERY.md.
- **R012** Long stages (plan_review, frames, clips) need a Bash timeout of 600000 or a background run. Never Read images or videos into the session; QA is text from the tools. If an Anthropic-backed checker prints API_UNAVAILABLE, use the manual fallbacks in PRODUCTION.md.
- **R013** Shared tools in `tools/` are changed by the supervisor only. A producer who finds a tool wrong works around it inside the project folder and reports it in DELIVERY.md.
- **R014** Launched or approved ads are locked (`ad.py <project> lock`). Never alter a launched master; make a hook variant or a copy.
- **R016** Offer lines in scripts, cards and songs come only from `default_offer` in `brand/brand.json`. No discount codes unless that line has one, nothing from `never_show`, no phrase from `banned_phrases`.
- **R017** Budget: 5,000 kie credits or fewer per ad. State the total from jobs.jsonl in DELIVERY.md.

## Course seeds for AI-ad stitches (C-rules; owner can strike any)
From the editing course (knowledge/video-editing-course/EDITING_KB.md); same numbers as RULES_raw-ugc-editor.md, applied in `ad.py stitch`.
- **C003** The music drop lands on the start of the hold (`hold_beat`, default beat 2). Pick the bed by `music_mood` from library/music.
- **C005** Music is EQ'd (1500 Hz, Q 4, -15 dB) before it is lowered, so it never fights the voice. Instrumental only under VO.
- **C007** Cut the music completely under the one line that must land (`music_stops`), bring it back after.
- **C009** Hook text is on screen from frame one, 3-5 s, no animation (`hook_card` box or `hook_text` line).
- **C010** Captions stay inside Meta's safe zone (bottom at y 1220 or higher); EDIT_CHECKS.md flags anything outside.
- **C011** SFX only on a visible event (`sfx_cues`), one or two per ad.


## agentchad seeds (A-rules; owner can strike any)
Seeded from the free agentchad.io skills (Reality Drama Engine, Trendjack Animator), not from an owner review. Source copies: `knowledge/agentchad/`. The owner can strike any of them; an owner R-rule always wins over an A-rule.
- **A001** End every video-clip prompt with the clean-frame line, word for word: "IMPORTANT: the picture must be completely clean. NO subtitles, NO captions, NO burned-in text, NO letters or words anywhere in the frame, no logos, no watermark." (Add "except the real product label" when the product's logo must read.) Omni, Seedance and Veo all burn in garbled subtitles without it.
- **A002** No names as labels in image or video prompts. Give each person one fixed description ("the woman about 45 with a grey bob and a green cardigan") and use it word for word in every prompt. Names used as labels get printed into the picture. A name spoken inside a quoted line is fine.
- **A003** Never use a character sheet or a multi-pose page as a clip's start frame: the engine animates the page for the first 1-2 s. Build a real scene still from the sheet, then start the clip from that still.
- **A004** A clip whose last frame smears before a cut is trimmed 0.05-0.1 s at the end in the edit, not re-rolled.
- **A005** Generated streets, shops and rooms must never show the same background person twice. Turn the shot toward a wall or shop front, or clear the background.
- **A006** Clips with native sound: the room sound matches the place you see. Indoors = "quiet small room, clean close voice, no background noise, no hiss"; car = "car interior, engine off, soft cabin sound"; street = "light outdoor air and distant traffic, voice clear and close". Hiss or a space echo indoors gets rejected on first listen.
- **A007** Every master gets `tools/av_check.py --check MASTER.mp4` (sound vs picture, FAIL above 40 ms; digital-silence holes; black frames) next to caption_sync_check. Joiners keep sound uncompressed per piece and encode AAC once; per-piece AAC + concat copy drifts about 10-30 ms per join. [enforced: tools/assemble_ugc.py]
- **A008** Reels/Stories right-hand button column: below y 868 keep every caption, sticker, badge and picture-in-picture left of x 886 (on 1080x1920; the full clear area is x 71-1027, y 347-1426). Our side margin (6 %, 65 px) only covers the edge. Known: rawedit.py's PIP box (y 340-980, right edge x 975) crosses this column for its bottom ~110 px.
- **A009** The first ~0.4 s of a generated clip barely moves. Generate at least the shot length + 0.5 s and start the shot about 0.45 s into the clip (lip-sync shots start at 0 so mouth and audio line up).
- **A010** Story locks: the product is never on screen before its reveal, and the hook's place comes back for the payoff.

## Owner rules (continued)

