# Multi-Market Agent: how it works, in plain language

## What it does, end to end

You have an ad that sells in one country. This system makes the same ad for another country: same pictures, same music, same cuts, but a new voice in the new language, new captions, and the right local details (money, units, places). It can start from video files on your computer, or it can look into your Meta ad account, list your best ads by spend, and translate the ones you pick.

It also takes an English (US) video and turns it into a European ad, converting dollars, ounces and American references instead of translating them word for word.

## Before the first run

Claude asks its questions in one message (which videos, from and to which language, whether you have the version
without captions or the music on its own, what kind of video, the voice, your native speaker, the new market's offer
and the words never translated, lipsync consent, the code prefix), then checks every tool one by one (ffmpeg, the
library's shared Python, demucs if you want it, the caption font, ElevenLabs, voices, and only if you use them Vmake,
sync., Suno and the Meta token) and tells you the exact fix for anything missing. A translation needs no full brand
pack: your answers about the new market's offer are saved as a short translation stub, and `brand-research` is offered
after the first video, not before. No caption remover is fine: the clean export or a free blurred cover does the job.
Then a free 10-second test of the whole pipeline. Every finished video gets the motion and sound-effects pass and `qa-sniper`,
and Claude asks whether to upload it to Meta. Full list: "First run" in SKILL.md.

## The pipeline

```
 PICK            CHECK              STRIP              WORDS                 VOICE              FIT
 ────            ─────              ─────              ─────                 ─────              ───
 your files  ─►  already done? ─►   old captions  ─►   transcript      ─►    new voice     ─►   every line placed
 or top ads      sung or spoken?    removed in the     line-by-line          per line           where the original
 by spend        which language?    caption band:      translation +         (ElevenLabs,       line started,
 (read-only)                        clean export,      native read           paid)              first word at 0.0 s
                                    Vmake (paid) or                                             (gentle speed-up)
                                    free blur cover
                                                                                   │
        ┌──────────────────────────────────────────────────────────────────────────┘
        ▼
 MIX                     CAPTIONS                  RENDER                    QA + LOG
 ───                     ────────                  ──────                    ────────
 new voice +        ─►   one line, one size,  ─►   original picture,    ─►   frame sheet, qa-sniper,
 original music          long words split,         clean band only           final audio transcribed:
 (old voice removed),    safe zone, no             where captions were       right language, every line
 -14 LUFS                punctuation
```

## What each step outputs

| Step     | Output                                                                               |
| -------- | ------------------------------------------------------------------------------------ |
| Pick     | a list of ads with spend, purchases and ROAS (from the API), or your chosen files    |
| Check    | "already translated?" answer from the log; language; sung or spoken score            |
| Strip    | a caption-free copy (clean export, Vmake) or a blurred cover, used only in the caption band |
| Words    | `src.json` (original words with times), `lines.json` (the translation, line by line) |
| Voice    | one audio file per line in `vo/`                                                     |
| Fit      | `schedule.json`: where each new line starts and ends, and how far it moved           |
| Mix      | `vo.wav` (voice track) and the voice + music mix                                     |
| Captions | caption images and a timing list in `caps/`                                          |
| Render   | the finished video in the ad's project folder                                        |
| QA + log | a frame sheet, a transcript of the final video, one line in `translations.md`        |

## Time and cost guide

| Part                                                  | Time for a 30 s ad               | Cost                                                                   |
| ----------------------------------------------------- | -------------------------------- | ---------------------------------------------------------------------- |
| Pick, check, transcript, timing, captions, render, QA | 10-25 minutes of computer time   | free (runs on your machine)                                            |
| Caption removal (only if captions are burned in)      | a few minutes to tens of minutes | one Vmake job                                                          |
| New voice                                             | about a minute                   | ElevenLabs characters, roughly one per letter of the translated script |
| Lipsync (optional, talking creators)                  | several minutes                  | sync. seconds of output; test 10 s first                               |
| Song cover (song ads only)                            | a few minutes in the browser     | your Suno plan                                                         |
| Native-speaker read                                   | 5 minutes of someone's time      | free if you have a friend in that market                               |

Every paid step stops and asks first, with the count (characters, seconds, jobs) on screen.

## What to check before you trust the output

1. **A native speaker** read the translation before the voice was made, and listened to the final.
2. **The final transcript** is in the target language and has every line (no English left, no line missing).
3. **Every line starts close to where the original line started** (`schedule.json` shows the drift; aim for under 0.6 s).
4. **Captions**: one line each, the same size throughout, inside the safe zone, never over a face or the product.
5. **Logos and labels** are still there (the clean video was only used in the caption band).
6. **Sound**: the music bed is the original's, no hiss where the old voice was, the voice level matches.
7. **Local details**: no dollar amounts, ounces, US holidays or US store names left in a European ad.
8. **The code**: the file and ad name carry the target market's prefix with the original number, and the log line is written.
