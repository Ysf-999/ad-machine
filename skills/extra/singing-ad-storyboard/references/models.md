# Models and costs (Maxfusion, checked 2026-10-14)

| Job | Default | Id | Cost | Cheaper option | Id | Cost |
|---|---|---|---|---|---|---|
| Character sheets, frames | Nano Banana 2 | `nanobanana-2.1` | ~4 cr / image | GPT Image 2 | `gpt-image-2` | ~1 cr / image |
| Clips | MiniMax H3 | `minimax-h3` @ 768p | 3 cr / second (5s min → 15 cr) | Seedance 2.0 Mini | `seedance-2.0-mini` @ 480p | 2 cr / second (4s min → 8 cr) |
| Song | Suno V6 | `maxfusion_create_music` | 5 cr per call (2 takes) | — | | |
| Timing | Transcription | `maxfusion_transcribe_media` | free | ElevenLabs `speech_to_text` | | |

Prices move. Read the current numbers from `maxfusion_list_image_models` / `maxfusion_list_video_models`
before quoting, and quote totals ("Beat 1 is 9 frames, about 36 credits").

## Quality trade-offs — what to tell the user (plain words, no model jargon)

Character sheets always use the best option: every later shot copies them.

**Pictures**

| | Best — Nano Banana 2 | Cheaper — GPT Image 2 |
|---|---|---|
| Same face in every shot | Holds the character pictures closely across 70+ shots | More likely to drift — a face can change slightly from shot to shot, and you redo more |
| The Pixar look | Stays in the animated style | Leans more realistic; some shots can look less like a cartoon film |
| Product label | Good | Very good — clean, sharp text on labels and signs |
| Speed | Slower | Faster |

**Clips**

| | Best — MiniMax (768p) | Cheaper — Seedance Mini (480p) |
|---|---|---|
| Sharpness | Sharper picture | Lower resolution — softer, especially on phones held close |
| Faces in wide shots | Stay readable | Small faces can smear or lose detail |
| Product label | Readable | Small text can blur |
| Length | 5s minimum per clip | 4s minimum per clip |

These are expected differences, not measured on this style yet. When the user is unsure, offer
the **test first** option — the first shot made both ways — rather than arguing it.

## Using references

- Images: character sheets first, then supporting cast sheets, product photo last. Describe people
  only by reference ("the man from Image 1") — appearance words fight the reference.
- MiniMax H3 binds references with `@image1`, `@image2` tags in the prompt; frames mode takes the
  approved still as the start frame. Use frames mode with the shot's still.
- Never ask the clip for singing or lip movement; clips are silent, the song is the audio.
