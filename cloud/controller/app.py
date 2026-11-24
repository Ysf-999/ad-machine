"""Deployed Modal app `<app_prefix>-ads`: the always-on cloud side of the ad controller (names: cloud/names.py).

Deploy (once, and again only when this file changes; the pipeline code itself travels to the Volume on every submit,
see cloud/ctl.py). From the repo root:
  .modal-env/bin/python cloud/ctl.py deploy        (same as: cd cloud && modal deploy controller/app.py)
The first deploy builds the worker image (Debian + Python 3.12 + pinned faster-whisper stack + static ffmpeg 7.0.2 +
httpx + claude-agent-sdk, which bundles the `claude` CLI); later deploys reuse it from Modal's cache.
Functions (all scale to zero; nothing runs or bills while idle):
  run_plain   4 CPU / 8 GiB, 45 min, no secret, network blocked   render + pad + offline check + final checks  up to 16 at once
  run_gen     2 CPU / 4 GiB, 60 min, kie + ElevenLabs secret      voiceover, stills, clips, redos    up to 10 at once
  run_claude  2 CPU / 4 GiB, 45 min, Claude login token           shot check, plan review, QC, stitch up to 10 at once
  pipeline    tiny, 6 h, no secret                                runs one ad's recipe steps in order, writes status
  admin       tiny, no secret                                     one-off Volume housekeeping
Every worker is a fresh single-use container that can only reach Modal for its own Volume commit (restrict_modal_access).
Work beyond those numbers waits in Modal's queue and starts when a slot frees up; nothing is refused for being busy.
The time limits and shapes here must match SHAPE in cloud/ctl.py and STAGE_TIMEOUT in cloud/worker/pipeline.py.
Needs (docs/SETUP_CLOUD.md): secrets <prefix>-generation and <prefix>-claude, volume <prefix>-whisper-ct2 with the model.
"""
import os
import pathlib
import sys

import modal

C = pathlib.Path(__file__).resolve().parents[1]
try:   # deploy runs on the Mac, inside the repo: one source for the names
    sys.path.insert(0, str(C))
    import names as _names
    PREFIX = _names.PREFIX
except Exception:
    PREFIX = os.environ.get('ADMACHINE_PREFIX') or 'admachine'
APP, VOLUME, STATUS = f'{PREFIX}-ads', f'{PREFIX}-adjobs', f'{PREFIX}-ads-status'
GEN_SECRET, CLAUDE_SECRET, MODEL_VOLUME = f'{PREFIX}-generation', f'{PREFIX}-claude', f'{PREFIX}-whisper-ct2'

# Exact runtime pins (faster-whisper CPU stack + Pillow for the render tools), then the two packages the paid / Claude
# workers need. ffmpeg is the static 7.0.2 build, checked by size and sha256.
PINS = ['av==15.1.0', 'certifi==2026.10.23', 'charset-normalizer==3.5.2', 'ctranslate2==4.6.0', 'faster-whisper==1.2.1',
        'filelock==4.2.12', 'flatbuffers==25.12.19', 'fsspec==2026.9.0', 'hf-xet==1.8.0', 'huggingface-hub==0.36.2',
        'idna==3.20', 'numpy==2.2.6', 'onnxruntime==1.32.0', 'packaging==26.3', 'protobuf==7.36.2', 'pyyaml==6.0.3',
        'requests==2.34.2', 'setuptools==84.2.1', 'tokenizers==0.21.4', 'tqdm==4.70.1', 'typing-extensions==4.16.0',
        'urllib3==2.8.0', 'pillow==13.0.0']
image = (modal.Image.debian_slim(python_version='3.12.14')
         .apt_install('curl', 'xz-utils', 'fontconfig')
         .uv_pip_install(*PINS)
         .run_commands('set -eu; curl -fsSL --retry 0 --max-time 180 -o /tmp/ffmpeg.tar.xz '
                       'https://johnvansickle.com/ffmpeg/releases/ffmpeg-7.0.2-amd64-static.tar.xz; '
                       'test "$(stat -c %s /tmp/ffmpeg.tar.xz)" = 41888096; '
                       'echo "abda8d77ce8309141f83ab8edf0596834087c52467f6badf376a6a2a4c87cf67  /tmp/ffmpeg.tar.xz" | sha256sum -c -; '
                       'mkdir -p /opt/ffmpeg/bin; tar -xJf /tmp/ffmpeg.tar.xz --strip-components=1 -C /opt/ffmpeg/bin '
                       'ffmpeg-7.0.2-amd64-static/ffmpeg ffmpeg-7.0.2-amd64-static/ffprobe; '
                       'chmod 755 /opt/ffmpeg/bin/ffmpeg /opt/ffmpeg/bin/ffprobe; rm /tmp/ffmpeg.tar.xz')
         .uv_pip_install('httpx==0.28.1', 'claude-agent-sdk==0.2.187'))
vol = modal.Volume.from_name(VOLUME, create_if_missing=True)
models = modal.Volume.from_name(MODEL_VOLUME, create_if_missing=False).with_mount_options(read_only=True)
app = modal.App(APP, include_source=False)
WORKER = dict(image=image, serialized=True, include_source=False, volumes={'/vol': vol, '/model': models},
              startup_timeout=180, retries=0, min_containers=0, buffer_containers=0, scaledown_window=2,
              restrict_modal_access=True, single_use_containers=True)


@app.function(**WORKER, timeout=2700, max_containers=16, cpu=(4, 4), memory=(8192, 8192), block_network=True)
def run_plain(payload):
    import re, sys
    if not re.fullmatch(r'[0-9a-f]{12,64}', str(payload.get('code'))) or not set(payload.get('stages', [])) <= {'check', 'rawrender', 'padtail', 'rawverify', 'preflight', 'status'}:
        raise ValueError('run_plain: offline stages and a code version only')
    sys.path.insert(0, f"/vol/adjobs/_code/{payload['code']}/worker")
    import ad_job
    return ad_job.run(payload, commit=vol.commit)


@app.function(**WORKER, timeout=3600, max_containers=10, cpu=(2, 2), memory=(4096, 4096), secrets=[modal.Secret.from_name(GEN_SECRET)])
def run_gen(payload):
    import re, sys
    if not re.fullmatch(r'[0-9a-f]{12,64}', str(payload.get('code'))) or not set(payload.get('stages', [])) <= {'vo', 'frames', 'clips', 'redo'}:
        raise ValueError('run_gen: generation stages and a code version only')
    sys.path.insert(0, f"/vol/adjobs/_code/{payload['code']}/worker")
    import ad_job
    return ad_job.run(payload, commit=vol.commit)


@app.function(**WORKER, timeout=2700, max_containers=10, cpu=(2, 2), memory=(4096, 4096), secrets=[modal.Secret.from_name(CLAUDE_SECRET)])
def run_claude(payload):
    import re, sys
    if not re.fullmatch(r'[0-9a-f]{12,64}', str(payload.get('code'))) or not set(payload.get('stages', [])) <= {'shotcheck', 'plan_review', 'qc', 'stitch', 'masterqc'} or payload.get('max_tasks'):
        raise ValueError('run_claude: Claude stages, no paid tasks, and a code version only')
    sys.path.insert(0, f"/vol/adjobs/_code/{payload['code']}/worker")
    import ad_job
    return ad_job.run(payload, commit=vol.commit)


@app.function(image=image, serialized=True, include_source=False, volumes={'/vol': vol.with_mount_options(read_only=True)},
              cpu=0.25, memory=512, timeout=6 * 3600, startup_timeout=180, retries=0, min_containers=0, buffer_containers=0,
              scaledown_window=2, max_containers=80, single_use_containers=True)
def pipeline(job):
    import re, sys
    import modal as m
    if not re.fullmatch(r'[0-9a-f]{12,64}', str(job.get('code'))):
        raise ValueError('pipeline: code version required')
    sys.path.insert(0, f"/vol/adjobs/_code/{job['code']}/worker")
    import pipeline as P
    board = m.Dict.from_name(STATUS, create_if_missing=True)
    workers = {kind: m.Function.from_name(APP, 'run_' + kind) for kind in ('plain', 'gen', 'claude')}

    def status(state):
        try:
            board.put(state['run'], state)
        except Exception as error:   # a status write must never break a paid run
            print('status write failed:', type(error).__name__)
    return P.run_pipeline(job, lambda kind, payload: workers[kind].remote(payload), status)


@app.function(image=image, serialized=True, include_source=False, volumes={'/vol': vol}, cpu=1, memory=1024, timeout=1500,
              retries=0, min_containers=0, scaledown_window=2, max_containers=1, single_use_containers=True,
              block_network=True, restrict_modal_access=True)
def admin(op):
    """'migrate': move every /adjobs/_assets/<ad>/<path> into the shared store /adjobs/_store/<path> (same file, one copy)."""
    import os, pathlib as pl, shutil
    if op != 'migrate':
        raise ValueError('unknown op')
    old, store, moved, kept = pl.Path('/vol/adjobs/_assets'), pl.Path('/vol/adjobs/_store'), 0, 0
    if old.is_dir():
        for f in sorted(p for p in old.rglob('*') if p.is_file()):
            rel = pl.Path(*f.relative_to(old).parts[1:])
            out = store / rel
            if out.is_file() and out.stat().st_size == f.stat().st_size:
                kept += 1
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, out)
                moved += 1
        shutil.rmtree(old)
        os.sync()
        vol.commit()
    return {'moved': moved, 'already_there': kept}
