# Song and timing

## A. Making the song

The user's lyrics are final. Never rewrite, trim or "improve" a line. Section tags and beat tags
are the only things you add.

### Suno-style prompt (copy-paste path)

Give two blocks.

**Lyrics** — their lyrics exactly, with simple section tags (`[Verse]`, `[Chorus]`, `[Bridge]`,
`[Outro]`) on their own lines. Remove the `[Beat …]` tags first — those are for the grid, not the
singer.

**Style** — at most 1,000 characters, no artist names. Start from this and adjust to the brief:

```
Emotional storytelling soul and R&B ballad, one [warm female | warm male] lead vocal, clear diction, conversational sung phrasing that follows the lyrics line by line, intimate piano and soft strings in the verses, steady mid-tempo, building to a confident gospel-tinged finale. Starts singing immediately, no long intro, no instrumental solos, no ad-libs, no spoken words, no added verses or repeated sections, clean ending.
```

Match the singer to the narrator: a woman's story gets a female vocal, a man's story a male vocal.
These style words are a starting point, not measured from the reference audio — ask the user to
judge the first take by ear.

Tell the user: paste lyrics and style into their song tool's two fields, make two takes, pick
one, drag the file back in (MP3 or WAV).

### In-chat path (when a music generator is connected)

Run ToolSearch for `create music` / `generate song`. Match by what the tool does.

- Maxfusion `maxfusion_create_music` runs Suno V6: 5 credits, two takes per call. Prefix the
  lyrics with `use these exact lyrics:` and leave duration on Auto — fixed durations exist only
  at 15/30/60/120/180/360s and cut long songs. If the job reads "running" for more than ~2
  minutes, check the project's audio list instead of waiting; status lags behind the file.
- ElevenLabs `compose_music` also works; give it the lyrics and the style text.
- Say the cost and get a yes before calling. Play or link both takes and let them pick.
- Commercial rights for Suno output through third-party tools are unconfirmed. Say so once if
  the user asks about running the song in paid ads.

### Hook takes (when the script has more than one hook) — done at Step 8

The full song is made with the lead hook. Each other hook is a short separate take, made from
the lead song so the voice and sound match. Give the user these exact Suno steps:

1. In Suno, find the song you chose. **Right-click it → Remix → Use as Inspiration.**
   (This is a Suno Pro feature.)
2. Open **Advanced**. Paste the lyrics: this hook's lines, then Verse 1's first line — so there is
   a natural join to cut on.
3. Open **More Options**. Set **Audio Influence to 85%**. This is the setting that keeps the same
   voice and sound — don't skip it.
4. Create, pick the best take, drag it back in.

- **Style:** keep the exact style block used for the lead song.
- **In the edit:** play the take up to the start of Verse 1's first line, then cut to the lead
  song at the same word. Check the join by ear — key, tempo and voice must match. If they don't,
  regenerate that take; never re-time the body to fit a hook.
- Time each take on its own (`beat_grid.py` on the take's lyrics) to get its hook shots.

## B. Timing the song

The grid is only as good as its timestamps. In order of preference:

1. **A transcription tool** (ToolSearch `transcribe` / `speech to text`): Maxfusion
   `maxfusion_transcribe_media` after uploading the audio, or ElevenLabs `speech_to_text`.
   Save the result as `segments.json` — a list of `{"start", "end", "text"}` in seconds.
2. **Local whisper**, if `whisper` is installed:
   `whisper song.mp3 --model small --output_format json` and pass its `segments`.
3. **No song at all (Step 4 option 3)**: run with `--script-only`. Length comes from the word
   count at 2.5 sung words/second (measured across the five proven ads). Tested on Ad 5: estimated
   4:32 vs real 4:12 — about 8% long — and individual lines drift more than that. Always label
   these timecodes as guesses.
4. **Song but no transcript**: run the script with `--duration <seconds>` (get it with
   `ffprobe -show_entries format=duration -of csv=p=0 song.mp3` or `ffmpeg -i song.mp3`).
   Lines are spaced by syllable count and the grid is marked ESTIMATED. Tell the user the
   timecodes are a guess until they check them against the song.

### Running the grid

Write the lyrics to `lyrics.txt` — one sung line per line, with a `[Beat N · Name]` tag on its
own line wherever a story beat starts. Then:

```bash
python3 scripts/beat_grid.py --lyrics lyrics.txt --segments segments.json --pace standard --out grid.json
```

- `--pace standard` ≈ 2.8s shots (most proven ads). `--pace fast` ≈ 1.7s shots (the
  top-scoring ad) — about twice as many frames to make. Recommend standard for a first ad.
- The script prints `N/M lines matched`. Below ~85% the song strays from the lyrics (Suno
  repeats or drops lines): show the user which lines were interpolated and ask whether the song
  or the lyrics file is right.
- Cuts land only on line starts. The hook holds its first line. Never re-time by hand to
  hit round numbers.

## C. Story beats — tagging the lyrics

Tag each line with one of the 8 beats in `references/visual-dna.md`. Most scripts follow them
in order; a beat may be missing (say so — Ad 5 skips the sacrifice). A song that has no
messenger or no ritual has no product moment — tell the user before building the grid, because
that is where every proven ad shows the product.
