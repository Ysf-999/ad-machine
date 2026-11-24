#!/usr/bin/env python3
"""Measure local audio by decoded samples; validate sample-based scene coverage.

Requires Python 3.10+, ffmpeg and ffprobe on PATH. No network or paid API calls.
"""
import argparse
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile


def decimal_text(value):
    with localcontext() as ctx:
        ctx.prec = 28
        return format(Decimal(value.numerator) / Decimal(value.denominator), '.9f')


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path, audio_stream, fps):
    path = Path(path).expanduser().resolve(strict=True)
    info = json.loads(subprocess.run(
        ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
        check=True, capture_output=True, text=True).stdout)
    streams = [s for s in info['streams'] if s['codec_type'] == 'audio']
    if not streams:
        raise ValueError('No audio stream found in the supplied file')
    if audio_stream is None:
        if len(streams) > 1:
            raise ValueError('Multiple audio streams; choose the voiceover using --audio-stream')
        audio_stream = 0
    if not 0 <= audio_stream < len(streams):
        raise ValueError(f'Audio stream selection must be between 0 and {len(streams) - 1}')
    stream = streams[audio_stream]
    rate, channels = int(stream['sample_rate']), int(stream['channels'])
    byte_count = 0
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(
            ['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(path),
             '-map', f'0:a:{audio_stream}', '-vn', '-sn', '-dn',
             '-c:a', 'pcm_s32le', '-f', 's32le', 'pipe:1'],
            stdout=subprocess.PIPE, stderr=errors)
        try:
            while chunk := proc.stdout.read(1024 * 1024):
                byte_count += len(chunk)
        finally:
            proc.stdout.close()
        if proc.wait():
            errors.seek(0)
            raise ValueError('Audio decode failed: ' + errors.read(800).decode(errors='replace'))
    if not byte_count or byte_count % (4 * channels):
        raise ValueError('Audio decoded to no complete samples')
    samples = byte_count // (4 * channels)
    duration = Fraction(samples, rate)
    frame_count = math.ceil(duration * fps)
    return {
        'source_path': str(path), 'source_sha256': file_hash(path),
        'audio_stream': audio_stream, 'codec': stream['codec_name'],
        'sample_rate': rate, 'channels': channels, 'decoded_samples': samples,
        'duration_fraction': str(duration), 'duration_seconds': decimal_text(duration),
        'container_duration_seconds': info.get('format', {}).get('duration'),
        'stream_duration_seconds': stream.get('duration'),
        'stream_start_seconds': stream.get('start_time'),
        'fps': str(fps), 'video_frames': frame_count,
        'video_duration_seconds': decimal_text(Fraction(frame_count, 1) / fps),
        'last_frame_padding_seconds': decimal_text(Fraction(frame_count, 1) / fps - duration),
    }


def check(timing_path, scenes_path):
    timing = json.loads(Path(timing_path).read_text())
    board = json.loads(Path(scenes_path).read_text())
    if board['source_sha256'] != timing['source_sha256']:
        raise ValueError('Board source hash differs from measured voiceover; realign the board')
    if file_hash(timing['source_path']) != timing['source_sha256']:
        raise ValueError('The source audio changed after measurement; remeasure and realign')
    fps = Fraction(timing['fps'])
    rate = timing['sample_rate']
    frames = []
    cursor = 0
    seen = set()
    for scene in board['scenes']:
        if not isinstance(scene['id'], str) or not scene['id'] or scene['id'] in seen:
            raise ValueError('Each scene requires a unique, nonempty string ID')
        seen.add(scene['id'])
        start, end = scene['start_sample'], scene['end_sample']
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= timing['decoded_samples']:
            raise ValueError(f"Scene {scene['id']} requires positive integer sample coverage inside the audio")
        if start != cursor:
            raise ValueError(f"Scene {scene['id']} must start at sample {cursor}; got {start}")
        first = math.ceil(Fraction(start, rate) * fps)
        last = math.ceil(Fraction(end, rate) * fps)
        if last <= first:
            raise ValueError(f"Scene {scene['id']} is shorter than the available video frame interval")
        frames.append({'id': scene['id'], 'start_frame': first, 'end_frame': last,
                       'frame_count': last - first,
                       'duration_seconds': decimal_text(Fraction(end - start, rate))})
        cursor = end
    if cursor != timing['decoded_samples']:
        raise ValueError(f"Scenes end at sample {cursor}; audio ends at {timing['decoded_samples']}")
    return {'valid': True, 'video_frames': math.ceil(Fraction(timing['decoded_samples'], rate) * fps),
            'scenes': frames}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('probe', help='Count decoded audio samples and print timing JSON')
    p.add_argument('audio')
    p.add_argument('--audio-stream', type=int, help='Zero-based audio stream; required for multi-track files')
    p.add_argument('--fps', type=Fraction, default=Fraction(30), help='Export FPS, e.g. 30 or 30000/1001')
    c = sub.add_parser('check', help='Validate scene coverage and print global frame boundaries')
    c.add_argument('timing')
    c.add_argument('scenes')
    args = parser.parse_args()
    try:
        if args.command == 'probe':
            if args.fps <= 0 or (args.audio_stream is not None and args.audio_stream < 0):
                raise ValueError('FPS must be positive; audio stream must be nonnegative')
            result = probe(args.audio, args.audio_stream, args.fps)
        else:
            result = check(args.timing, args.scenes)
    except (OSError, ValueError, TypeError, KeyError, IndexError, ZeroDivisionError, subprocess.SubprocessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
