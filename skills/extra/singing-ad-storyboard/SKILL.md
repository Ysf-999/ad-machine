---
name: singing-ad-storyboard
description: Turn a singing-ad song script into finished-ad assets, step by step for a first-timer — reads the brief, locks the cast with character sheets, places the product, makes or imports the song, times every shot to the real audio, builds a beat grid, then makes the Pixar-style frames and clips (or hands over prompts), with one ad per hook. Built from the five top-scoring singing ads on GetHookd. Trigger on "singing ad", "song ad", "storyboard my song", "beat grid", "make frames for my song script", "Pixar song ad", or whenever someone pastes song lyrics for an ad and wants visuals, timing or prompts.
---

# Singing Ad Storyboard

> **Owner taste + auto-learning (mandatory).** `feedback.py rules` prints `feedback/OWNER_TASTE.md` first:
> the owner taste rules (T-rules), most repeated first. They win over every other rule and grow from the owner's own notes.
> Every owner revision (chat, Frame.io, review page) is logged the moment it arrives (`feedback.py add` / `frameio.py pull`)
> and learned at once with the `learn` skill: no approval step. Before ANY delivery (Frame.io push, Drive, chat) run
> `.venv/bin/python tools/preflight.py <project>`, fix every FAIL and answer every box
> in PREFLIGHT.md (taste rules + every earlier revision on this ad and its sibling hooks). `frameio.py push` refuses otherwise.


You take someone's finished song script and walk them to finished assets. Assume they have never
made an ad, never used an AI tool, and know nothing about either. Read `references/visual-dna.md`
once at the start — it is what the proven ads actually look like.

## Local environment (this machine) — read before Step 1

Camilo's skill, unchanged except this section. Where this section differs from anything below,
this section wins. Use it after `singing-drama-scripting` for a song ad with human characters (betrayal to revenge).
`song-ad-machine` stays the route for a one-mascot song film. Both use the tools here.

**Run it hands-off.** The owner is not a first-timer. Skip the step-message format and skip Step 2b: always Here mode,
never website prompts. Stop only at four points: the cast, the song take, the beat grid, and REVIEW.html.

**Tools (kie.ai replaces Maxfusion, Higgsfield and the Suno website). Run from the repo root, project in `projects/<ad>/`:**
```
.venv/bin/python -I tools/music.py song projects/<ad>/song/lead.mp3 projects/<ad>/lyrics.txt "<style>" --gender f
.venv/bin/python -I tools/music.py times projects/<ad>/song/lead.tracks.json          # add --pick 2 for the alt take
python3 -I skills/extra/singing-ad-storyboard/scripts/beat_grid.py --lyrics projects/<ad>/lyrics.txt \
    --segments projects/<ad>/song/lead.segments.json --pace standard --out projects/<ad>/grid.json
.venv/bin/python -I tools/song_plan.py projects/<ad> --song song/lead.mp3 --segments song/lead.segments.json --grid grid.json
```
Then fill each beat's `visual`/`refs` and run the normal stages: `plan_review`, `ad.py frames`, `clips`, `qc`, `review`,
`stitch`. Never run `ad.py vo` (it refuses). Set `"skill": "song-ad-machine"` so its rules and notes apply.

**Measured on a pilot song ad (8 lines):**
- A song is 12 credits for two takes, a hook take 12, word timings 0.5.
- The two takes of one lyric ran 51.5 s and 86.6 s. Pick on sound first, then on length.
- "Starts singing immediately" did NOT stop the intro: 8.8 s before the first word. `song_plan.py` trims it, so the ad
  always opens on the first sung word. Check the trim, do not trust the style text.
- Suno's word timings ran late (caption sync FAIL, median +0.18 s, worst +0.55 s). `song_plan.py` re-times from Whisper,
  which took the check to PASS. Treat `beat_grid`'s "N/M lines matched" as a lyric check only.
- Before the grid gate, diff Whisper on `VO/vo.mp3` against the lyrics. A brand or hard-word mismatch means re-roll the
  take. A brand name heard as two words ("Brand Name" for BrandName) is fine; near-misses on ordinary words: the owner's ear
  decides those. Put the brand and product words in `transcribe_hint` in `brand/brand.json`.
- Cover tracks return no word timings from kie, so time hook takes with Whisper.

**Hook takes.** `music.py hook projects/<ad>/song/hook2.mp3 hook2.txt projects/<ad>/song/lead.tracks.json --key hook2`, where
`hook2.txt` holds the hook's lines plus Verse 1's first line. It replaces the Suno Remix steps and uses `audio_weight` 0.85
(the course's Audio Influence). The words came out right on the pilot; whether voice and key match at the join is for the
owner's ear. Joining a take to the body is not automated yet: cut it in the project with ffmpeg at Verse 1's first word,
and never re-time the body to fit a hook. Reuse the body clips through `hook_variant.py`, as other ads do.

**Budget (R017, 5,000 credits an ad).** Standard pace on the pilot needed 46 s of clips for 31.8 s of song. At the measured
20 credits/s for Kling and 18 per Nano Banana Pro frame, that is about 34 credits per second of song, so about 2:25 fits.
A longer song needs shorter lyrics or owner sign-off. Fast pace doubles the shots and plays 3 s clips at about 1.8x
(Kling's minimum), so re-run the sums before offering it. The proven ads in `visual-dna.md` run about 5 to 14 minutes,
so their shot counts do not transfer. Their pace does.

**Ignore these parts of the references:**
- `models.md` is Maxfusion pricing. MiniMax H3 and Nano Banana 2 are on kie but unmeasured here, so use the existing
  Kling and Nano Banana Pro path unless the owner asks for a test.
- The SILENT line in `motion.md`. Clips generate with sound on (`ad.py`; the song SOP found silent clips move worse) and
  `plan.sfx_db` sinks them under the song.
- Pink karaoke captions. R005 captions apply.
- Anything about commercial rights, and the "Skool" setup lesson.

**Brand rules on top of `singing-drama-scripting`'s:**
- The product is never redrawn from text. `brand/brand.json` (`product_look`, `how_it_works`, `never_show`), the photos in
  `brand/product-photos/` and the animated/song R-rules bind every shot. For a "mystery product" beat, hide the real product
  in a plain unmarked pouch or box, then reveal it.
- If the product is not a body product, the glow-up is the person's life and standing, never a body change, and a "body
  cutaway" becomes a cutaway of the problem itself (the material, the object), never inside a body.
- Cast from the buyer (`audience` in `brand/brand.json` and your own customer research), never from the ads in `visual-dna.md`.

## How every message looks — enforce this above everything

1. **Header:** `**Step N of 8 · [Name]**` on its own line.
2. **Why:** one plain sentence on what this step is for.
3. **The choice**, laid out so nothing blends together:
   - each option is a bold title on its own line, e.g. `**Option 1**`
   - every detail on its own labelled line: `**They sing:** …`, `**You see:** …`, `**Cost:** …`
   - a blank line between options
4. **Reply line:** exactly what to type, e.g. `Reply **1**, **2** or **3**.` / `Reply **yes**, or tell me what to change.`
5. **Next:** last line, always: `**Next:** [what happens after they answer]`.

And:
- One question per message. Never stack two decisions.
- No jargon. Never say MCP, API, model, register, prompt engineering, beat tag, ECU. Say "make it here",
  "paste this into your image tool".
- **Never change the lyrics.** Not a word. You choose pictures and timing for them.
- **Read the whole brief first.** Editor notes, casting, story, emotion, product rules: anything already
  written is an answer. Show it back; only ask about what's missing.
- Always say the cost before spending credits, and get a yes.

## The 8 steps

| Step | Name | What happens |
|---|---|---|
| 1 | What I understood | Play the brief back; they confirm |
| 2 | Your cast | Character sheets for every person; they approve |
| 3 | Your product | Real product photo in; where it appears |
| 4 | Your song | Have one? Import it. No? Pick the lead hook and make it |
| 5 | Your storyboard | Time the song, pick pace, approve the beat grid |
| 6 | Your frames | Made here or prompts; one beat at a time |
| 7 | Your clips | Made here or prompts |
| 8 | Your ads | One ad per hook: hook takes, edit checklist |

Keep the project in one folder (`./<ad-name>/`): `brief.md`, `lyrics.txt`, `hook-N.txt`, `cast/`,
`product/`, `song/`, `segments.json`, `grid.json`, `beat-grid.md`, `prompts.md`, `frames/`, `clips/`.
Reuse accepted work; never regenerate something they approved.

## Tools — detect by capability, never ask until Step 6

At the start, silently check which tools you have for: generating images, generating video,
creating music, transcribing audio. (In Claude Code, use ToolSearch for those four; in Claude
chat, look at the connected tools.) Match on what a tool does, not a brand name. Remember what
you found; say nothing about it yet.

**Files in Claude chat:** a file the user drags in lands in the chat's file area, not in a
connected tool. To transcribe a song they dragged in, upload it to the connected tool first
(e.g. Maxfusion's upload). A song made with a connected music tool can be transcribed directly by
its id — no upload needed. If an upload fails, fall back to Step 4 option 3 timing and say so.

**Default models when generating here** (`references/models.md` has the details):
- Images: **Nano Banana 2** (`nanobanana-2.1`). Cheaper option: GPT Image 2.
- Video: **MiniMax H3** (`minimax-h3`, 768p). Cheaper option: Seedance 2.0 Mini (480p).

---

## STEP 1 · What I understood

Silently tag every line with one of the 8 story beats (`references/visual-dna.md`), save
`lyrics.txt`, and write `brief.md`. Then show it back in plain words:

> **Step 1 of 8 · What I understood**
> Before we make anything, check I read your script right.
>
> **The story:** [3 short lines]
> **The product:** [name, and the rule for how it shows up]
> **The cast:** [names in one line]
> **The hooks:** [N] — you'll get one ad per hook
> **The song:** [vocal + genre from the brief, or "not decided"]
>
> Reply **yes**, or tell me what I got wrong.
>
> **Next:** I'll make a picture of every character so you can see your cast.

Never show beat tags or line numbers. If there's no product moment, add one line:
`There's no moment to show the product — every proven ad shows it in the ritual beat.`

## STEP 2 · Your cast — and where you'll make things

**2a · The cast in words.** Lock every character from the brief (face, skin tone, build, hair,
complete outfit head to toe, jewellery). Fill gaps from the story and say which ones you filled;
never invent an ethnicity or age the brief doesn't support — ask instead. If the story has a
glow-up or a second outfit, that character gets a second sheet.

> **Step 2 of 8 · Your cast**
> First, who's in your ad. Every shot will match these looks.
>
> **[Role]:** [one line]
> (one line per character)
>
> Your notes didn't describe [X], so I suggested a look — change anything.
>
> Reply **yes**, or tell me what to change.
>
> **Next:** you'll choose where your pictures get made.

**2b · Where you'll make things — asked once, used for the whole ad.** This choice changes every
step after it, so ask it here, before any picture exists:

> **Where do you want to make your pictures and videos?**
>
> **Option 1 · Right here in Claude**
> **How it works:** I make everything and show you. You just approve.
> **You need:** Maxfusion or Higgsfield connected to Claude
>
> **Option 2 · On a website, yourself**
> **How it works:** I give you a prompt for each picture. You paste it into Maxfusion, Higgsfield,
> Kie or similar, and upload the pictures it asks for.
> **You need:** an account on one of those sites
>
> Reply **1** or **2**.
>
> **Next:** your character pictures.

- **1, tool found:** remember **Here mode**.
- **1, nothing found:** `You don't have your AI tools connected to Claude yet. This lesson shows
  you how, in about 5 minutes:
  https://www.skool.com/adcreatorslab/classroom/ad204fab?md=7566546d4db04af0be0173bf189c804d
  Come back when it's done, or reply **2** to use a website instead.`
- **2:** remember **Website mode**. Ask once which site (`Reply **Maxfusion**, **Higgsfield**,
  **Kie** or the name of yours`) and word every later instruction for that site.

Never ask this again later. Steps 3, 6 and 7 follow the mode.

**2c · The character pictures** (`styles/PIXAR-SONG-STYLE.md`). Always use the best image tool
for these — every later shot copies them, so a weak sheet weakens the whole ad.
- **Here mode:** `[N] character pictures, about [cost]. Reply **yes**.` Make them, show each under
  its name, then `Reply **yes** to keep them all, or **redo [name]** and what to change.`
- **Website mode:** one prompt per character, each in its own block, headed with the character's
  name. Then: `Paste each one into [site]. Save every picture with the character's name — you'll
  upload them again with later prompts. You don't need to send them back to me.`

## STEP 3 · Your product

The ask depends on the mode chosen in Step 2:

**Here mode**
> **Step 3 of 8 · Your product**
> I need a photo of the real product so it looks exactly right on screen.
>
> Drag a photo of your product in here, or reply **no product**.
>
> **Next:** I'll show you every moment the product appears.

**Website mode**
> **Step 3 of 8 · Your product**
> Your product photo goes into [site] with every prompt that shows the product.
>
> **1.** Save a clear photo of your product on your computer, on a plain background.
> **2.** Drag it in here too, so I can describe its shape and colour right. (Optional, but it
>    makes your prompts better.)
>
> Reply **done**, or **no product**.
>
> **Next:** I'll show you every moment the product appears.

Then show where it appears, as a short list (`**Shown:** …` per moment), including any rules from
the brief (e.g. a mystery version in the story, the real one only at the end). In Website mode,
say plainly: `Every prompt that shows the product will say **Upload: your product photo**.`

A story-only product version (e.g. an unlabelled mystery jar) gets made from the real photo:
- **Here mode:** make it, show it, `yes / redo`.
- **Website mode:** give its prompt with `Upload: your product photo` above it, and: `Save this
  picture as "mystery jar" — some later prompts will ask for it.`

Never redesign real packaging.

## STEP 4 · Your song

> **Step 4 of 8 · Your song**
> The song sets the timing for every shot, so it comes before the storyboard.
>
> **Do you have your song?**
>
> **Option 1 · Yes, I have it**
> **How it works:** drag the file in. I time every line, so each shot lands on the music.
>
> **Option 2 · No, help me make it**
> **How it works:** we make it together, then I time it.
>
> **Option 3 · Plan from the script only, no song yet**
> **How it works:** I guess the timing from your lyrics.
> **Watch out:** guessed timing is usually about 10% off. Shots won't land on the beat drops,
> and you'll trim or stretch clips in the edit to fit the real song. Use this only if you can't
> bring the song back here.
>
> Reply **1**, **2** or **3**.
>
> **Next:** [1 → I'll time every line. / 2 → you'll pick which hook leads. / 3 → I'll plan your shots.]

**1 · Yes:** import it, then Step 5. If the script has several hooks, ask which hook their file
starts with — the others are made at Step 8.

**3 · Script only:** run `scripts/beat_grid.py --script-only` and go to Step 5. Mark every
timecode `~` (e.g. `~0:23`), keep the warning as one line above the pace question, and add to the
edit handoff: `Your timings are guesses — cut each clip to the real song, not to the grid.` If they
bring a song later, re-time and keep every approved picture.

**No:** the song is made once, with one hook at the front (the **lead**). The other hooks are
recorded at the end (Step 8). Show the hooks in the option format with `**They sing:**` /
`**You see:**`, a ⭐ on the recommended lead and a one-line **Why:** — pick the hook whose last line
flows most cleanly into Verse 1 first, closeness to the proven ads (mid-action, shocked face)
second. Never call the others rejected; they are tests.

Then make it (`references/song-and-timing.md` §A):
- **Music generator found:** `Two versions of your song, about [cost]. Reply **yes**.` Play both;
  `Reply **1** or **2** to keep one.`
- **Not found:** give the **Lyrics** and **Style** blocks and the exact Suno steps, then: `Make it,
  pick your favourite version, and drag the file in.`

## STEP 5 · Your storyboard

Time the song (`references/song-and-timing.md` §B), run `scripts/beat_grid.py` at both paces, then:

> **Step 5 of 8 · Your storyboard**
> How fast the video cuts. Faster holds attention better but needs more pictures.
>
> **Option 1 · Standard**
> **Shots:** [N] (about 2.8 seconds each)
> **Like:** most of the proven ads
>
> **Option 2 · Fast**
> **Shots:** [M] (about 1.7 seconds each)
> **Like:** the top-scoring ad. Twice the pictures to make.
>
> Reply **1** or **2**.
>
> **Next:** I'll show you every shot, one part of the story at a time.

Then fill every shot with one plain-English picture (15–30 words, no film words) from the shot
library in `references/visual-dna.md`, following the grid rules there. Show the grid **one story
part at a time** — a table per part (`| Shot | Time | They sing | You see | Who | Product |`), with
`⟶ PRODUCT` on every product moment. Ask `Reply **yes**, or give shot numbers to change.` after
each part. Save everything to `beat-grid.md`; offer to share it as a page for an editor.

## STEP 6 · Your frames

Follows the Step 2 mode — never re-ask where.

**Here mode** — offer the quality choice with what it actually changes, using
`references/models.md` "Quality trade-offs". Never offer the cheap option without its downsides.

> **Step 6 of 8 · Your frames**
> Now every shot becomes a picture. Pick the quality — it changes how the ad looks.
>
> **Option 1 · Best quality — Nano Banana 2**
> **Cost:** about [cost] for all [N] pictures
> **You get:** [the "best" lines from models.md]
>
> **Option 2 · Cheaper — GPT Image 2**
> **Cost:** about [cost]
> **Watch out for:** [the "cheaper" downsides from models.md]
>
> **Option 3 · Not sure — test first**
> **How it works:** I make your first shot both ways (about [cost]) so you can see the difference.
>
> Reply **1**, **2** or **3**.
>
> **Next:** I'll make Part 1 ([n] pictures) and show you.

Then one story part at a time with a cost check before each.

**Website mode** — every shot in its own block:
`Shot 7 · 0:23`, then `**They sing:**`, then **Upload:** the pictures it needs (`[Name] picture`,
`your product photo ⟶ PRODUCT`), then the prompt. Give one story part at a time.

Build every frame from `styles/PIXAR-SONG-STYLE.md`. Check each made image: right people, right
version, readable action, product intact, no stray text. Redo a failure once; after two misses offer
a different picture for that shot.

## STEP 7 · Your clips

Follows the Step 2 mode:
- **Here mode:** the same three options as Step 6 — **Best (MiniMax)**, **Cheaper (Seedance
  Mini)**, **Test first** (one clip both ways) — each with its cost and the real trade-offs from
  `references/models.md`. Then animate one story part at a time with a cost check before each.
- **Website mode:** one motion prompt per shot (`references/motion.md`), each in its own block,
  with **Upload:** that shot's picture as the start image, and which video tool setting to pick.

## STEP 8 · Your ads

1. **Hook takes** (when there are extra hooks): give the Suno steps from
   `references/song-and-timing.md` "Hook takes" — Remix → Use as Inspiration, lyrics in Advanced,
   Audio Influence **85%**. Time each take, then make its hook shots (Steps 6–7 for just those shots).
2. Close with the filled **In the edit** block from `references/motion.md`: one ad per hook,
   named `[ad]-H1`, `-H2`, `-H3`. Don't call an ad finished unless its clips exist.

## Resuming

Read the project folder, say in one line where it stands, and ask to continue from there.
