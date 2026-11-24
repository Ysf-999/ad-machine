# Reality Drama Engine: workflow breakdown

Plain-language breakdown for people who don't write code. The full instructions Claude follows are in `SKILL.md`.

## What it does, end to end

You describe your product and who buys it. Claude writes a short real-life scene (a remark that stings, a friend who
brings the fix, a street interview, a testimonial in a car), designs the people in it as photos that look like they
were taken on a phone, and has an AI video model (Gemini Omni Flash 1.1, through Starpop) film each line with that
person saying the words themselves. Claude then checks every clip, cuts the ad together and adds captions. You get
three finished versions of the same ad, each with a different opening (hook), ready to test.

You approve three things before any money is spent: the script, the people (stills) and the price estimate.

## Before the first run

Claude reads your settings (`## agentchad settings` in your project CLAUDE.md; missing: say `set up the ad clone
system`). It runs the brand check first and also checks your product's real size by eye. If your brand pack is
missing or thin (no list of what the product never claims, fewer than 10 real customer quotes, no offer), it stops
and offers to run `brand-research` first. Then it asks its Step 1 questions in one message and checks Starpop and
its credits, ffmpeg, Python, the caption route and your product photo. Reference ads come from your ad library
(Atria, TrendTrack or any library with an API) or the free Meta Ad Library. Before delivery every video gets the
`motion-and-sfx-kit` pass and the `qa-sniper` check, you review it (Frame.io comments on exact timestamps, or notes
with timestamps in a review file), and Claude asks "Do you want to upload these to Meta, TikTok, Snapchat, Google or AppLovin?". Full list: "First run"
in SKILL.md.

## The pipeline

```
 YOU: product, buyer, offer, language, format
        |
        v
 [1] SCENE + SCRIPT ............ 3 hooks on one shared body, split into 3-10 s clips   (free)
        |  you approve
        v
 [2] PEOPLE STILLS ............. one "phone photo" per person = their identity        (paid, small)
        |  you approve
        v
 [3] CLIP PROMPTS .............. exact lines in quotes + frozen voice + room sound
        |                        + the clean-frame line (no text in the picture)
        v
 [4] COST ESTIMATE ............. total credits for all clips                          (free)
        |  you approve
        v
 [5] GENERATE .................. one test clip first, then the rest                    (paid)
        |
        v
 [6] CHECK EVERY CLIP .......... words vs script (wordcheck.py), text, faces, products  (free)
        |  failed clip? fix that prompt, ask, regenerate only that clip
        v
 [7] ASSEMBLE .................. 30 fps, trims, loudness, one file per hook (assemble.py) (free)
        |
        v
 [8] CAPTIONS ................. scripts/captions.py (built in)                     (free)
        |
        v
 FINAL: final/<CODE>_A.mp4, _B.mp4, _C.mp4  +  what was checked, credits spent, retakes
```

## What each step outputs

| Step             | Output                                           | Where                                                        |
| ---------------- | ------------------------------------------------ | ------------------------------------------------------------ |
| 1 Scene + script | Script, 3 hooks, scene plan, storyboard table    | `<WORKSPACE>/<BRAND>/05_briefs/`                             |
| 2 Stills         | One 9:16 phone-style photo per person per scene  | `<MEDIA_DIR>/<BRAND>/ads/<MARKET>/<CODE>.<n>-<slug>/stills/` |
| 3 Prompts        | One prompt per clip (in the brief file)          | `05_briefs/`                                                 |
| 5 Generate       | 3-10 s clips with the person speaking            | `.../clips/`                                                 |
| 6 Check          | A pass/fail per clip with the reason             | Claude's report                                              |
| 7 Assemble       | One mp4 per hook, 1080 x 1920, 30 fps            | `.../final/`                                                 |
| 8 Captions       | Captioned finals + a first-3-seconds check sheet | `.../final/`                                                 |

## Why it looks real (the three locks)

1. **Phone-Photo Lock** — every clip starts from the same designed still that already looks like a real phone photo.
   Fake-looking people are fixed in the photo, never with more adjectives.
2. **Native Speech** — the video model speaks the line inside the clip, so lips, breath and gestures belong together.
   A frozen voice description, pasted unchanged into every clip, keeps the voice the same person.
3. **Clean-Frame Guard** — every prompt bans letters in the picture; captions are added at the end where you control
   spelling, size and position.

Drama scenes are filmed like TV: one clip per speaker turn (shot, reverse shot), plus silent reaction shots. That keeps
the right words in the right mouth.

## Time and cost guide (rough, check your own plan)

| Ad                             | Clips | Credits (approx.) | Time with checks  |
| ------------------------------ | ----- | ----------------- | ----------------- |
| 15 s talking head, 3 hooks     | 3-4   | 35-50             | about 45 minutes  |
| 30 s talking head, 3 hooks     | 4-6   | 60-80             | about 1-1.5 hours |
| 30 s two-person drama, 3 hooks | 6-9   | 90-120            | about 2 hours     |

Omni Flash 1.1 at 1080p costs about 1.5 credits per second of video. One 8 s clip takes about 3-5 minutes to make.
Expect one or two retakes per ad. Claude shows the exact estimate before every paid step; prices change.

## What to check before you trust the output

- **Listen to every final yourself.** Claude reads transcripts; it cannot hear an odd accent or a robotic pause.
- The words in each clip match the approved script (`wordcheck.py` prints MATCH).
- No letters anywhere in the picture except your real product label.
- The same face, hair and clothes in every clip of that person; no extra fingers.
- The product is the real one, at the real size, packaging as sold.
- The room sound matches the place (no hiss in a kitchen, no echo in a car).
- No repeated stranger in the background.
- Captions sit inside the safe zone and never cover a mouth, face or product (`scripts/captions.py`, then look at the frames).
- Your ad platform's rules on AI-generated people and on claims are respected before the ad goes live.
