# Learned rules — ugc-talking-head

Each rule comes from an owner review. Read these before starting an ad: `ad.py <project> rules` (or `feedback.py rules ugc-talking-head`). New rules arrive through `feedback.py promote`. None yet.


## agentchad seeds (A-rules; owner can strike any)
Seeded from the free agentchad.io skills (Reality Drama Engine, Trendjack Animator), not from an owner review. Source copies: `knowledge/agentchad/`. The owner can strike any of them; an owner R-rule always wins over an A-rule.
- **A101** Gemini Omni Flash: write one frozen voice sentence per person ("<label> speaks English with a natural <accent> accent, <age>-year-old <gender> voice, <tone>, <pace> pace.") and paste it unchanged into every clip of that person, or the voice drifts between clips. End the voice block with "Exactly these words, nothing added."
- **A102** Omni: if a clip rushes or swallows words, drop to about 2.5 spoken words per second of clip (8 s ≈ 20 words), each clip ending at the end of a sentence.
- **A103** Match the voice to the face: an older face needs an older voice description, or it reads fake at once.
- **A104** Realism is an input problem: if the person looks plastic, redo the still (candid phone photo, one real light source, real skin with pores, slight grain), not the adjectives in the clip prompt.
- **A105** Start on the first real line: no "hi guys", no breath or room tone before the first word.
- **A106** A cloned or TTS voice laid on phone footage sounds too clean, and that is what gives it away. Give it the original's room sound with `.venv/bin/python -I -B knowledge/agentchad/multi-market-agent/scripts/envmatch.py <voice.wav> <original vocals.wav> out.wav 0.18 0.13 8 1.0` (original vocals from demucs; wet 0 for outdoor speakers), then match the level.
- **A107** Photoreal phone-footage stills: keep the top 18 % and bottom 25 % of the frame free of anything important (faces, the product, hands) so the app UI and captions never cover it.
- **A108** Lip-sync to an external voice: test ONE shot before planning a talking ad on a model. Several video models ignore the audio and invent their own garbled speech; only models that list audio-conditioned lip sync follow the words.

## Owner rules (continued)

