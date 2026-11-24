# Learned rules — song-ad-machine

Each rule comes from an owner review. Read these before starting an ad: `ad.py <project> rules` (or `feedback.py rules song-ad-machine`). New rules arrive through `feedback.py promote`.

- **R039** Pixar frames with the product in a character's hand: never paste a photo of the product onto the frame. Draw it on the character's own hand with the image model (nano-banana-pro), using the styled product references (see the animated-ad-machine rules) and a camera angle that keeps the product's shape readable. The logo stays sharp this way, so this overrides the composite-last step of R035 for these frames. Zoom-check the logo and hand on every frame, and feed one good frame as a reference so neighbouring frames match.

## agentchad seeds (A-rules; owner can strike any; apply to singing-ad-storyboard too)
Seeded from the free agentchad.io skills (Reality Drama Engine, Trendjack Animator), not from an owner review. Source copies: `knowledge/agentchad/`. The owner can strike any of them; an owner R-rule always wins over an A-rule.
- **A401** The song starts on the singing: at most 0.5 s of music before the first sung word. Trim a long intro; never cover it with a held frame.
- **A402** Pick a genre the target buyer listens to. Rap or EDM on an ad for an older buyer feels wrong at once; a slow ballad kills a short ad.
- **A403** Whisper with an initial_prompt repeats lyric lines as zero-length "ghost" words: run it without one and drop zero-length repeats. Whisper may invent a closing line over the outro: drop words after the last sung line. Captions keep the approved lyric spelling.
- **A404** Sung vs spoken comes from the reference's audio, not the brief: a reference that is a song, rebuilt as a spoken VO, is rejected on sight.
- **A405** Genre by buyer: 45+ home and family = warm country-pop or acoustic pop, 100-115 bpm; broad 25-45 = upbeat pop 110-120; young/playful = bright pop with handclaps 115-125. Avoid genres that bury words (dance, house, EDM, K-pop). Never slow or sad.
- **A406** Length is words x tempo: about 80-90 sung words a minute (about 2 a second; ~30 words for a 15 s drama song, ~40 for 30 s), 3-7 words per sung line. Product songs repeat the chorus word for word and carry at most one feature line.
- **A407** Write the brand name in the lyrics the way it must be SUNG and fix the spelling in the captions. To translate a song ad, make a Suno Cover of the approved song with the translated lyrics and the same line count (Audio Influence ~60 %, Style ~70 %, Weirdness ~30 %), never a fresh song; see multi-market-agent.

## Owner rules (continued)

