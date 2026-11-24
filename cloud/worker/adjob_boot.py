"""Python launcher for cloud ad jobs: `python [-I] script.py args` -> same run, with two process-local shims.

Every tool the pipeline starts goes through work/.venv/bin/python, a tiny shell wrapper that execs this file, so the
shims reach every child process (ad.py starts gen_scenes.py, batch.py, assemble_anim.py ... with `-I`, which would
otherwise drop PYTHONPATH/sitecustomize). Originals in tools/ are never edited.

Shim 1, mlx_whisper: Linux has no MLX, so `mlx_whisper.transcribe` is served by cloud/transcription.py with the
frozen faster-whisper CPU profile (cloud/whisper-settings.json) and the hash-verified CT2 model in
<work>/.ct2. Same dict shape as mlx_whisper. Captions stay informational: the Mac MLX check is authoritative.

Shim 2, kie: POSTs are sent ONCE (the original _req retries 3x, which can double-submit a paid createTask), and a
job-wide task counter (<work>/.adjob/tasks.jsonl, flock) refuses createTask beyond ADJOB_MAX_TASKS. Polls (GET) keep
the original retry behaviour; resubmits after a failed task stay the original tool's decision but count toward the cap.
"""
import fcntl
import importlib.abc
import importlib.util
import json
import os
import pathlib
import re
import runpy
import sys
import time
import types

WORK = pathlib.Path(os.environ.get('ADJOB_WORK', '/tmp/adjob/work'))
STATE = WORK / '.adjob'


_CALLS = []   # [tool, output or audio name, seconds] for the render stopwatch (ffmpeg calls and Whisper calls)


def _keep_whisper_model_loaded():
    """rawedit times captions with one Whisper call per beat, and cloud/transcription.py builds the model inside every call
    (about 30 loads of the same model per render). Keep one loaded model per (folder, settings) for the life of the process:
    same model, same settings, same audio, so the same words and timings."""
    import faster_whisper
    if getattr(faster_whisper, '_adjob_cached', False):
        return
    real, loaded = faster_whisper.WhisperModel, {}

    def cached(*a, **k):
        key = repr((a, sorted(k.items())))
        if key not in loaded:
            t0 = time.monotonic()
            loaded[key] = real(*a, **k)
            _CALLS.append(['whisper', 'model load', round(time.monotonic() - t0, 2)])
        return loaded[key]
    faster_whisper.WhisperModel = cached
    faster_whisper._adjob_cached = True


_WHISPER_CACHE = None   # folder for remembered Whisper results; set for a real-footage render only (see main)


def _model_tag(folder):
    """What produced a remembered result: the model files and the library versions. Any change gives new cache keys."""
    import hashlib
    h = hashlib.sha256()
    for name in ('config.json', 'tokenizer.json', 'vocabulary.json', 'vocabulary.txt'):
        f = folder / name
        if f.is_file():
            h.update(name.encode() + f.read_bytes())
    weights = folder / 'model.bin'
    if weights.is_file():   # size plus the first and last 4 MB: a different model of the same size still gets new keys
        size = weights.stat().st_size
        h.update(str(size).encode())
        with weights.open('rb') as f:
            h.update(f.read(4 << 20))
            f.seek(max(0, size - (4 << 20)))
            h.update(f.read(4 << 20))
    adapter = pathlib.Path(__file__).resolve().parents[1] / 'cloud' / 'transcription.py'
    if adapter.is_file():   # the code that turns the model's output into the result the tools read
        h.update(adapter.read_bytes())
    for lib in ('faster_whisper', 'ctranslate2'):
        try:
            h.update(str(getattr(__import__(lib), '__version__', '?')).encode())
        except Exception:
            h.update(b'?')
    return h.hexdigest()


def _cached_transcribe(audio, opts, run, folder, tag):
    """Whisper on one audio file, remembered by (audio bytes, settings, model). rawedit times captions with one Whisper
    call per beat (43 calls, about 390 s of a 680 s render on 4 CPUs); a re-render whose voice did not change asks for
    exactly the same audio again, so it gets exactly the same words and timings back without running the model.
    A missing, unreadable or mismatched entry is simply computed again."""
    import hashlib
    h = hashlib.sha256(b'whisper-result-v1\0' + tag.encode() + b'\0' + json.dumps(opts, sort_keys=True, default=str).encode() + b'\0')
    h.update(pathlib.Path(audio).read_bytes())
    key = h.hexdigest()
    path = folder / f'{key}.json'
    try:
        saved = json.loads(path.read_text())
        if saved.get('key') == key and isinstance(saved.get('result'), dict):
            _CALLS.append(['whisper', 'remembered', 0.0])
            return saved['result']
    except (OSError, ValueError):
        pass
    result = run()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
        tmp.write_text(json.dumps({'key': key, 'result': result}, default=float))
        if json.loads(tmp.read_text())['result'] == result:   # only keep an entry that reads back exactly as computed
            os.replace(tmp, path)
        else:
            tmp.unlink()
    except Exception as error:   # remembering is optional; the render already has its result
        print('whisper result not remembered:', type(error).__name__, flush=True)
    return result


def _install_mlx_shim():
    state = {}

    def transcribe(audio, **kw):
        if str(WORK / 'cloud') not in sys.path:
            sys.path.insert(0, str(WORK / 'cloud'))
        from transcription import transcribe as tr
        settings = json.loads((WORK / 'cloud/whisper-settings.json').read_text())['faster']
        opts = dict(settings)
        if kw.get('initial_prompt'):
            opts['initial_prompt'] = kw['initial_prompt']
        try:
            _keep_whisper_model_loaded()
        except Exception as error:   # never a reason to fail: the call below then loads the model itself, as before
            print('whisper model not kept loaded:', type(error).__name__, flush=True)

        def run():
            t0 = time.monotonic()
            try:
                return tr(str(audio), backend='faster-whisper', model_path=WORK / '.ct2', **opts)
            finally:
                _CALLS.append(['whisper', pathlib.Path(str(audio)).name[:60], round(time.monotonic() - t0, 2)])
        if _WHISPER_CACHE is None:
            return run()
        try:
            if 'tag' not in state:
                state['tag'] = _model_tag(WORK / '.ct2')
            tag = state['tag']
        except Exception:
            return run()
        return _cached_transcribe(audio, opts, run, _WHISPER_CACHE, tag)
    sys.modules['mlx_whisper'] = types.SimpleNamespace(transcribe=transcribe)


def count_task(body):
    """Reserve one paid task slot job-wide; raise before the POST when the cap is reached."""
    cap = int(os.environ.get('ADJOB_MAX_TASKS', '0'))
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'tasks.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = STATE / 'tasks.jsonl'
        n = len(path.read_text().splitlines()) if path.exists() else 0
        if n >= cap:
            raise RuntimeError(f'ADJOB task cap reached ({n}/{cap}); refusing createTask')
        with path.open('a') as f:
            f.write(json.dumps({'at': time.time(), 'model': (body or {}).get('model'), 'pid': os.getpid()}) + '\n')
            f.flush()
            os.fsync(f.fileno())


def patch_kie(mod):
    original = mod._req
    httpx = mod.httpx

    def _req(method, url, **kw):
        if method.upper() != 'POST':
            return original(method, url, **kw)
        if url.endswith('/jobs/createTask'):
            count_task(kw.get('json'))
            r = httpx.request(method, url, headers=mod._h(), timeout=120, **kw)   # a paid task is asked for exactly once
            r.raise_for_status()
            return r.json()
        last = None
        for attempt in range(3):   # anything else (a reference upload) creates nothing paid: a network blip gets retried
            for part in (kw.get('files') or {}).values():   # an open file was read by the attempt before: start it again
                handle = part[1] if isinstance(part, (tuple, list)) else part
                if hasattr(handle, 'seek'):
                    handle.seek(0)
            try:
                r = httpx.request(method, url, headers=mod._h(), timeout=120, **kw)
                if r.status_code < 500 and r.status_code != 429:
                    r.raise_for_status()
                    return r.json()
                last = httpx.HTTPStatusError(f'{r.status_code} from {url}', request=r.request, response=r)
            except httpx.HTTPStatusError:
                raise
            except httpx.HTTPError as error:
                last = error
            time.sleep(4 * (attempt + 1))
        raise last
    mod._req = _req
    mod._adjob_patched = True


_SHOT_FILE = re.compile(r'(^|/)shot_\d+\.mp4$')


def patch_rawedit(mod):
    """Two cloud-only wrappers around rawedit.sh (the tool itself is unchanged): the 48 kHz / padded-voice loudnorm fix,
    and a stopwatch on every ffmpeg call, saved with the Whisper timings to <project>/.cloud/render-timing.json."""
    original = mod.sh
    calls, began = _CALLS, time.monotonic()
    proj = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None   # fixed now: the tool may change folder later

    def sh(*a, **k):
        a = [str(x) for x in a]
        if any('loudnorm' in x for x in a) and '-c:a' in a:
            a = [x.replace('[0:a]highpass', '[0:a]apad=pad_dur=0.6,highpass', 1) for x in a]
            i = a.index('-c:a'); a[i:i] = ['-ar', '48000']
        t0 = time.monotonic()
        try:
            return original(*a, **k)
        finally:
            if a and a[0] in ('ffmpeg', 'ffprobe'):
                calls.append([a[0], pathlib.Path(a[-1]).name[:60], round(time.monotonic() - t0, 2)])
    mod.sh = sh

    def save():
        if not calls or proj is None or not proj.is_dir():
            return
        try:
            groups = {}
            for tool, name, sec in calls:
                key = ('shots (SEGMENTS/shot_NN.mp4)' if _SHOT_FILE.search(name) else
                       'whisper (caption timing, one call per beat)' if tool == 'whisper' and name not in ('model load', 'remembered')
                       else f'{tool} {name}')
                groups[key] = round(groups.get(key, 0) + sec, 2)
            top = sorted(groups.items(), key=lambda kv: -kv[1])[:12]
            ran = [c for c in calls if c[0] == 'whisper' and c[1] not in ('model load', 'remembered')]
            out = {'command': sys.argv[2:3], 'wall_seconds': round(time.monotonic() - began, 1),
                   'ffmpeg_calls': sum(c[0] != 'whisper' for c in calls), 'in_ffmpeg_seconds': round(sum(c[2] for c in calls if c[0] != 'whisper'), 1),
                   'whisper_calls': len(ran), 'in_whisper_seconds': round(sum(c[2] for c in ran), 1),
                   'whisper_remembered': sum(c[1] == 'remembered' for c in calls if c[0] == 'whisper'),
                   'slowest': top, 'calls': calls[-400:]}
            (proj / '.cloud').mkdir(exist_ok=True)
            (proj / '.cloud' / 'render-timing.json').write_text(json.dumps(out, indent=1) + '\n')
            print('render timing: ' + ', '.join(f'{k} {v:.0f}s' for k, v in top[:5]) + f"; whisper ran {len(ran)}, remembered {out['whisper_remembered']}", flush=True)
        except Exception as error:   # the stopwatch must never fail a render
            print('render timing not saved:', type(error).__name__, flush=True)
    import atexit
    atexit.register(save)


class _KieFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name != 'kie':
            return None
        sys.meta_path.remove(self)
        try:
            spec = importlib.util.find_spec(name)
        finally:
            sys.meta_path.insert(0, self)
        if spec is None or spec.loader is None:
            return None
        loader = spec.loader

        class Loader(importlib.abc.Loader):
            def create_module(self, s):
                return loader.create_module(s)

            def exec_module(self, module):
                loader.exec_module(module)
                patch_kie(module)
        spec.loader = Loader()
        return spec


def main(argv):
    args = list(argv)
    while args and (args[0] in ('-I', '-u', '-B', '-E', '-s', '-S') or args[0].startswith('-W')):
        args.pop(0)
    _install_mlx_shim()
    sys.meta_path.insert(0, _KieFinder())
    if not args:
        raise SystemExit('adjob_boot: script required')
    if args[0] == '-c':
        sys.argv = ['-c'] + args[2:]
        exec(compile(args[1], '<string>', 'exec'), {'__name__': '__main__'})
    elif args[0] == '-m':
        sys.argv = [args[1]] + args[2:]
        runpy.run_module(args[1], run_name='__main__', alter_sys=True)
    else:
        script = pathlib.Path(args[0]).resolve()
        sys.argv = [str(script)] + args[1:]
        sys.path.insert(0, str(script.parent))
        if script.name == 'rawedit.py':   # same workaround as the Mac render48.py: 48 kHz mix, voice padded before loudnorm
            import rawedit
            patch_rawedit(rawedit)
            if len(args) > 1 and (pathlib.Path(args[1]) / 'plan.json').is_file():
                global _WHISPER_CACHE   # kept with the project's intermediates: saved to the Volume, never sent to the Mac
                _WHISPER_CACHE = pathlib.Path(args[1]).resolve() / 'SEGMENTS' / '_whisper'
            rawedit.main()
        else:
            runpy.run_path(str(script), run_name='__main__')


if __name__ == '__main__':
    main(sys.argv[1:])
