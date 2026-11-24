"""Offline transcription adapters returning the mlx_whisper SDK dictionary shape.

Additive only: importing this module does not alter tools or install an SDK shim.
Every call requires existing local audio and model files. Model IDs/URLs are refused.
The caller must use OS network isolation for a hard offline guarantee (see docs).
"""
from __future__ import annotations

import argparse
import difflib
import importlib
import json
import math
import os
from pathlib import Path
import re
import statistics
from typing import Any


class TranscriptionError(RuntimeError):
    pass


class ModelUnavailable(ValueError):
    pass


class DependencyUnavailable(TranscriptionError):
    pass


def _backend(name: str | None) -> str:
    name = name or os.environ.get('CLOUD_TRANSCRIPTION_BACKEND', 'mlx')
    aliases = {'mlx': 'mlx', 'mlx-whisper': 'mlx', 'mlx_whisper': 'mlx',
               'faster-whisper': 'faster-whisper', 'faster_whisper': 'faster-whisper'}
    if name not in aliases:
        raise ValueError('backend must be mlx or faster-whisper; no automatic fallback')
    return aliases[name]


def _model(path: str | Path | None, backend: str) -> Path:
    if not path:
        raise ModelUnavailable('Set model_path to an existing local model directory; downloads are disabled')
    directory = Path(path).expanduser().resolve()
    required = ['config.json']
    if backend == 'faster-whisper':
        required += ['model.bin', 'tokenizer.json']
        alternatives = ['vocabulary.json', 'vocabulary.txt']
    else:
        alternatives = ['weights.safetensors', 'weights.npz']
    if (not directory.is_dir() or any(not (directory / f).is_file() for f in required)
            or not any((directory / f).is_file() for f in alternatives)):
        raise ModelUnavailable(f'Incomplete local {backend} model: require {required} and one of {alternatives}')
    return directory


def _sdk(name: str):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise DependencyUnavailable(f'{name} is unavailable; install separately after owner review; no fallback') from exc


def _interval(item: dict[str, Any]) -> None:
    start, end = item.get('start'), item.get('end')
    if (isinstance(start, bool) or isinstance(end, bool)
            or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
            or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start):
        raise TranscriptionError('Invalid transcription timestamps')


def _validate(result: dict[str, Any], word_timestamps: bool) -> dict[str, Any]:
    if not isinstance(result.get('text'), str) or not isinstance(result.get('segments'), list):
        raise TranscriptionError('Expected SDK text/segments result')
    for segment in result['segments']:
        _interval(segment)
        words = segment.get('words')
        if word_timestamps and (not isinstance(words, list) or (segment.get('text', '').strip() and not words)):
            raise TranscriptionError('Word timestamps requested but missing')
        for word in words or []:
            _interval(word)
            if not isinstance(word.get('word'), str):
                raise TranscriptionError('Invalid word text')
    return result


def transcribe(audio: str | Path, *, backend: str | None = None,
               model_path: str | Path | None = None, path_or_hf_repo: str | Path | None = None,
               language: str | None = 'en', word_timestamps: bool = True,
               device: str = 'cpu', compute_type: str = 'int8', cpu_threads: int = 0, **options: Any) -> dict[str, Any]:
    """Return {text, language, segments:[{..., words:[{word,start,end,probability}]}]}.

    path_or_hf_repo is a compatibility keyword, but MUST be a local directory.
    MLX preserves the SDK result. Faster-whisper consumes the lazy segment iterator.
    VAD stays off to avoid altering speech segmentation or downloading a VAD model.
    Faster-whisper uses greedy decoding by default (beam_size=1), matching MLX's
    default; this does not establish model parity. GPU must be explicitly selected.
    """
    if isinstance(cpu_threads, bool) or not isinstance(cpu_threads, int) or cpu_threads < 0:
        raise ValueError('cpu_threads must be a nonnegative integer')
    selected = _backend(backend)
    if model_path is not None and path_or_hf_repo is not None:
        if Path(model_path).expanduser().resolve() != Path(path_or_hf_repo).expanduser().resolve():
            raise ValueError('model_path and path_or_hf_repo conflict')
    directory = _model(model_path or path_or_hf_repo or os.environ.get('CLOUD_WHISPER_MODEL_PATH'), selected)
    source = Path(audio).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError('An existing local audio file is required')
    common = {'task', 'temperature', 'compression_ratio_threshold', 'logprob_threshold', 'no_speech_threshold',
              'condition_on_previous_text', 'initial_prompt', 'prepend_punctuations', 'append_punctuations',
              'suppress_tokens', 'hallucination_silence_threshold'}
    supported = common | ({'verbose', 'fp16'} if selected == 'mlx' else {'verbose', 'beam_size', 'best_of', 'vad_filter', 'max_new_tokens'})
    unknown = set(options) - supported
    if unknown:
        raise TypeError('Unsupported transcription options: ' + ', '.join(sorted(unknown)))
    if selected == 'mlx':
        sdk = _sdk('mlx_whisper')
        return _validate(sdk.transcribe(str(source), path_or_hf_repo=str(directory), language=language,
                                       word_timestamps=word_timestamps, **options), word_timestamps)
    if options.get('vad_filter', False) is not False:
        raise ValueError('VAD is disabled for offline timing parity')
    options.pop('verbose', None)
    options['vad_filter'] = False
    options.setdefault('beam_size', 1)
    if 'logprob_threshold' in options:
        options['log_prob_threshold'] = options.pop('logprob_threshold')
    sdk = _sdk('faster_whisper')
    engine_options = {'cpu_threads': cpu_threads} if cpu_threads else {}
    engine = sdk.WhisperModel(str(directory), device=device, compute_type=compute_type, local_files_only=True, **engine_options)
    segments, info = engine.transcribe(str(source), language=language, word_timestamps=word_timestamps, **options)
    materialized = []
    for segment in segments:
        row = {key: getattr(segment, key) for key in
               ('id', 'seek', 'start', 'end', 'text', 'tokens', 'temperature', 'avg_logprob',
                'compression_ratio', 'no_speech_prob')}
        if segment.words is not None:
            row['words'] = [{key: getattr(word, key) for key in ('word', 'start', 'end', 'probability')}
                            for word in segment.words]
        materialized.append(row)
    return _validate({'text': ''.join(s['text'] for s in materialized), 'language': info.language,
                      'segments': materialized}, word_timestamps)


def compare_word_timings(mlx: dict[str, Any], faster: dict[str, Any]) -> dict[str, Any]:
    """Compare aligned word starts AND ends; separate from the mandatory caption gate.

    Predeclared tolerance: >=98% normalized words matched in EACH transcript,
    median absolute endpoint delta <=80ms and maximum endpoint delta <=200ms.
    Empty transcripts fail. Never call this a caption_sync_check PASS.
    """
    def words(result):
        rows = []
        for segment in result['segments']:
            for word in segment.get('words', []):
                key = re.sub(r"[^a-z0-9']", '', word['word'].lower())
                if key:
                    _interval(word)
                    rows.append((key, word['start'], word['end']))
        return rows
    left, right = words(mlx), words(faster)
    matcher = difflib.SequenceMatcher(None, [w[0] for w in left], [w[0] for w in right], autojunk=False)
    deltas, matched = [], 0
    for block in matcher.get_matching_blocks():
        matched += block.size
        for a, b in zip(left[block.a:block.a + block.size], right[block.b:block.b + block.size]):
            deltas.extend([abs(a[1] - b[1]), abs(a[2] - b[2])])
    coverage = [matched / len(w) if w else 0. for w in (left, right)]
    median = statistics.median(deltas) if deltas else None
    maximum = max(deltas) if deltas else None
    passed = bool(deltas) and min(coverage) >= .98 and median <= .08 and maximum <= .2
    return {'status': 'PASS' if passed else 'FAIL', 'matched_words': matched,
            'mlx_words': len(left), 'faster_words': len(right), 'coverage': coverage,
            'median_absolute_endpoint_delta_seconds': median, 'max_absolute_endpoint_delta_seconds': maximum,
            'caption_gate': 'NOT RUN'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', type=Path)
    parser.add_argument('--backend', choices=['mlx', 'faster-whisper'], default=None)
    parser.add_argument('--model-path', type=Path, required=True)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--compute-type', default='int8')
    args = parser.parse_args()
    result = transcribe(args.audio, backend=args.backend, model_path=args.model_path,
                        device=args.device, compute_type=args.compute_type)
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
