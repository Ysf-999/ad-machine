from __future__ import annotations
from hygiene import guarded_run,require_space,clone_file,finish_result
import dataclasses, hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile, time

SAFE = {'ad': {'status', 'rules', 'stitch', 'realign'},
        'rawedit': {'status', 'fcpxml', 'plan', 'captions', 'render'},
        'preflight': {'check'}, 'caption_sync_check': {'check'}, 'av_check': {'check'}, 'audio_check': {'check'}}

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest()

def relative(name):
    p = pathlib.PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or not p.parts or '.env' in p.parts:
        raise ValueError(f'Unsafe manifest path: {name}')
    return p

@dataclasses.dataclass
class Manifest:
    tool: str
    stage: str
    project_inputs: list[str]
    root_inputs: list[str] = dataclasses.field(default_factory=list)
    outputs: list[str] = dataclasses.field(default_factory=lambda: ['plan.json', 'jobs.jsonl'])
    args: list[str] = dataclasses.field(default_factory=list)
    timeout: int = 600
    model_cache: str | None = None
    fonts_dir: str | None = None

    def validate(self):
        if self.stage not in SAFE.get(self.tool, set()):
            raise ValueError('Stage not enabled: paid, upload, review/open, and unverified stages fail closed')
        if self.model_cache and self.model_cache != 'models--mlx-community--whisper-large-v3-turbo':
            raise ValueError('Only the audited Whisper model cache is enabled')
        if self.fonts_dir is not None and (self.fonts_dir!='library/fonts' or 'library/fonts' not in self.root_inputs):raise ValueError('Bundled font mode needs exact declared library/fonts input')
        if self.args: raise ValueError('Arbitrary tool arguments disabled until audited')
        if 'plan.json' not in self.project_inputs: raise ValueError('Declare plan.json')
        for p in self.project_inputs + self.root_inputs + self.outputs: relative(p)
        for p in self.root_inputs:
            if pathlib.PurePosixPath(p).parts[0] not in {'footage', 'library', 'feedback', 'product-kit', 'knowledge'}:
                raise ValueError('Unsupported root input')

def _copy(root, dest, names):
    records = {}
    root = root.resolve()
    for name in names:
        p = root / relative(name)
        if not p.exists(): raise FileNotFoundError(p)
        files = sorted(p.rglob('*')) if p.is_dir() else [p]
        for f in files:
            if f.is_dir(): continue
            if f.is_symlink() or not f.resolve().is_relative_to(root): raise ValueError('Input symlink/escape refused')
            rel = f.relative_to(root)
            if '.env' in rel.parts or '.git' in rel.parts: raise ValueError('Secret/repository input refused')
            to = dest / rel; to.parent.mkdir(parents=True, exist_ok=True)
            clone_file(f, to); records[str(rel)] = digest(to)
    return records

def _sandbox(work, root, *, deny_system_fonts=False):
    from worker.isolation import select_backend,probe,MacSeatbelt
    backend=select_backend(sys.platform,probe(sys.platform))
    if not isinstance(backend,MacSeatbelt):
        raise RuntimeError('Linux requires a verified Runtime manifest and full execution plan')
    return backend.prefix(work,root,deny_system_fonts=deny_system_fonts)

def _run_stage(root, project, manifest: Manifest, result_dir):
    """Return output bundle and optimistic plan patch; NEVER write back into source projects.

    Runtime is the pinned host venv + OS libraries/fonts. All tools are copied. Network and
    original data reads are denied by Seatbelt, not just hidden by changing cwd.
    """
    manifest.validate(); root = pathlib.Path(root).resolve(); project = pathlib.Path(project).resolve()
    if not project.is_relative_to(root): raise ValueError('Stage source must be under the audited root')
    plan = json.loads((project / 'plan.json').read_text())
    if plan.get('locked'): raise ValueError('LOCKED: all cloud work refuses locked inputs')
    result = pathlib.Path(result_dir).resolve()
    if not result.is_relative_to(root / 'cloud/.scratch'): raise ValueError('Build outputs must remain under cloud/.scratch/')
    if result.is_relative_to(root / 'projects') or result.is_relative_to(project):
        raise ValueError('Output must be separate from source project')
    if result.exists(): raise FileExistsError('Result bundles are immutable; choose a new path')
    result.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='stage-', dir=root / 'cloud' / '.scratch') as td:
        work = pathlib.Path(td).resolve(); wp = work / 'projects' / project.name; wp.mkdir(parents=True)
        model_hashes = {}
        if manifest.model_cache:
            cache = pathlib.Path.home() / '.cache/huggingface/hub'
            source = cache / manifest.model_cache
            for f in sorted(source.rglob('*')):
                if not f.is_file(): continue
                if not f.resolve().is_relative_to(cache.resolve()): raise ValueError('Model cache symlink escapes cache')
                target = work / '.models' / manifest.model_cache / f.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True); clone_file(f.resolve(), target)
                model_hashes[str(target.relative_to(work))] = digest(target)
        src_hashes = _copy(project, wp, manifest.project_inputs)
        root_hashes = _copy(root, work, manifest.root_inputs)
        (work / 'tools').mkdir()
        tools = {}
        for f in sorted((root / 'tools').glob('*.py')):
            clone_file(f, work / 'tools' / f.name); tools[f.name] = digest(f)
        # Additive backend runtime imported lazily by the permitted tool hooks.
        if (root / 'cloud/llm.py').exists():
            (work / 'cloud').mkdir(); clone_file(root / 'cloud/llm.py', work / 'cloud/llm.py')
            tools['../cloud/llm.py'] = digest(root / 'cloud/llm.py')
        # Runtime-only mount, explicitly not the original project's data.
        (work / '.venv').symlink_to(root / '.venv', target_is_directory=True)
        (work / 'bin').mkdir(); (work / 'home').mkdir(); (work / 'tmp').mkdir()
        bins = list((root / '.venv').glob('lib/python*/site-packages/static_ffmpeg/bin/darwin_arm64'))
        if not bins: raise RuntimeError('Pinned static ffmpeg unavailable')
        for name in ['ffmpeg', 'ffprobe']: (work / 'bin' / name).symlink_to(bins[0] / name)
        env = {'PATH': str(work / 'bin') + ':/usr/bin:/bin', 'HOME': str(work / 'home'), 'TMPDIR': str(work / 'tmp'),
               'FFMPEG_NO_GATE': '1', 'CLAUDE_BACKEND': 'skip', 'MOMENTS_BACKEND': 'skip',
               'HF_HUB_CACHE': str(work / '.models'), 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'LANG': 'en_US.UTF-8'}
        if manifest.fonts_dir:
            from worker.fonts import configuration
            env.update(configuration(work/manifest.fonts_dir,work/'fontconfig'))
        cmd = [str(work / '.venv/bin/python'), '-I', str(work / 'tools' / (manifest.tool + '.py'))]
        if manifest.tool in {'ad', 'rawedit'}: cmd += [str(wp), manifest.stage]
        elif manifest.tool == 'av_check': cmd += ['--check', str(wp / 'MASTER.mp4')]
        elif manifest.tool == 'audio_check': cmd += [str(wp / 'MASTER.mp4')]
        else: cmd += [str(wp)]
        started = time.monotonic()
        proc = guarded_run(_sandbox(work, root,deny_system_fonts=bool(manifest.fonts_dir)) + cmd, cwd=work, env=env, capture_output=True, text=True, timeout=manifest.timeout)
        text = proc.stdout + '\n' + proc.stderr
        if proc.returncode == 0 and manifest.tool == 'rawedit' and manifest.stage in {'render', 'captions'}:
            gate = guarded_run(_sandbox(work, root,deny_system_fonts=bool(manifest.fonts_dir)) + [str(work / '.venv/bin/python'), '-I', str(work / 'tools/caption_sync_check.py'), str(wp)], cwd=work, env=env, capture_output=True, text=True, timeout=manifest.timeout)
            text += '\n' + gate.stdout + '\n' + gate.stderr
        elapsed = time.monotonic() - started
        (result / 'stage.log').write_text(text.replace(str(work), '<workspace>'))
        newplan = json.loads((wp / 'plan.json').read_text())
        patch = {'base_sha256': src_hashes['plan.json'], 'set': {k:v for k,v in newplan.items() if plan.get(k) != v},
                 'remove': [k for k in plan if k not in newplan]}
        before_jobs = (project / 'jobs.jsonl').read_text() if 'jobs.jsonl' in manifest.project_inputs else ''
        after_jobs = (wp / 'jobs.jsonl').read_text() if (wp / 'jobs.jsonl').exists() else ''
        if not after_jobs.startswith(before_jobs): raise RuntimeError('jobs.jsonl was rewritten: append-only patch refused')
        (result / 'plan.patch.json').write_text(json.dumps(patch, indent=2))
        (result / 'jobs.append.jsonl').write_text(after_jobs[len(before_jobs):])
        (result / 'outputs').mkdir()
        collected = _copy(wp, result / 'outputs', [p for p in manifest.outputs if (wp / p).exists()])
        # ad.stitch ignores the caption checker return code, so stage exit 0 is insufficient.
        passed = proc.returncode == 0
        gates = {}
        if manifest.stage in {'stitch', 'render', 'captions'} or manifest.tool == 'caption_sync_check':
            gates['caption_sync'] = 'passed' if 'CAPTION SYNC PASS' in text and 'SYNC FAIL' not in text else 'not_passed'
            passed = passed and gates['caption_sync'] == 'passed'
        report = {'tool': manifest.tool, 'stage': manifest.stage, 'status': 'done' if passed else 'failed',
                  'returncode': proc.returncode, 'wall_seconds': elapsed, 'gates': gates,
                  'deliverable': False, 'isolation': 'macOS Seatbelt: no network/source data read; writes workspace only (plus /dev/null)',
                  'runtime': 'host .venv + system libraries/fonts; not Linux parity', 'inputs': src_hashes,
                  'root_inputs': root_hashes, 'model_inputs': model_hashes, 'tools': tools, 'outputs': collected}
        (result / 'result.json').write_text(json.dumps(report, indent=2)); return report


def run_stage(root, project, manifest: Manifest, result_dir, *, keep=False):
    """Disk guard before allocation; retain media only on explicit successful keep."""
    require_space()
    result = pathlib.Path(result_dir).resolve()
    if not result.is_relative_to(pathlib.Path(root).resolve() / 'cloud/.scratch'):
        raise ValueError('Scratch result directory required')
    if result.exists(): raise FileExistsError('Immutable result directory required')
    try:
        report = _run_stage(root, project, manifest, result)
    except BaseException as exc:
        if result.exists():
            (result/'result.json').write_text(json.dumps({'status':'failed','error':type(exc).__name__,'deliverable':False}))
            finish_result(result,success=False)
        raise
    report['outputs_retained'] = bool(keep and report['status']=='done')
    (result/'result.json').write_text(json.dumps(report,indent=2))
    finish_result(result,success=report['status']=='done',keep=keep)
    return report
