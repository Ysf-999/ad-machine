# Library v2, 2026-11-09 (agentchad.io). Keys only from your own environment; nothing here is account-specific.
# 2026-11-10: WHISPER_MODEL from ~/.agentchad/settings.env, default small (one default for the whole library);
#             with a language code it also runs a separate language check (no, nn and nb all count as Norwegian).
"""transcribe.py <media> <out.json> [lang]
Word-timed transcript of a video or audio file with faster-whisper. Prints the segments as it goes.
Settings (environment variable, then ~/.agentchad/settings.env, then the default):
  WHISPER_MODEL  default small (about 0.5 GB, downloaded once on first use; the default in every skill of the
                 library, so it downloads only once). large-v3-turbo (about 1.6 GB) = best quality, slower.
  WHISPER_DEVICE default cpu.
Language codes: sv Swedish, no Norwegian (nb and nn are accepted too), da Danish, fi Finnish, de, fr, nl, en.
Run with the shared Python (AGENTCHAD_PY); started with another Python it switches by itself. Exit code 3 =
faster-whisper missing.
Leave [lang] out the first time so Whisper detects the language: some ads have English speech with local captions.
With [lang] (the final check of a translated ad): the text is written in that language, and the language is ALSO
detected on its own and compared with it, so a wrong-language mix still shows up ("language check: OK / CHECK").
Output: {"language": .., "segments": [{"start","end","text","words": [[start,end,word],..]}],
         "language_check": {"target": .., "detected": .., "share": ..}}   (the last key only with [lang])"""
import sys, json, subprocess, tempfile, os
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py import need, setting  # noqa: E402
if len(sys.argv) < 3:
    sys.exit(__doc__)
need(['faster_whisper'])
from faster_whisper import WhisperModel  # noqa: E402
media, out = os.path.expanduser(sys.argv[1]), os.path.expanduser(sys.argv[2])
if not os.path.exists(media):
    sys.exit(f'not found: {media}')
# Whisper knows Norwegian as "no" (and Nynorsk as "nn"); "nb" (Bokmal) is the same language for this check.
FAMILY = {'no': {'no', 'nn', 'nb'}, 'nn': {'no', 'nn', 'nb'}, 'nb': {'no', 'nn', 'nb'}}
target = sys.argv[3].lower() if len(sys.argv) > 3 else None
lang = 'no' if target == 'nb' else target
model = setting('WHISPER_MODEL', 'small')
device = setting('WHISPER_DEVICE', 'cpu')
fd, wav = tempfile.mkstemp(suffix='.wav'); os.close(fd)
print(f'Whisper model {model} (the first use downloads it once: small about 0.5 GB, large-v3-turbo about 1.6 GB)',
      flush=True)
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', media, '-vn', '-ac', '1', '-ar', '16000', wav], check=True)
m = WhisperModel(model, device=device, compute_type='int8' if device == 'cpu' else 'float16')
segs, info = m.transcribe(wav, language=lang, word_timestamps=True)
res = []
for s in segs:
    print(f'{s.start:6.2f}-{s.end:6.2f}  {s.text.strip()}', flush=True)
    res.append({'start': s.start, 'end': s.end, 'text': s.text.strip(),
                'words': [[w.start, w.end, w.word.strip()] for w in s.words]})
doc = {'language': info.language, 'segments': res}
check = None
if target:
    try:
        from faster_whisper.audio import decode_audio
        det, prob, allp = m.detect_language(decode_audio(wav, sampling_rate=16000))
        fam = FAMILY.get(target, {target})
        share = sum(p for code, p in allp if code in fam)
        ok = det in fam or share >= 0.5
        check = {'target': target, 'detected': det, 'detected_p': round(prob, 2), 'share': round(share, 2), 'ok': ok}
        print(f"language check: detected {det} {prob:.2f}; target {target}"
              + (f" (no, nn and nb together {share:.2f})" if target in FAMILY else f" {share:.2f}")
              + (" -> OK" if ok else " -> CHECK: the mix may still hold the old voice, or a line was not replaced"))
    except (ImportError, AttributeError, TypeError, ValueError) as e:   # older faster-whisper without detect_language
        print(f'language check skipped ({e.__class__.__name__}: this faster-whisper cannot detect separately); '
              f'read the text above: it must be the target language, every line there')
    doc['language_check'] = check
json.dump(doc, open(out, 'w'), ensure_ascii=False, indent=1)
os.remove(wav)
print('language', info.language, round(info.language_probability, 2) if not target else '(given)')
print('Check the last segment: Whisper often invents a closing line. Check every number against the script.')
