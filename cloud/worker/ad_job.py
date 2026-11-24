"""Remote side of a cloud ad job: run unchanged tools/ad.py stages on one project, persist it to the Volume.

run(job) is called inside a Modal function. job = {ad, stages:[...], max_tasks, timeout_s}. Layout:
  /code           read-only code snapshot (tools/*.py, feedback/, library/{fonts,sfx,index.json}, cloud/{transcription.py,
                  whisper-settings.json}, worker/adjob_boot.py) mounted by the driver, OR (controller runs,
                  job['code'] = version) the same snapshot at /vol/adjobs/_code/<version>/
  /vol/adjobs/<ad> the project folder (plan.json, VO/, FRAMES/, CLIPS/, jobs.jsonl ...), read at start, written back + committed
  /vol/adjobs/_store/<ROOT-relative path>  shared clip store: footage, music, transcripts uploaded once and reused by every ad;
                  the project's assets.json lists the paths this ad needs (older runs: /vol/adjobs/_assets/<ad>/)
  /model          read-only CT2 whisper model (hash-verified copy into <work>/.ct2)
Secrets arrive only as env vars of the function that needs them; logs are redacted before they leave the container.
Returns a small JSON receipt (<64 KB); full logs are written to /vol/adjobs/<ad>/.cloud/<run>.log.

Paid kie stages are crash-safe: while one runs, a checkpoint thread saves jobs.jsonl (every kie task id), every finished
file those records name and the run's task counter to the Volume, so a container that dies mid-stage loses no kie work
that was paid for. (The ElevenLabs voice is one short step of its own and is saved when that step ends; a worker that
dies inside that step loses that one voice take.) The next run of the ad polls the saved task ids instead of creating new tasks.
"""
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time

MODEL_SHA = {
    'README.md': 'aaef74a740faca90fa1899c4233ebe17f2093b9846d0acf16d9131bf650e9585',
    'config.json': 'b0253ea6c0d3bea6b1e19e91a02acfd3b53f4467362efcb5a3e6b16c9b3a9b7e',
    'generation_config.json': 'cce11bfe3aaa6ae9e072ea2637caaec8795e68d9b67e655a5af16ee509681a4c',
    'model.bin': 'e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da',
    'preprocessor_config.json': '7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711',
    'tokenizer.json': '297b13372ac43916285644fb9687add3cc62ee2a1adb60da3dc25cc94c1871fd',
    'vocabulary.json': 'c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1',
}
STAGES = {'status', 'plan_review', 'vo', 'frames', 'clips', 'qc', 'stitch', 'masterqc', 'check', 'rawrender', 'padtail', 'rawverify',
          'shotcheck', 'redo', 'preflight'}
WORK = pathlib.Path('/tmp/adjob/work')   # the container's working copy (one ad per container)
MEDIA_CHECKS = '.cloud/media-checks.json'   # tools/preflight.py --media-json: the video-only final checks, with the file's fingerprint
GATE_BLOCKED = 3   # shot_check.py exit code: un-acknowledged issues, do not render
# The repo folder on the Mac (plan.json files name absolute Mac paths). cloud/ctl.py writes it into the code snapshot.
_ROOT_FILE = pathlib.Path(__file__).resolve().with_name('mac_root.txt')
MAC_ROOT = (_ROOT_FILE.read_text().strip() if _ROOT_FILE.is_file() else '') or os.environ.get('ADMACHINE_MAC_ROOT', '')
SECRET_KEY = re.compile(r'KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH', re.I)


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def redactor():
    secrets = sorted({v for k, v in os.environ.items() if v and len(v) >= 8 and SECRET_KEY.search(k)}, key=len, reverse=True)

    def safe(text):
        for v in secrets:
            text = text.replace(v, '[REDACTED]')
        return text
    return safe


def validate(job):
    ad = job.get('ad')
    if not isinstance(ad, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,80}', ad):
        raise ValueError('Safe ad name required')
    stages = job.get('stages')
    if not isinstance(stages, list) or not stages or any(s not in STAGES for s in stages):
        raise ValueError('Known stages only: ' + ', '.join(sorted(STAGES)))
    if type(job.get('max_tasks', 0)) is not int or not 0 <= job.get('max_tasks', 0) <= 80:
        raise ValueError('max_tasks must be an int 0..80')
    if job.get('code') is not None and not re.fullmatch(r'[0-9a-f]{12,64}', str(job['code'])):
        raise ValueError('code version must be a hex digest')
    if job.get('run') is not None and not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,120}', str(job['run'])):
        raise ValueError('run id must be a safe name')
    if job.get('qc_stage') not in (None, 'frames', 'clips', 'all'):
        raise ValueError('qc_stage must be frames, clips or all')
    if job.get('advisory') and not set(stages) <= {'rawverify', 'preflight'}:
        raise ValueError('only the final checks can be advisory')
    if type(job.get('timeout_s', 1500)) is not int or not 60 <= job.get('timeout_s', 1500) <= 3400:
        raise ValueError('timeout_s must be an int 60..3400')
    redos = job.get('redos', [])
    if 'redo' in stages and not redos:
        raise ValueError('redo stage needs redos')
    for r in redos:
        if (not isinstance(r, list) or len(r) != 3 or type(r[0]) is not int or not 1 <= r[0] <= 99 or r[1] not in ('frame', 'clip')
                or not isinstance(r[2], str) or len(r[2]) > 600 or '\x00' in r[2]):
            raise ValueError('redos must be [[beat, "frame"|"clip", "note"], ...]')
    return ad, stages


def copy_assets(work, src, vol=pathlib.Path('/vol/adjobs')):
    """Copy only the files this ad references from the shared store (assets.json); fall back to the old per-ad folder."""
    listing = src / 'assets.json'
    if listing.is_file():
        root = (vol / '_store').resolve()
        for rel in json.loads(listing.read_text()):
            f = (root / rel).resolve()
            if not str(f).startswith(str(root) + os.sep) or not f.is_file():
                raise FileNotFoundError(f'asset missing from the shared store: {rel}')
            out = work / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, out)
        return 'store'
    old = vol / '_assets' / src.name
    if old.is_dir():
        shutil.copytree(old, work, symlinks=False, dirs_exist_ok=True)
        return 'legacy'
    return 'none'


def recover(dst):
    """A worker that died in the middle of persist() can leave the project folder missing, with the new copy in
    <ad>.incoming (complete: the swap only starts after the copy) or the old one in <ad>.previous. Put it back."""
    if (dst / 'plan.json').is_file():
        return None
    for suffix in ('.incoming', '.previous'):
        cand = dst.with_name(dst.name + suffix)
        if (cand / 'plan.json').is_file() and (suffix == '.previous' or (cand / MANIFEST).is_file()):
            if dst.exists():
                shutil.rmtree(dst)
            cand.rename(dst)
            return suffix
    return None


def setup(work, ad, need_model, code='/code'):
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(code, work, symlinks=False)
    src = pathlib.Path('/vol/adjobs') / ad
    recover(src)
    if not (src / 'plan.json').is_file():
        raise FileNotFoundError(f'project {ad} not on the Volume')
    plan = json.loads((src / 'plan.json').read_text())
    if plan.get('locked'):
        raise PermissionError('LOCKED project refused')
    shutil.copytree(src, work / 'projects' / ad, symlinks=False)
    copy_assets(work, src)                                       # footage/music/transcripts this project references (ROOT-relative)
    pj = work / 'projects' / ad / 'plan.json'                    # Mac absolute paths -> container paths (reversed on persist)
    if MAC_ROOT:
        pj.write_text(pj.read_text().replace(MAC_ROOT, str(work)))
    if need_model:
        (work / '.ct2').mkdir()
        for name, digest in MODEL_SHA.items():
            shutil.copyfile(pathlib.Path('/model') / name, work / '.ct2' / name)
            if sha(work / '.ct2' / name) != digest:
                raise ValueError('GLOBAL_HASH_MISMATCH model ' + name)
    for d in ('home', 'tmp', '.venv/bin', 'bin', '.adjob'):
        (work / d).mkdir(parents=True, exist_ok=True)
    from xml.sax.saxutils import escape
    (work / 'fonts.conf').write_text('<fontconfig><dir>' + escape(str(work / 'library/fonts')) + '</dir><cachedir>'
                                     + escape(str(work / 'tmp/fc-cache')) + '</cachedir></fontconfig>')
    wrapper = work / '.venv/bin/python'
    wrapper.write_text(f'#!/bin/sh\nexec {sys.executable} {work}/worker/adjob_boot.py "$@"\n')
    wrapper.chmod(0o755)
    import importlib.util
    spec = importlib.util.find_spec('claude_agent_sdk')
    if spec:
        cli = pathlib.Path(spec.origin).parent / '_bundled' / 'claude'
        if cli.exists():
            (work / 'bin' / 'claude').symlink_to(cli)


def env_for(work, max_tasks):
    keep = {k: v for k, v in os.environ.items() if k in ('KIE_API_KEY', 'ELEVENLABS_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'LANG')}
    keep.update(PATH=f'{work}/bin:/opt/ffmpeg/bin:/usr/local/bin:/usr/bin:/bin', HOME=str(work / 'home'), TMPDIR=str(work / 'tmp'),
                ADJOB_WORK=str(work), ADJOB_MAX_TASKS=str(max_tasks), FFMPEG_NO_GATE='1', OMP_NUM_THREADS='4',
                HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', PYTHONDONTWRITEBYTECODE='1',
                FONTCONFIG_FILE=str(work / 'fonts.conf'), CLAUDE_BACKEND='cli', MOMENTS_BACKEND='cli', LANG=keep.get('LANG', 'C.UTF-8'),
                DISABLE_TELEMETRY='1', DISABLE_AUTOUPDATER='1', CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1')
    return keep


def credits(project):
    total, jobs = 0.0, 0
    p = project / 'jobs.jsonl'
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get('state') == 'success' and d.get('creditsConsumed') is not None:
                total += float(d['creditsConsumed']); jobs += 1
    return round(total, 2), jobs


def padtail(project):
    """Re-mux MASTER audio padded to the picture length (rawedit's loudnorm drops ~0.15 s of decoded audio at the end)."""
    m = project / 'MASTER.mp4'
    dur = float(subprocess.run(['/opt/ffmpeg/bin/ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=duration', '-of', 'csv=p=0', str(m)],
                               capture_output=True, text=True, check=True).stdout.strip())
    wav, out = project / '.cloud' / 'tail.wav', project / '.cloud' / 'MASTER.padded.mp4'
    wav.parent.mkdir(exist_ok=True)
    subprocess.run(['/opt/ffmpeg/bin/ffmpeg', '-v', 'error', '-y', '-i', str(m), '-vn', '-af', f'aresample=48000,afade=t=out:st={dur - 0.12:.3f}:d=0.1', '-ac', '2', '-f', 'wav', str(wav)], check=True)
    subprocess.run(['/opt/ffmpeg/bin/ffmpeg', '-v', 'error', '-y', '-i', str(m), '-i', str(wav), '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-af', f'apad=whole_dur={dur:.3f}',
                    '-c:a', 'aac', '-b:a', '192k', str(out)], check=True)
    os.replace(out, m); wav.unlink()
    return f'MASTER audio padded to {dur:.3f}s'


MANIFEST = 'MANIFEST.sha256.json'


def write_manifest(project):
    """sha256 of every finished file (not SEGMENTS/CUT* intermediates) so the Mac pull can prove each download is intact."""
    import hashlib
    out = {}
    for f in sorted(project.rglob('*')):
        rel = f.relative_to(project).as_posix()
        if not f.is_file() or rel == MANIFEST or rel.startswith(('SEGMENTS/', 'CUT')) or rel.endswith('.dl'):
            continue
        h = hashlib.sha256()
        with f.open('rb') as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b''):
                h.update(chunk)
        out[rel] = {'sha256': h.hexdigest(), 'size': f.stat().st_size}
    (project / MANIFEST).write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    return out


def persist(work, ad, commit):
    src, dst = work / 'projects' / ad, pathlib.Path('/vol/adjobs') / ad
    pj = src / 'plan.json'
    if MAC_ROOT:
        pj.write_text(pj.read_text().replace(str(work), MAC_ROOT))
    write_manifest(src)
    tmp = dst.with_name(ad + '.incoming')
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(src, tmp, symlinks=False)
    old = dst.with_name(ad + '.previous')
    if old.exists():
        shutil.rmtree(old)
    if dst.exists():
        dst.rename(old)
    tmp.rename(dst)
    shutil.rmtree(old, ignore_errors=True)
    os.sync()
    if commit:
        commit()


def task_file(project, run):
    """The run's paid-task counter, kept inside the project so it survives across the steps and retries of one run."""
    return project / '.cloud' / f'tasks-{run}.jsonl'


def checkpoint(work, ad, commit, run=None, vol=pathlib.Path('/vol/adjobs')):
    """Save what has been paid for so far: every finished file the generation records name, then jobs.jsonl itself (in
    that order, so a saved 'success' line always has its file), then the task counter. Entries are added to the
    Volume's manifest so the Mac can pull them even when this container never reaches persist()."""
    src, dst = work / 'projects' / ad, vol / ad
    jobs = src / 'jobs.jsonl'
    if not jobs.is_file() or not dst.is_dir():
        return 0
    text = jobs.read_bytes()
    mpath = dst / MANIFEST
    manifest = json.loads(mpath.read_text()) if mpath.is_file() else {}
    todo = []
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        for f in (d.get('files') or []) if d.get('state') == 'success' else []:
            try:
                rel = pathlib.Path(f).resolve().relative_to(src.resolve())
            except ValueError:
                continue
            todo.append(rel)
    todo.append(pathlib.Path('jobs.jsonl'))
    counter = work / '.adjob/tasks.jsonl'
    if run and counter.is_file():
        task_file(src, run).parent.mkdir(exist_ok=True)
        shutil.copyfile(counter, task_file(src, run))
        todo.append(task_file(src, run).relative_to(src))
    n = 0
    for rel in todo:
        a, b = src / rel, dst / rel
        if not a.is_file():
            continue
        data = text if rel.name == 'jobs.jsonl' else None
        size = len(data) if data is not None else a.stat().st_size
        known = manifest.get(rel.as_posix())
        if known and known['size'] == size and b.is_file() and (data is None or hashlib.sha256(data).hexdigest() == known['sha256']):
            continue
        b.parent.mkdir(parents=True, exist_ok=True)
        tmp = b.with_name(b.name + '.ckpt')
        if data is not None:
            tmp.write_bytes(data)
        else:
            shutil.copyfile(a, tmp)
        manifest[rel.as_posix()] = {'sha256': sha(tmp), 'size': tmp.stat().st_size}
        os.replace(tmp, b)
        n += 1
    if n:
        tmp = mpath.with_name(MANIFEST + '.ckpt')
        tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
        os.replace(tmp, mpath)
        os.sync()
        if commit:
            commit()
    return n


class contextlib_null:
    """Stand-in when no checkpoints are needed (unpaid stages, or a local test without a commit function)."""
    saved = errors = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Checkpointer:
    """Runs checkpoint() whenever jobs.jsonl or the task counter changed (looked at every 2 s) while a paid stage runs."""
    def __init__(self, work, ad, commit, run):
        self.args, self.stop, self.saved, self.errors = (work, ad, commit, run), threading.Event(), 0, 0
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def stamp(self):
        work, ad = self.args[0], self.args[1]
        out = []
        for f in (work / 'projects' / ad / 'jobs.jsonl', work / '.adjob/tasks.jsonl'):
            out.append((f.stat().st_size, f.stat().st_mtime_ns) if f.exists() else None)
        return out

    def loop(self):
        last = self.stamp()
        while not self.stop.wait(2):
            now = self.stamp()
            if now != last:
                try:
                    self.saved += checkpoint(*self.args)
                    last = now
                except Exception:
                    self.errors += 1   # a checkpoint must never break the paid run; persist() still saves at the end

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(timeout=120)


def beat_gaps(project, stage):
    """Beats the stage should have produced but did not (a provider task that failed costs nothing and leaves a hole)."""
    plan = json.loads((project / 'plan.json').read_text())
    folder, stem, ext = (project / 'FRAMES', 'scene', '.png') if stage == 'frames' else (project / 'CLIPS', 'clip', '.mp4')
    gaps = []
    for b in plan.get('beats', []):
        name = f"{stem}_{b['n']:02d}"
        if not any(re.fullmatch(rf'{name}(_v\d+)?', p.stem) for p in folder.glob(f'{name}*{ext}')):
            gaps.append(b['n'])
    return gaps


NOT_DELIVERED = re.compile(r'^(FAIL|PENDING) \S+|^NOT DONE: ', re.M)


def run(job, commit=None):
    ad, stages = validate(job)
    safe = redactor()
    work = WORK
    t0 = time.monotonic()
    code = f"/vol/adjobs/_code/{job['code']}" if job.get('code') else '/code'
    setup(work, ad, need_model=bool(set(stages) & {'vo', 'qc', 'stitch', 'check', 'rawrender', 'rawverify', 'preflight'}), code=code)
    env = env_for(work, job.get('max_tasks', 0))
    project = work / 'projects' / ad
    py = str(work / '.venv/bin/python')
    deadline = time.monotonic() + job.get('timeout_s', 1500)   # for ALL stages of this call, so it ends in time to save
    run_id = job.get('run')
    counter = work / '.adjob/tasks.jsonl'
    if run_id and task_file(project, run_id).is_file():   # an earlier step or attempt of this run: its paid tasks still count
        shutil.copyfile(task_file(project, run_id), counter)
    tasks_before = len(counter.read_text().splitlines()) if counter.exists() else 0
    receipt = {'ad': ad, 'stages': [], 'approved': False, 'deliverable': False}
    log_lines = []
    before = credits(project)

    def one(cmd, label):
        began = time.monotonic()
        # own process group: on a timeout every child (ad.py starts batch.py, gen_scenes.py ...) is stopped with it,
        # so nothing keeps writing into the project while it is being saved
        proc = subprocess.Popen(cmd, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        try:
            out, _ = proc.communicate(timeout=max(20, deadline - time.monotonic()))
            out, rc = safe(out or ''), proc.returncode
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, 9)
            except OSError:
                pass
            out, _ = proc.communicate()
            out, rc = safe((out or '') + '\nTIMEOUT'), -9
        log_lines.append(f'===== {label} rc={rc} {time.monotonic() - began:.1f}s\n{out}')
        return out, rc, round(time.monotonic() - began, 1)

    paid = bool(set(stages) & {'vo', 'frames', 'clips', 'redo'})
    with Checkpointer(work, ad, commit, run_id) if paid and commit else contextlib_null() as saver:
        for stage in stages:
            if stage == 'plan_review':
                cmd = [py, '-I', 'tools/plan_review.py', f'projects/{ad}']
            elif stage == 'check':
                cmd = [py, '-I', 'worker/adjob_check.py', ad]
            elif stage == 'rawrender':
                plan = json.loads((project / 'plan.json').read_text())
                cmd = [py, '-I', 'tools/rawedit.py', f'projects/{ad}', 'render', *plan.get('render_args', [])]
            elif stage == 'rawverify':
                cmd = [py, '-I', 'tools/rawedit.py', f'projects/{ad}', 'verify']
            elif stage == 'preflight':   # the video-only final checks, as data; PREFLIGHT.md stays the Mac's file
                (project / MEDIA_CHECKS).unlink(missing_ok=True)
                cmd = [py, '-I', 'tools/preflight.py', f'projects/{ad}', '--media-json', f'projects/{ad}/{MEDIA_CHECKS}']
            elif stage == 'shotcheck':
                cmd = [py, '-I', 'tools/shot_check.py', f'projects/{ad}']
            elif stage == 'qc' and job.get('qc_stage'):
                cmd = [py, '-I', 'tools/ad.py', f'projects/{ad}', 'qc', '--stage', job['qc_stage']]
            elif stage == 'redo':   # owner revisions on an AI ad: one ad.py redo per [beat, frame|clip, note], in order
                began, out, rc, missed, finished = time.monotonic(), '', 0, [], []
                for beat, what, note in job['redos']:
                    text, rc, _ = one([py, '-I', 'tools/ad.py', f'projects/{ad}', 'redo', str(beat), what] + ([note] if note else []),
                                      f'redo {beat} {what}')
                    out += f'--- redo {beat} {what}\n' + text
                    if rc == 0 and NOT_DELIVERED.search(text):   # the provider returned nothing for this redo (not charged)
                        missed.append(f'{beat}:{what}')
                    elif rc == 0:
                        finished.append([beat, what])   # made and saved: sending it again would make (and bill) a new version
                    if rc:
                        break
                receipt['redos_done'] = finished
                if missed and not rc:
                    rc = 1; receipt['not_done'] = missed
                    out += f'\nNOT DELIVERED by the provider (no charge): {missed}'
                receipt['stages'].append({'stage': 'redo', 'returncode': rc, 'seconds': round(time.monotonic() - began, 1), 'tail': out[-1500:]})
                if rc:
                    break
                continue
            elif stage == 'padtail':
                began = time.monotonic()
                try:
                    msg, rc = padtail(project), 0
                except Exception as e:
                    msg, rc = safe(f'{type(e).__name__}: {e}'), 1
                log_lines.append(f'===== padtail rc={rc}\n{msg}')
                receipt['stages'].append({'stage': 'padtail', 'returncode': rc, 'seconds': round(time.monotonic() - began, 1), 'tail': msg})
                if rc:
                    break
                continue
            else:
                cmd = [py, '-I', 'tools/ad.py', f'projects/{ad}', stage]
            out, rc, seconds = one(cmd, stage)
            if rc == 0 and stage in ('frames', 'clips'):
                gaps = beat_gaps(project, stage)
                if gaps:   # failed provider tasks are not charged: one more pass makes only the missing beats
                    more, rc, extra = one(cmd, f'{stage} (second pass for beats {gaps})')
                    out, seconds = out + more, seconds + extra
                    gaps = beat_gaps(project, stage) if rc == 0 else gaps
                if gaps and rc == 0:
                    rc = 1; receipt['not_done'] = [f'{n}:{stage[:-1]}' for n in gaps]
                    out += f'\nNOT DELIVERED after two passes (no charge for failed tasks): beats {gaps}'
            if job.get('advisory'):   # a final check: say what it found, never fail the step (the video is already made)
                found = {'returncode': rc, 'seconds': seconds, 'tail': out[-900:]}
                if stage == 'preflight':
                    try:
                        data = json.loads((project / MEDIA_CHECKS).read_text())
                        found.update(fingerprint=data.get('fingerprint'), lines=len(data.get('lines') or []),
                                     fails=[str(x)[:200] for x in data.get('lines') or [] if str(x).startswith('FAIL')][:12])
                    except (OSError, ValueError):
                        found['fingerprint'] = None   # the check did not finish: nothing to carry over
                receipt.setdefault('checks', {})[stage] = found
                receipt['stages'].append({'stage': stage, 'returncode': 0, 'check_returncode': rc, 'seconds': seconds, 'tail': out[-1500:]})
                continue
            receipt['stages'].append({'stage': stage, 'returncode': rc, 'seconds': seconds, 'tail': out[-1500:]})
            if stage == 'shotcheck' and rc == GATE_BLOCKED:
                receipt['gate'] = 'blocked'   # not a crash: the check found shots to fix (or acknowledge) before rendering
            if rc != 0:
                break
    after = credits(project)
    if run_id and counter.exists():
        task_file(project, run_id).parent.mkdir(exist_ok=True)
        shutil.copyfile(counter, task_file(project, run_id))
    receipt.update(kie_credits_consumed_this_run=round(after[0] - before[0], 2), kie_success_jobs_this_run=after[1] - before[1],
                   kie_create_tasks_this_run=(len(counter.read_text().splitlines()) if counter.exists() else 0) - tasks_before,
                   checkpoints=getattr(saver, 'saved', 0), checkpoint_errors=getattr(saver, 'errors', 0),
                   files=sorted(str(p.relative_to(project)) for p in project.rglob('*') if p.is_file() and p.stat().st_size < 400_000_000)[:300],
                   wall_seconds=round(time.monotonic() - t0, 1))
    logdir = project / '.cloud'
    logdir.mkdir(exist_ok=True)
    name = time.strftime('%Y%m%d-%H%M%S') + '-' + '-'.join(stages) + '.log'
    (logdir / name).write_text('\n'.join(log_lines))
    receipt['log'] = f'.cloud/{name}'
    persist(work, ad, commit)
    text = json.dumps(receipt)
    while len(text.encode()) > 60_000 and (any(s['tail'] for s in receipt['stages']) or receipt.get('files')):
        receipt['files'] = receipt['files'][:len(receipt['files']) // 2]
        for s in receipt['stages']:
            s['tail'] = s['tail'][len(s['tail']) // 2:]
        text = json.dumps(receipt)
    return text
