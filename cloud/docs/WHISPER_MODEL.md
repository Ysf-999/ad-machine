# Whisper model for the cloud workers

Captions are timed by Whisper on the real audio. On the Mac the tools use `mlx-whisper` with
`mlx-community/whisper-large-v3-turbo`. In the cloud (Linux, CPU) the same model runs through `faster-whisper`:

- Model: `openai/whisper-large-v3-turbo` at revision `41f01f3fe87f28c78e2fbf8b568835947dd65ed9` (MIT license),
  converted to CTranslate2 with `ct2-transformers-converter --quantization float16`. Same learned weights as the MLX
  copy; inference runs on CPU in float32.
- Where: the Modal Volume `<app_prefix>-whisper-ct2`, mounted read-only at `/model` in every worker
  (`controller/app.py`). Files at the volume root: `README.md`, `config.json`, `generation_config.json`, `model.bin`,
  `preprocessor_config.json`, `tokenizer.json`, `vocabulary.json` (about 1.6 GB).
- Check: `worker/ad_job.py` (`MODEL_SHA`) hash-checks each file when it copies the model into the container and refuses
  a mismatch. The hashes in the file are those of the conversion made with ctranslate2 4.6.0, transformers 4.48.3 and
  torch 2.6.0. If your conversion gives different hashes, put yours in `MODEL_SHA`
  (`docs/SETUP_CLOUD.md` step 6 shows the command that prints them).
- Settings: `cloud/whisper-settings.json` (`faster`: CPU, float32, beam 1, word timestamps, the same temperature and
  threshold ladder as the Mac profile in `production_mlx`). `worker/adjob_boot.py` loads the model once per process and
  caches each transcription by audio bytes + settings + model.

The Mac's MLX timing stays the authority for caption sync: `collect` re-runs the Mac checks on every finished ad.
