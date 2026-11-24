"""Mac client of the cloud ad controller (deployed Modal app `<app_prefix>-ads`, cloud/controller/app.py; names in cloud/names.py).

Run from the repo root with the Python that has `modal` installed:  .modal-env/bin/python cloud/ctl.py <command>
Settings: cloud/controller/config.json (copy config.example.json; without it the example's values are used).

  submit <recipe> <ad,ad,...> --go [--batch "<name>"] [--kie-cap N] [--redo "<ad>:<beat>:frame|clip:<note>" ...] [--clip-bound N]
  submit --from <batch.json> --go      many ads with different recipes / redos in one go (see `revise-plan`)
        Uploads what changed (code, project, any footage the shared store does not have yet), starts one cloud pipeline
        per ad and returns at once. The Mac can sleep or close: the cloud keeps going. Submit as many batches as you like;
        the cloud runs them side by side and queues what does not fit.
        Real footage:  raw (shot check -> render)
        AI ad, straight through:  ai (plan review -> voice -> stills -> clips -> QC/assemble)
        AI ad with the starting-frame review:  ai-frames (plan review -> voice -> stills -> stills QC, then stop)
              -> ai-frames-revise (redo stills from the owner's notes; repeat until he is happy) -> ai-clips (clips -> QC/assemble)
        ai-resume (missing stills/clips -> QC/assemble, voice kept; also continues a run that failed part-way)
        ai-revise (redo beats of a finished ad -> QC/assemble), ai-finish (QC/assemble only), inserts (stills/clips/QC),
        check (offline readiness). Paid recipes use kie_cap_per_ad from config.json (the most kie credits ONE ad may use in
        one run); --kie-cap N overrides it for one submit.
  status [--batch N] where every open run is, grouped by batch (queued / running step / done / failed / blocked)
  wait [ad ...]     block until the named (or all open) runs finish
  collect [ad ...]  for finished runs: settle the budget, download with sha256 checks, run the Mac final checks
                    (real-footage: rawedit verify; all: preflight), one ad at a time. A frame-review run opens REVIEW.html.
  watch [--once]    keep collecting finished runs as they land and post a Slack note (the launchd job runs this)
  notes             pull new Frame.io comments into the feedback log and list what is open
  revise-plan [ad ...]   open owner notes -> a batch file skeleton (each note matched to its beat / shot) for `submit --from`
  history [N] [--next]   the last N collected runs with their result (--next: what to do with each)
  dash [--no-open]  the ad board: tabs for In progress / Frames to approve / Getting ready for Frame.io / Ready for review
                    (with the Frame.io link). Approved ads are not shown. The watcher keeps it fresh.
                    dash --hide "<ad or batch>" takes something off the board; --unhide puts it back; --hidden lists them.
  usage [--no-open] [--index] [--archive] [--verify]   the usage page (the board's small "Usage" button): kie credits and dollars per
                    batch (first pass / revisions), revision rounds, make time, the live kie balance. cloud/usage.py.
  reviews [--done <ad>]  frame decisions the owner sent from the board or a REVIEW.html page (the "Approve frames" /
                    "Send to Claude" buttons, cloud/frame_review.py) that still wait for a session to act. For an ad made by
                    the cloud controller the next run starts by itself; for any other ad the decision waits here.
                    --done <ad> marks one as dealt with.
  jobs [--sweep]    unattended Claude jobs on this Mac (cloud/claude_job.py): the headless Claude that the "Revisions done"
                    button and the watcher start, one per batch. Shows what runs, how each ended and its log.
                    --sweep starts whatever waits now (the watcher does this every pass).
  assets <ad>       dry run: which shared files this ad needs
  migrate           one-off: move older per-ad footage copies on the Volume into the shared store
  deploy            (re)deploy the cloud app; only needed when cloud/controller/app.py changes
  submit ... --checks   this submit also runs the final checks in the cloud (always, with "cloud_checks": true in
                    config.json): the run comes back with what they found. CONTROLLER.md "Final checks in the cloud".

Money: every cloud call is admitted against cloud/controller/ledger-<month>.json before it starts (cap and stop line in
cloud/controller/config.json). A paid worker that CRASHES stops everything (GLOBAL_STOP.json) until a person lifts it; a
paid step that ends cleanly with items the provider did not deliver only fails that ad (nothing was charged for them).
Nothing here approves, uploads to Drive or pushes to Frame.io: after `collect`, answer PREFLIGHT.md and run frameio.py push.
"""
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
from decimal import Decimal as D

C = pathlib.Path(__file__).resolve().parent
ROOT = C.parent
sys.path[:0] = [str(ROOT), str(C)]
from cloud.worker import pipeline as P  # noqa: E402
from cloud.worker.overnight_budget import Budget  # noqa: E402
import names  # noqa: E402

STATE = C / 'controller'
APP, VOLUME, BOARD = names.APP, names.VOLUME, names.STATUS
SLACK_POST = ROOT / 'bin' / 'slack-post'   # bin/slack-post <slack_user_id> <message-file|->  (Composio SLACK_SEND_MESSAGE)
CODE = C / '.scratch/ctl-code'
MAC_PY = str(ROOT / '.venv/bin/python')
MODAL_PY = os.environ.get('MODAL_PYTHON') or sys.executable   # the Python that has `modal`
DEFAULTS = {'modal_cap_usd': '10.00', 'modal_stop_usd': '10.00', 'max_ads_per_submit': 24, 'kie_cap_per_ad': 1500,
            'cloud_checks': False, 'trust_cloud_checks': False}   # $10/month Modal (tell the owner if hit); kie default per ad per run
# (CPU, GiB, function time limit in seconds) of each cloud function: must match cloud/controller/app.py
SHAPE = {'plain': (D(4), D(8), 2700), 'gen': (D(2), D(4), 3600), 'claude': (D(2), D(4), 2700), 'pipeline': (D('0.25'), D('0.5'), 21600),   # 6 h: the steps of the longest recipe add up to 4 h 5 min before queueing and saving
         'admin': (D(1), D(1), 1500)}
BATCH_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,59}')
SKIP_UP = re.compile(r'(^|/)(SEGMENTS/|\.DS_Store$)|\.part$|\.dl$|(^|/)MASTER[^/]*\.mp4$')
STILL_BOUND = D(25)          # measured: Nano Banana Pro 2K still = 18 credits
CLIP_PER_SECOND = D(24)      # measured: Kling 3.0 std with sound = 100-113.5 credits per 5 s


# ---------- pure helpers (tested in cloud/tests/test_ctl.py) ----------
def unit(kind):
    cpu, mem, _ = SHAPE[kind]
    return cpu * D('.0000131') + mem * D('.00000222')


def bound(kind):
    return (D(SHAPE[kind][2] + 180 + 30) * unit(kind) + D('.005')).quantize(D('.0001'))


def parse_redos(items, ads):
    """--redo "ad:beat:frame|clip:note" -> {ad: [[beat, what, note], ...]} (order kept). One ad may omit the ad prefix."""
    out = {}
    for item in items:
        parts = item.split(':', 3)
        if len(parts) >= 2 and parts[0].isdigit() and len(ads) == 1:
            parts = [ads[0]] + item.split(':', 2)
        if len(parts) < 3 or parts[0] not in ads or not parts[1].isdigit() or parts[2] not in ('frame', 'clip'):
            raise ValueError(f'bad --redo {item!r}: use "<ad>:<beat>:frame|clip:<note>"')
        out.setdefault(parts[0], []).append([int(parts[1]), parts[2], parts[3].strip() if len(parts) > 3 else ''])
    return out


def versions(folder, stem, ext):
    """Files of one beat in any version: <stem><ext>, <stem>_v2<ext> ... (the same test tools/ad.py `latest` uses)."""
    return [p for p in folder.glob(f'{stem}*{ext}') if re.fullmatch(rf'{stem}(_v\d+)?', p.stem)] if folder.is_dir() else []


def kie_need(plan, recipe, redos, lib=None, clip_bound=None, proj=None):
    """(createTask count, worst-case credits) one run of a paid recipe can use, from measured prices. With `proj` (the
    project folder) stills and clips that already exist are not counted, exactly as the tools skip them. No measured price
    for the plan's clip mode -> ValueError (pass --clip-bound after a measured pilot, never a guess)."""
    lib = lib or {}
    beats = {b['n']: b for b in plan.get('beats', [])}
    stages = {st for kind, sts in P.RECIPES[recipe] if kind in P.PAID for st in sts}
    frames_dir, clips_dir = (proj / 'FRAMES', proj / 'CLIPS') if proj else (pathlib.Path('/nonexistent'),) * 2

    def clip_cost(b):
        if clip_bound is not None:
            return D(clip_bound)
        if plan.get('kling_mode', 'std') != 'std':
            raise ValueError(f"no measured kie price for kling mode {plan.get('kling_mode')!r}: pass --clip-bound")
        return max(D(120), CLIP_PER_SECOND * D(str(b.get('duration', 5))))
    tasks, worst = 0, D(0)
    if 'redo' in stages:
        for beat, what, _ in redos:
            if beat not in beats:
                raise ValueError(f'no beat {beat} in this plan')
            if recipe == 'ai-frames-revise' and what != 'frame':
                raise ValueError(f'beat {beat}: ai-frames-revise redoes stills only (clips do not exist yet)')
            tasks += 1; worst += STILL_BOUND if what == 'frame' else clip_cost(beats[beat])
        return tasks, worst
    for b in beats.values():
        entry = lib.get(b.get('lib')) if b.get('lib') else None
        if b.get('lib') and not entry:
            raise ValueError(f"beat {b['n']}: library id {b['lib']!r} not found")
        whole_clip = bool(entry) and entry.get('type') == 'clip'      # an approved library clip is reused whole: free
        has_clip = bool(versions(clips_dir, f"clip_{b['n']:02d}", '.mp4'))
        if 'frames' in stages and not whole_clip:
            n = 0 if entry or (frames_dir / f"scene_{b['n']:02d}.png").exists() else 1
            if b.get('end_visual') and not (frames_dir / f"scene_{b['n']:02d}_end.png").exists() and not has_clip:
                n += 1
            tasks += n; worst += n * STILL_BOUND
        if 'clips' in stages and not whole_clip and not has_clip:
            tasks += 1; worst += clip_cost(b)
    return tasks, worst


def task_cap(tasks):
    """Hard count of paid tasks the cloud worker may create in one run: the planned ones plus room for the second pass
    on tasks the provider fails (failed tasks are not charged, so the credit worst case does not move)."""
    return tasks + max(2, tasks // 4)


def digest_tree(folder):
    h = hashlib.sha256()
    for f in sorted(p for p in folder.rglob('*') if p.is_file() and p.name != '.complete'):
        h.update(f.relative_to(folder).as_posix().encode() + b'\0' + hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()[:16]


def step_keys(run, recipe, checks=False):
    return [f'{run}-s{i}-{kind}' for i, (kind, _) in enumerate(P.steps_of(recipe, checks))] + [f'{run}-pipeline']


def settle(run, state):
    """Budget outcome per admitted call of a run -> [(key, status, estimate_usd)]. Calls that never ran cost nothing;
    a crash or timeout is counted at its full admitted bound. A paid step that ended cleanly but incomplete (the provider
    did not deliver some items, or a tool reported an error) is INCOMPLETE: that ad failed, nothing else has to stop.
    A paid worker that crashed is FAILED: the budget journal raises the global stop for that."""
    recipe, out = run['recipe'], []
    checks = bool(run.get('checks'))   # this run was admitted with one more step: the final checks in the cloud
    steps = (state or {}).get('steps', [])
    if (state or {}).get('never_started'):   # the submit never reached the cloud: nothing ran, nothing is owed
        return [(key, 'SKIPPED', D(0)) for key in step_keys(run['run'], recipe, checks)]
    # a pipeline that died mid-run: steps the board saw finish are settled as they ended, the step that was running
    # counts at its full bound (FAILED: for a paid step that raises the global stop), later steps never started
    running = len(steps) if (state or {}).get('state') == 'crashed' and state.get('current') else None
    for i, (kind, _) in enumerate(P.steps_of(recipe, checks)):
        key = f"{run['run']}-s{i}-{kind}"
        if state is None or i == running:
            out.append((key, 'FAILED', bound(kind)))
        elif i >= len(steps) or steps[i].get('skipped'):
            out.append((key, 'SKIPPED', D(0)))
        else:
            row = steps[i]
            if 'checks' in row and row.get('error') and row.get('seconds') is not None:
                # the final checks could not run (refused or crashed): charged for the time the tries took, not the bound
                est = min((D(str(row['seconds'])) + 80) * unit(kind), bound(kind)).quantize(D('.0001'))
                out.append((key, 'FAILED', est))
            elif row.get('error') or row.get('seconds') is None:
                out.append((key, 'FAILED', bound(kind)))
            else:
                tries = 2 if row.get('retried') else 1   # a retried unpaid step ran twice under one admission
                est = min((D(str(row['seconds'])) + 40) * tries * unit(kind), bound(kind)).quantize(D('.0001'))
                verdict = 'BLOCKED' if row.get('gate') == 'blocked' else 'DONE' if not row.get('failed') else 'INCOMPLETE' if kind in P.PAID else 'FAILED'
                out.append((key, verdict, est))
    if state is None or not state.get('finished'):
        out.append((f"{run['run']}-pipeline", 'FAILED', bound('pipeline')))
    else:
        est = min((D(str(state['finished'] - state['started'])) + 40) * unit('pipeline'), bound('pipeline')).quantize(D('.0001'))
        out.append((f"{run['run']}-pipeline", 'DONE', est))
    return out


def time_to_place(plan, t):
    """Where second `t` of the finished ad falls: ('beat', n, text) for an AI ad, ('shot', index, text) for real footage."""
    if plan.get('shots'):
        shots = sorted(plan['shots'], key=lambda x: x.get('at', 0))
        hit = [i for i, x in enumerate(shots) if x.get('at', 0) <= t]
        if not hit:
            return None
        x = shots[hit[-1]]
        return 'shot', hit[-1], f"{pathlib.Path(str(x.get('src', ''))).stem}@{x.get('in', 0)} {x.get('note', '')}".strip()
    hit = [b for b in plan.get('beats', []) if b.get('vo_start') is not None and b['vo_start'] <= t]
    if not hit:
        return None
    return 'beat', hit[-1]['n'], str(hit[-1].get('visual', ''))[:90]


def flag_rows(issues):
    """Shot-check issues on library footage -> rows for footage/moments/flags.jsonl (the clip search demotes them)."""
    rows = []
    for it in issues:
        m = re.fullmatch(r'([A-Za-z0-9_-]{20,})@([\d.]+)', it.get('key', ''))
        if m and it.get('clip_fault'):   # only faults of the footage itself, never a wrong pick for a line
            rows.append({'fid': m[1], 't': float(m[2]), 'issue': f"{it.get('rule', '')} {it.get('issue', '')}".strip()[:200]})
    return rows


# ---------- local state ----------
def cfg():
    """cloud/controller/config.json, or config.example.json when it is missing, over DEFAULTS."""
    STATE.mkdir(exist_ok=True)
    return {**DEFAULTS, **names.config(STATE)}


def ledger():
    c = cfg()
    b = Budget(STATE / f"ledger-{datetime.date.today():%Y-%m}.json", c['modal_cap_usd'], c['modal_stop_usd'], task=APP)
    with b.locked() as data:   # the config file is the owner's setting; keep the month's ledger in step with it
        if (data['cap_usd'], data['stop_at_usd']) != (c['modal_cap_usd'], c['modal_stop_usd']):
            data.update(cap_usd=c['modal_cap_usd'], stop_at_usd=c['modal_stop_usd']); b.write(data)
    return b


def runs_load():
    f = STATE / 'runs.json'
    return json.loads(f.read_text()) if f.exists() else {}


def runs_save(runs):
    STATE.mkdir(exist_ok=True)
    tmp = STATE / 'runs.json.pending'
    tmp.write_text(json.dumps(runs, indent=1) + '\n')
    os.replace(tmp, STATE / 'runs.json')


@contextlib.contextmanager
def runs_locked():
    """Read-change-write of runs.json under a file lock: several sessions and the watcher use the controller at once."""
    STATE.mkdir(exist_ok=True)
    with (STATE / 'runs.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        runs = runs_load()
        yield runs
        runs_save(runs)


def run_update(run_id, **fields):
    with runs_locked() as runs:
        runs[run_id].update(fields)
        return dict(runs[run_id])


def guard():
    if (STATE / 'GLOBAL_STOP.json').exists():
        sys.exit('GLOBAL STOP is set (cloud/controller/GLOBAL_STOP.json): a person has to look at it and lift it first')
    free, need = shutil.disk_usage(ROOT).free, float(cfg().get('mac_min_free_gb', 3))   # refuse new work below this much free disk
    if free < need * 1e9:
        sys.exit(f'Mac disk has {free / 1e9:.1f} GB free; {need:g} GB needed (mac_min_free_gb in cloud/controller/config.json)')


def sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


# ---------- staging ----------
def build_snapshot(CODE=None):
    """Copy the code a cloud run needs into `CODE` and return its content version. Each submit passes its own folder."""
    CODE = pathlib.Path(CODE or globals()['CODE'])
    if CODE.exists():
        shutil.rmtree(CODE)
    (CODE / 'tools').mkdir(parents=True)
    for p in (ROOT / 'tools').glob('*.py'):
        shutil.copy2(p, CODE / 'tools' / p.name)
    for rel in ('feedback', 'library/fonts', 'library/sfx'):
        shutil.copytree(ROOT / rel, CODE / rel, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
    if (ROOT / 'library/index.json').exists():
        shutil.copy2(ROOT / 'library/index.json', CODE / 'library/index.json')
    (CODE / 'cloud').mkdir(parents=True)
    shutil.copy2(C / 'transcription.py', CODE / 'cloud/transcription.py')
    shutil.copy2(C / 'whisper-settings.json', CODE / 'cloud/whisper-settings.json')
    (CODE / 'worker').mkdir()
    for n in ('adjob_boot.py', 'adjob_check.py', 'ad_job.py', 'pipeline.py'):
        shutil.copy2(C / 'worker' / n, CODE / 'worker' / n)
    (CODE / 'worker/mac_root.txt').write_text(str(ROOT) + '\n')   # ad_job.py maps this Mac path to the container's copy
    version = digest_tree(CODE)
    (CODE / '.complete').write_text(version + '\n')
    return version


def assets_of(ad):
    """Every file outside the project folder this ad reads, ROOT-relative (the shared store keeps one copy of each)."""
    proj = ROOT / 'projects' / ad
    text = (proj / 'plan.json').read_text()
    plan = json.loads(text)
    found = set()
    for m in re.finditer(re.escape(str(ROOT)) + r'/[^"\\]+', text):   # any absolute repo path the plan names
        f = pathlib.Path(m[0])
        if f.is_file() and proj not in f.parents:
            found.add(f)
    if plan.get('shots'):   # real-footage ad
        if any(str(x.get('src', '')).startswith('m:') for x in plan['shots']):
            sys.exit(f'{ad}: the plan uses m:<id> clip references; set real file paths (and "in") before a cloud run')
        raw, tr = ROOT / 'footage/raw', ROOT / 'footage/transcripts'
        srcs = [pathlib.Path(x['src']) for x in plan['shots']] + [raw / plan['aroll']['file']]
        # the backwards-text check is Apple Vision (Mac only): make sure every clip's cached answer exists, ship the cache
        subprocess.run([MAC_PY, '-c', 'import sys, pathlib; sys.path.insert(0, sys.argv[1]); import rawedit as RE\n'
                        'for f, n in zip(sys.argv[2::2], sys.argv[3::2]): RE.mirror_of(pathlib.Path(f), int(n))', str(ROOT / 'tools'),
                        *[x for f in srcs for x in (str(f), '6' if f.name == plan['aroll']['file'] else '4')]], check=True, cwd=ROOT)
        for f in srcs:
            found.add(f)
            if (tr / f'{f.stem}.mirror.json').exists():
                found.add(tr / f'{f.stem}.mirror.json')
        for suffix in ('.words.json', '.silences.json'):
            if (tr / f"{plan['aroll']['fid']}{suffix}").exists():
                found.add(tr / f"{plan['aroll']['fid']}{suffix}")
    else:   # AI ad: approved library clips it reuses + its music track
        lib = json.loads((ROOT / 'library/index.json').read_text()) if (ROOT / 'library/index.json').exists() else {}
        for b in plan.get('beats', []):
            if b.get('lib') and b['lib'] in lib:
                found.add(ROOT / 'library' / lib[b['lib']]['file'])
        has_track = plan.get('music') and (proj / plan['music']).exists()
        if plan.get('music_mood') and not plan.get('song') and not has_track:
            # same call ad.py stitch makes; it records the pick in library/music/usage.json so the cloud run picks the same track
            beats = plan['beats']
            hold_n = plan.get('hold_beat', beats[1]['n'] if len(beats) > 1 else beats[0]['n'])
            code = ('import sys, json; sys.path.insert(0, sys.argv[1]); import music_lib as ml\n'
                    'a = json.loads(sys.argv[2]); print(json.dumps(ml.pick(*a, quiet=True)))')
            args = [plan['music_mood'], plan.get('music_kind', 'any'), (beats[-1].get('vo_end') or 30) + 3, ad,
                    bool(plan.get('music_vocals')), next((b.get('vo_start') or 0.0 for b in beats if b['n'] == hold_n), 0.0)]
            pick = json.loads(subprocess.run([MAC_PY, '-c', code, str(ROOT / 'tools'), json.dumps(args)], capture_output=True, text=True,
                                             check=True, cwd=ROOT).stdout.strip().splitlines()[-1])
            if pick:
                found.update({pathlib.Path(pick['file']), ROOT / 'library/music/index.json', ROOT / 'library/music/usage.json'})
    bad = [str(f) for f in found if not f.is_file() or ROOT not in f.resolve().parents]
    if bad:
        sys.exit(f'{ad}: files missing or outside the repo: ' + ', '.join(bad))
    return sorted(f.resolve().relative_to(ROOT).as_posix() for f in found)


def listing(vol, prefix):
    out = {}
    try:
        for e in vol.iterdir(prefix, recursive=True):
            if e.type.name == 'FILE':
                out[e.path.split(prefix.strip('/') + '/', 1)[1]] = e.size
    except Exception:
        pass
    return out


def read_small(vol, path):
    try:
        return b''.join(vol.read_file(path))
    except Exception:
        return None


MUTABLE_SMALL = re.compile(r'\.(json|jsonl|txt|srt|csv|md)$')


def store_has(store, rel, size):
    """Is this shared file already in the cloud store? The store listing only gives sizes, so a small text file
    (word timings, mirror cache, music index: they get edited in place) is always sent again; media is matched by size."""
    return store.get(rel) == size and not (size < 2_000_000 and MUTABLE_SMALL.search(rel))


def stage(vol, ads, version, code_dir=None):
    code_dir = pathlib.Path(code_dir or CODE)
    needs = {ad: assets_of(ad) for ad in ads}
    store = listing(vol, '/adjobs/_store')
    code_there = read_small(vol, f'/adjobs/_code/{version}/.complete') is not None
    plan_uploads, sizes = [], 0
    for ad in ads:
        proj = ROOT / 'projects' / ad
        (proj / 'assets.json').write_text(json.dumps(needs[ad], indent=1) + '\n')
        manifest = json.loads(read_small(vol, f'/adjobs/{ad}/MANIFEST.sha256.json') or b'{}')
        cloud_jobs = len((read_small(vol, f'/adjobs/{ad}/jobs.jsonl') or b'').splitlines())
        local_jobs = len((proj / 'jobs.jsonl').read_text().splitlines()) if (proj / 'jobs.jsonl').exists() else 0
        if cloud_jobs > local_jobs:
            sys.exit(f'{ad}: the cloud copy has newer generation records than the Mac ({cloud_jobs} vs {local_jobs}). '
                     f'Run `collect {ad}` (or adjob.py pull) first so nothing paid is made twice.')
        for f in sorted(p for p in proj.rglob('*') if p.is_file()):
            rel = f.relative_to(proj).as_posix()
            if SKIP_UP.search(rel) or rel == 'MANIFEST.sha256.json':
                continue
            known = manifest.get(rel)
            if known and known['size'] == f.stat().st_size and known['sha256'] == sha_file(f):
                continue
            plan_uploads.append((f, f'/adjobs/{ad}/{rel}')); sizes += f.stat().st_size
    shared = sorted({rel for ad in ads for rel in needs[ad] if not store_has(store, rel, (ROOT / rel).stat().st_size)})
    with vol.batch_upload(force=True) as up:
        if not code_there:
            up.put_directory(str(code_dir), f'/adjobs/_code/{version}')
        for rel in shared:
            up.put_file(str(ROOT / rel), '/adjobs/_store/' + rel)
        for f, dest in plan_uploads:
            up.put_file(str(f), dest)
    mb = sum((ROOT / rel).stat().st_size for rel in shared) / 1e6
    print(f"staged: code {version}{' (already in the cloud)' if code_there else ' uploaded'}; {len(shared)} new shared files ({mb:.0f} MB), "
          f"{sum(len(v) for v in needs.values()) - len(shared)} reused from the store; {len(plan_uploads)} project files ({sizes / 1e6:.0f} MB)")
    return needs


# ---------- commands ----------
def specs_from(args, c):
    """What to start, as [{'ad', 'recipe', 'redos'}], plus the batch name. Either `<recipe> <ad,ad,...>` with --redo
    items, or `--from file.json`: {"batch": "name", "jobs": [{"ad": "x", "recipe": "raw"},
    {"ad": "y", "recipe": "ai-revise", "redo": [[3, "clip", "note"], ...]}]} (jobs with "skip": true are left out)."""
    opt = lambda name: args[args.index(name) + 1] if name in args else None   # noqa: E731
    batch = opt('--batch')
    if '--from' in args:
        data = json.loads(pathlib.Path(opt('--from')).expanduser().read_text())
        batch = batch or data.get('batch')
        specs = []
        for j in data.get('jobs', []):
            if j.get('skip'):
                continue
            redos = [[int(r[0]), str(r[1]), str(r[2]) if len(r) > 2 else ''] for r in j.get('redo', [])]
            if any(r[1] not in ('frame', 'clip') for r in redos):
                sys.exit(f"{j.get('ad')}: each redo is [beat, \"frame\"|\"clip\", \"note\"]")
            specs.append({'ad': str(j.get('ad')), 'recipe': str(j.get('recipe')), 'redos': redos})
    else:
        recipe, ads = args[0], [a for a in args[1].split(',') if a]
        redos = parse_redos([args[i + 1] for i, a in enumerate(args) if a == '--redo'], ads)
        specs = [{'ad': ad, 'recipe': recipe, 'redos': redos.get(ad, [])} for ad in ads]
    ads = [x['ad'] for x in specs]
    if not specs or len(set(ads)) != len(ads) or len(ads) > int(c['max_ads_per_submit']):
        sys.exit(f"1 to {c['max_ads_per_submit']} different ads per submit (one run per ad at a time)")
    bad = sorted({x['recipe'] for x in specs} - set(P.RECIPES))
    if bad:
        sys.exit(f"unknown recipe {', '.join(bad)}. Recipes: " + ', '.join(sorted(P.RECIPES)))
    batch = batch or f"{specs[0]['recipe'] if len({x['recipe'] for x in specs}) == 1 else 'mixed'} {time.strftime('%m-%d %H.%M')}"
    if not BATCH_NAME.fullmatch(batch):
        sys.exit('batch name: letters, digits, space, dot, dash, underscore; up to 60 characters')
    return specs, batch


def banned_hits(plan):
    """Banned clips/windows in a real-footage plan, from tools/banned.py. No answer (older checkout) means no refusal:
    the Mac final checks still catch a banned clip after the render."""
    try:
        sys.path.insert(0, str(ROOT / 'tools'))
        import banned
        hits = banned.blockers(plan, ROOT) if hasattr(banned, 'blockers') else banned.plan_hits(plan, ROOT)   # line-scoped windows only warn (preflight)
        return list(hits or [])
    except SystemExit:
        raise
    except Exception:
        return []
    finally:
        if str(ROOT / 'tools') in sys.path:
            sys.path.remove(str(ROOT / 'tools'))


def plan_job(spec, c, runs, lib, cap_opt=None, clip_bound=None, checks=False):
    """Every refusal for one ad happens here, before anything is uploaded or started. Returns the job dict."""
    ad, recipe = spec['ad'], spec['recipe']
    proj = ROOT / 'projects' / ad
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,80}', ad) or not (proj / 'plan.json').exists():
        sys.exit(f'no project {ad} (lower-case name with a plan.json)')
    plan = json.loads((proj / 'plan.json').read_text())
    if plan.get('locked'):
        sys.exit(f'{ad} is LOCKED (launched): never re-made')
    if any(r['ad'] == ad and not r.get('collected') for r in runs.values()):
        sys.exit(f'{ad} still has a run that was not collected: run `collect {ad}` first')
    has_voice = any((proj / 'VO').glob('vo.*'))
    if recipe == 'ai' and has_voice:
        sys.exit(f'{ad} already has a voiceover: use ai-resume (stills/clips/assemble), ai-revise or ai-finish, never a second voice run')
    if bool(plan.get('shots')) != (recipe == 'raw') and recipe != 'check':
        sys.exit(f"{ad}: recipe {recipe!r} does not fit this project ({'real-footage' if plan.get('shots') else 'AI'} plan)")
    job = {'ad': ad, 'recipe': recipe, 'max_tasks': 0}
    if recipe == 'raw':   # a clip or window the owner banned never reaches a render (footage/BANNED_CLIPS.json)
        hits = banned_hits(plan)
        if hits:
            sys.exit(f'{ad}: the plan uses footage the owner banned. Replace it, then submit again:\n' + '\n'.join(
                f"  {h.get('where', '?')}: {pathlib.Path(str(h.get('src', ''))).name} {h.get('in', '')} ({h.get('reason', '')})" for h in hits))
    if recipe == 'ai-frames' and has_voice:
        job['skip'] = ['vo']   # a song ad, or a voice made earlier: the voice is never made twice
    if recipe in P.NEEDS_REDOS:
        if not spec.get('redos'):
            sys.exit(f'{ad}: {recipe} needs at least one --redo "{ad}:<beat>:frame|clip:<note>"')
        beats = {b.get('n') for b in plan.get('beats', [])}
        for r in spec['redos']:   # the same limits the cloud worker enforces; refused here nothing is reserved or started
            if type(r[0]) is not int or not 1 <= r[0] <= 99 or r[0] not in beats:
                sys.exit(f'{ad}: redo names beat {r[0]}, which this plan does not have')
            if len(r[2]) > 600 or '\x00' in r[2]:
                sys.exit(f'{ad}: the note for beat {r[0]} is {len(r[2])} characters; a redo note may be at most 600. Shorten it.')
        job['redos'] = spec['redos']
    elif spec.get('redos'):
        sys.exit(f'{ad}: redos only go with ai-revise or ai-frames-revise, not {recipe}')
    if recipe in ('ai-clips', 'ai-revise', 'ai-finish', 'ai-frames-revise'):
        need = 'FRAMES' if recipe in ('ai-clips', 'ai-frames-revise') else 'CLIPS'
        stem, ext = ('scene', '.png') if need == 'FRAMES' else ('clip', '.mp4')
        gaps = [b['n'] for b in plan.get('beats', []) if not versions(proj / need, f"{stem}_{b['n']:02d}", ext)
                and not (need == 'CLIPS' and b.get('lib'))]
        if gaps:
            hint = 'run ai-frames (or ai-resume) first' if need == 'FRAMES' else 'run ai-clips or ai-resume first'
            sys.exit(f"{ad}: {recipe} needs a {'still' if need == 'FRAMES' else 'clip'} for every beat; missing beats {gaps}: {hint}")
    if P.is_paid(recipe):
        cap = cap_opt or str(c.get('kie_cap_per_ad', ''))   # default from config.json; --kie-cap overrides one run
        if cap is None or not cap.isdigit() or int(cap) <= 0:
            sys.exit('this recipe spends kie credits: set kie_cap_per_ad in cloud/controller/config.json or pass --kie-cap N')
        try:
            tasks, worst = kie_need(plan, recipe, job.get('redos', []), lib, clip_bound, proj)
        except ValueError as e:
            sys.exit(f'{ad}: {e}')
        if worst > int(cap):
            sys.exit(f'{ad}: worst case is {worst} kie credits for {tasks} tasks, above the cap of {cap}. Nothing started.')
        voice_only = any('vo' in st for _, st in P.RECIPES[recipe]) and not job.get('skip')
        if tasks > 80 or (tasks == 0 and not voice_only):
            sys.exit(f'{ad}: {tasks} paid tasks in one run (1 to 80 allowed)' + ('; nothing is missing: use ai-finish' if tasks == 0 else ''))
        job.update(max_tasks=min(80, task_cap(tasks)), kie_tasks_planned=tasks, kie_cap=int(cap), kie_worst=str(worst))
    if (checks or c.get('cloud_checks') is True) and recipe in P.CHECK_STEP:
        job['checks'] = True   # one more unpaid step: the final checks run in the cloud, so the run comes back checked
    return job


def submit(args):
    import modal
    c = cfg()
    if '--go' not in args:
        sys.exit('add --go to really start cloud work')
    specs, batch = specs_from(args, c)
    guard()
    opt = lambda name: args[args.index(name) + 1] if name in args else None   # noqa: E731
    lib = json.loads((ROOT / 'library/index.json').read_text()) if (ROOT / 'library/index.json').exists() else {}
    runs = runs_load()
    jobs = {x['ad']: plan_job(x, c, runs, lib, opt('--kie-cap'), opt('--clip-bound'), '--checks' in args) for x in specs}
    if opt('--stage-timeout'):   # for tests of the resume path: cut every step short after N seconds (60..3400)
        for job in jobs.values():
            job['timeout_s'] = int(opt('--stage-timeout'))
    stamp = int(time.time())
    with runs_locked() as live:   # claim every ad now: a second submit of the same ad (another session) is refused here
        busy = sorted({r['ad'] for r in live.values() if r['ad'] in jobs and not r.get('collected')})
        if busy:
            sys.exit(f"{', '.join(busy)}: another submit or run of this ad is open. Nothing started (see ctl.py status).")
        for ad, job in jobs.items():
            job.update(run=f"{ad}-{job['recipe']}-{stamp}", batch=batch)
            live[job['run']] = {**job, 'submitted': stamp, 'collected': False, 'pid': os.getpid(),
                                'plan_sha': sha_file(ROOT / 'projects' / ad / 'plan.json')}
    started_runs, started = set(), 0   # started_runs: entries to keep in the registry
    code_dir = C / '.scratch' / f'ctl-code-{os.getpid()}-{stamp}'
    try:
        version = build_snapshot(code_dir)
        vol = modal.Volume.from_name(VOLUME, create_if_missing=True)
        stage(vol, list(jobs), version, code_dir)
        budget = ledger()
        fn = modal.Function.from_name(APP, 'pipeline')
        for ad, job in jobs.items():
            recipe, run = job['recipe'], job['run']
            job['code'] = version
            steps = P.steps_of(recipe, job.get('checks', False))
            keys = list(zip(step_keys(run, recipe, job.get('checks', False)), steps + [('pipeline', ['orchestrate'])]))

            def release():
                for key, _ in keys:
                    try:
                        budget.finish(key, 'SKIPPED', '0', 0)
                    except (StopIteration, PermissionError):
                        pass
            try:
                for key, (kind, stages) in keys:
                    budget.reserve(key, str(bound(kind)), 'function', {
                        'family': f"ads-{recipe}-{'checks' if (kind, stages) == P.CHECK_STEP.get(recipe) else kind}", 'paid_call': kind in P.PAID, 'diagnostic_only': kind not in P.PAID,
                        'cpu': str(SHAPE[kind][0]), 'memory_GiB': str(SHAPE[kind][1]), 'timeout': SHAPE[kind][2], 'stages': stages})
            except PermissionError as e:   # the month's Modal limit would be passed: stop here, keep what already started
                release()
                print(f'NOT started: {ad} and every ad after it. The Modal budget refused it ({e}): {started} of {len(jobs)} ads are running. '
                      'Collect finished runs to free their reserved budget, or tell the owner the monthly Modal limit is reached '
                      '(modal_cap_usd in cloud/controller/config.json).')
                break
            run_update(run, code=version, ledger=budget.path.name)
            try:
                call = fn.spawn({k: job[k] for k in ('run', 'ad', 'recipe', 'code', 'max_tasks', 'redos', 'skip', 'batch', 'timeout_s', 'checks') if k in job})
            except Exception as e:
                # most likely nothing started, but an error on this side does not prove it: the entry stays, so the ad
                # cannot be started a second time until status/collect has looked at the cloud and closed this one
                release()
                started_runs.add(run)
                print(f'NOT confirmed: {ad} ({type(e).__name__}: {str(e)[:200]}). Wait two minutes, run `ctl.py collect {ad}`, '
                      'then submit it again if it says no cloud run was started.')
                continue
            started_runs.add(run)
            run_update(run, call=call.object_id)
            budget.link(f'{run}-pipeline', call.object_id, APP)
            started += 1
            print(f'started {run}' + (f"  (kie: {job['kie_tasks_planned']} tasks planned, worst case {job['kie_worst']} of cap {job['kie_cap']})" if job.get('kie_cap') else ''))
    finally:
        shutil.rmtree(code_dir, ignore_errors=True)
        with runs_locked() as live:   # ads of this submit that never reached the cloud leave no trace
            for job in jobs.values():
                if job.get('run') not in started_runs:
                    live.pop(job.get('run'), None)
    if started:
        print(f'Batch "{batch}": {started} ad(s). The cloud is working on its own now. Check with: ctl.py status   then: ctl.py collect')
        board_refresh()


def _transient(error):
    """True for an error of the connection to Modal (no network after wake, DNS, TLS, a dropped stream): it says
    nothing about the run, so the run must not be called crashed (and settled, and collected) because of it."""
    import socket, ssl
    import modal
    names = {c.__module__.split('.')[0] for c in type(error).__mro__}
    if isinstance(error, (modal.exception.ConnectionError, modal.exception.ClientClosed, modal.exception.AuthError,
                          modal.exception.ServiceError, modal.exception.InternalError, modal.exception.ResourceExhaustedError,
                          ConnectionError, socket.gaierror, socket.timeout, ssl.SSLError)):
        return True
    return bool(names & {'grpclib', 'aiohttp', 'h2', 'asyncio'}) and not isinstance(error, modal.exception.NotFoundError)


def state_of(run, board=None):
    """Latest state of a run: the status board first, then the pipeline call itself (to notice a crash).
    Only a definite crash is terminal. A connection error returns the last known state with 'unreachable' set."""
    import modal
    state, board_ok = None, True
    try:
        board = board or modal.Dict.from_name(BOARD, create_if_missing=True)
        state = board.get(run['run'])
    except Exception:
        board_ok = False
    if state and state.get('state') in P.TERMINAL:
        return state
    waiting = state or {'state': 'queued', 'steps': []}
    if not board_ok:   # Modal cannot be reached at all: say so, decide nothing
        return {**waiting, 'unreachable': 'no connection to Modal'}
    age = time.time() - float(run.get('submitted') or 0)
    if not run.get('call'):   # the submit wrote its entry first and has not (or never) recorded the cloud call
        if state:             # the pipeline is running; without the call id only its own time limit can end the wait
            return waiting if age < SHAPE['pipeline'][2] + 900 else {**waiting, 'state': 'crashed', 'error': 'pipeline ran out of time'}
        if _alive(run.get('pid')) or age < 120:
            return {'state': 'queued', 'steps': [], 'note': 'submit in progress'}
        return {'state': 'failed', 'steps': [], 'never_started': True, 'started': run.get('submitted'), 'finished': run.get('submitted'),
                'error': 'the submit did not finish: no cloud run was started'}
    try:
        return modal.FunctionCall.from_id(run['call']).get(timeout=0)
    except modal.exception.FunctionTimeoutError:
        return {**waiting, 'state': 'crashed', 'error': 'pipeline ran out of time'}
    except modal.exception.OutputExpiredError:
        return {**waiting, 'state': 'crashed', 'error': 'the result expired before it was collected'}
    except (TimeoutError, modal.exception.TimeoutError):
        return waiting   # still running
    except BaseException as e:   # InputCancellation is a BaseException
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        if _transient(e) and age < SHAPE['pipeline'][2] + 900:
            return {**waiting, 'unreachable': f'{type(e).__name__}: {e}'[:200]}
        return {**waiting, 'state': 'crashed', 'error': f'{type(e).__name__}: {e}'[:300]}


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def describe(run, state):
    s = state.get('state', '?')
    done = ', '.join('+'.join(x['stages']) + (' skipped' if x.get('skipped') else f" {x['seconds']:.0f}s" if x.get('seconds') else '')
                     for x in state.get('steps', []))
    cur = state.get('current')
    now = f" | now: {'+'.join(cur['stages'])} for {time.time() - cur['since']:.0f}s" if cur and s == 'running' else ''
    kie = sum(float(x.get('kie_credits') or 0) for x in state.get('steps', []))
    last = state.get('steps', [{}])[-1] if state.get('steps') else {}
    why = f" | {last.get('failed') or ''} {last.get('error') or ''}".rstrip() if s in ('failed', 'crashed') else ''
    missing = f" | not delivered: {', '.join(last['not_done'])}" if last.get('not_done') else ''
    label = 'FRAMES READY' if s == 'done' and run['recipe'] in P.FRAME_REVIEW else s.upper()
    return (f"{run['run']:44s} {label:8s} {done}{now}{why}{missing}" + (f' | kie {kie:.0f}' if kie else '')
            + (f" | {state['error']}" if state.get('error') else '')
            + (f" | cannot reach Modal right now ({state['unreachable']})" if state.get('unreachable') else '')
            + (f" | {state['note']}" if state.get('note') else ''))


def pick_runs(args, runs):
    batch = args[args.index('--batch') + 1] if '--batch' in args and args.index('--batch') + 1 < len(args) else None
    names = [a for i, a in enumerate(args) if not a.startswith('--') and (i == 0 or args[i - 1] != '--batch')]
    open_runs = [r for r in runs.values() if not r.get('collected')]
    return [r for r in open_runs if (not names or r['ad'] in names or r['run'] in names) and (batch is None or r.get('batch') == batch)]


def settle_run(r, st):
    """Close a finished run's budget reservations once (status, collect and the watcher all call this). Returns a
    global-stop message when the journal raised one."""
    if r.get('settled') or st.get('state') not in P.TERMINAL:
        return None
    budget = Budget(STATE / r.get('ledger', f'ledger-{datetime.date.today():%Y-%m}.json'))   # the month it was admitted in
    stopped = None
    for key, verdict, est in settle(r, None if st['state'] == 'crashed' and not st.get('finished') and not st.get('steps') and not st.get('current') else st):
        try:
            budget.finish(key, verdict, str(est), float(st.get('finished', time.time())) - float(st.get('started', r['submitted'])))
        except PermissionError as e:
            stopped = f'{e} ({key})'
        except StopIteration:
            pass
    r.update(run_update(r['run'], settled=True, final_state=st['state']))
    return stopped


def status(args, quiet=False):
    runs = runs_load()
    todo = pick_runs(args, runs)
    if not todo:
        if not quiet:
            print('no open runs')
        return []
    import modal
    board = modal.Dict.from_name(BOARD, create_if_missing=True)
    out, stops = [], []
    for r in sorted(todo, key=lambda r: (r.get('batch') or '', r['submitted'], r['run'])):
        st = state_of(r, board)
        out.append((r, st))
        stop = settle_run(r, st)   # frees the run's reserved budget as soon as it is finished, before any download
        if stop:
            stops.append(stop)
    if not quiet:
        for batch in dict.fromkeys(r.get('batch') for r, _ in out):
            rows = [(r, st) for r, st in out if r.get('batch') == batch]
            tally = {}
            for r, st in rows:
                word = 'frames ready' if st.get('state') == 'done' and r['recipe'] in P.FRAME_REVIEW else st.get('state', '?')
                tally[word] = tally.get(word, 0) + 1
            print(f"== batch \"{batch or 'no name'}\": " + ', '.join(f'{n} {w}' for w, n in tally.items()))
            for r, st in rows:
                print('  ' + describe(r, st))
    for stop in stops:
        print(f'GLOBAL STOP (tell the owner): {stop}')
    if not quiet:
        board_refresh(out)
    return out


def wait(args):
    while True:
        rows = status(args)
        if all(st.get('state') in P.TERMINAL for _, st in rows):
            return
        print('...', flush=True)
        time.sleep(45)


def pull(vol, ad, plan_sha, strict=True):
    """Download the cloud copy of a project. Every file is checked against the sha256 manifest the worker wrote.
    strict=False is for a run where no worker reached its final save (it crashed or never started): the manifest then
    only vouches for what an earlier run or a checkpoint wrote, so a file that does not match it is left alone
    (it is the Mac's own upload) instead of failing the collect."""
    dest = ROOT / 'projects' / ad
    manifest = json.loads(read_small(vol, f'/adjobs/{ad}/MANIFEST.sha256.json') or b'{}')
    n = 0
    try:
        entries = list(vol.iterdir(f'/adjobs/{ad}', recursive=True))
    except Exception as e:
        if 'not found' in str(e).lower() or type(e).__name__ in ('NotFoundError', 'FileNotFoundError'):
            print(f'  {ad}: no folder in the cloud (nothing to download)')
            return 0
        raise
    for entry in entries:
        if entry.type.name != 'FILE':
            continue
        rel = entry.path.split(f'adjobs/{ad}/', 1)[1]
        if rel.startswith(('SEGMENTS/', 'CUT')) or rel.endswith('.dl'):
            continue
        out = dest / rel
        want = (manifest.get(rel) or {}).get('sha256')
        if not want:
            continue   # not part of the last finished run (stale or half-written): never trusted
        if out.exists() and out.stat().st_size == entry.size and sha_file(out) == want:
            continue
        if rel == 'plan.json' and out.exists() and sha_file(out) != plan_sha:
            out = dest / 'plan.cloud.json'   # the plan was edited on the Mac after submit: keep both, the person merges
            print(f'  {ad}: plan.json changed on the Mac since submit; the cloud version is saved as plan.cloud.json')
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.name + '.part')
        for attempt in range(4):
            try:
                with tmp.open('wb') as f:
                    for chunk in vol.read_file(entry.path):
                        f.write(chunk)
                if sha_file(tmp) != want:
                    if not strict:
                        tmp.unlink(missing_ok=True)
                        break
                    raise IOError('sha256 mismatch')
                break
            except Exception as e:
                print(f'  retry {attempt + 1} {rel}: {type(e).__name__}')
                time.sleep(5 * (attempt + 1))
        else:
            tmp.unlink(missing_ok=True)
            sys.exit(f'download failed on {ad}/{rel}; nothing was replaced. Run collect again.')
        if not tmp.exists():   # not strict: the manifest did not vouch for this file
            continue
        if rel == 'jobs.jsonl' and out.exists():
            extra = local_only_lines(out.read_text(), tmp.read_text())
            if extra:   # generation was also run on the Mac meanwhile: its task ids must survive, or they are paid twice
                with tmp.open('a') as f:
                    f.write('\n'.join(extra) + '\n')
                print(f'  {ad}: kept {len(extra)} generation record(s) made on the Mac during the cloud run')
        tmp.replace(out)
        n += 1
    return n


def local_only_lines(local, cloud):
    """Lines of the Mac's jobs.jsonl that the cloud copy does not have (order kept)."""
    seen = set(cloud.splitlines())
    return [ln for ln in local.splitlines() if ln.strip() and ln not in seen]


def cloud_checks_of(st):
    """What the cloud's own final checks found for a run: None when the run had no check step, else
    {'verdict': 'PASS' | 'FAIL' | 'NOT RUN', 'fails': [...], 'fingerprint': of the checked file, 'stages': {name: rc}}."""
    row = next((x for x in (st or {}).get('steps', []) if 'checks' in x), None)
    if row is None:
        return None
    found = row.get('checks') or {}
    want = [s for s in row.get('stages', []) if s in ('rawverify', 'preflight')]
    if not found or any(s not in found for s in want):
        return {'verdict': 'NOT RUN', 'fails': [], 'fingerprint': None, 'stages': {}, 'why': str(row.get('error') or 'no result')[:200]}
    pre = found.get('preflight') or {}
    codes = {s: found[s].get('returncode') for s in want}
    fails = list(pre.get('fails') or []) + [f'FAIL {s} stopped with code {c}' for s, c in codes.items() if c != 0 and not (s == 'preflight' and pre.get('fails'))]
    ok = all(c == 0 for c in codes.values()) and ('preflight' not in want or bool(pre.get('fingerprint')))
    return {'verdict': 'PASS' if ok else 'FAIL', 'fails': fails, 'fingerprint': pre.get('fingerprint'), 'stages': codes}


def mac_fail_lines(ad):
    """The FAIL lines of the Mac's own PREFLIGHT.md (automatic checks only)."""
    f = ROOT / 'projects' / ad / 'PREFLIGHT.md'
    return [ln[2:].strip() for ln in f.read_text().splitlines() if ln.startswith('- FAIL')] if f.exists() else []


def parity_row(r, cloud, results, now=None):
    """One line for controller/check-parity.jsonl: do the cloud's checks and the Mac's say the same about this render?
    `cloud_only` are FAILs only the cloud raised (a real disagreement); `mac_only` may be the Mac-only checks (tilt, banned
    clips, plan checks), so they do not count against the cloud."""
    rule = lambda ln: ' '.join(str(ln).split()[:2])   # noqa: E731  'FAIL T09'
    ran = any(name.startswith('preflight.py') for name, _ in results)   # the Mac stops at a failed verify: no fresh PREFLIGHT.md
    mac_rules = {rule(x) for x in mac_fail_lines(r['ad'])} if ran else set()
    cloud_rules = {rule(x) for x in cloud['fails'] if not str(x).startswith('FAIL rawverify')}
    verify = dict(results).get('rawedit.py verify')
    cloud_verify = cloud['stages'].get('rawverify')
    agree = cloud['verdict'] != 'NOT RUN' and (not ran or not (cloud_rules - mac_rules)) and (
        verify is None or cloud_verify is None or (verify == 0) == (cloud_verify == 0))
    return {'at': int(now or time.time()), 'run': r['run'], 'ad': r['ad'], 'recipe': r['recipe'], 'cloud': cloud['verdict'],
            'mac': 'PASS' if all(c == 0 for _, c in results) else 'FAIL', 'agree': bool(agree),
            'cloud_only': sorted(cloud_rules - mac_rules) if ran else [], 'mac_only': sorted(mac_rules - cloud_rules), 'mac_preflight_ran': ran,
            'mac_verify': verify, 'cloud_verify': cloud_verify}


def mac_gate(ad, raw, carried=None):
    """The Mac-only final checks, one ad at a time: Apple Vision text, MLX Whisper caption timing, preflight. With
    `carried` (the cloud's video checks for this exact file, trusted by config) the Mac does only its own part."""
    proj = ROOT / 'projects' / ad
    log = proj / '.cloud' / f'mac-gate-{time.strftime("%Y%m%d-%H%M%S")}.log'
    log.parent.mkdir(exist_ok=True)
    if carried:
        steps = [['tools/preflight.py', f'projects/{ad}', '--media-from', str(carried)]]
    else:
        steps = ([['tools/rawedit.py', f'projects/{ad}', 'verify']] if raw else []) + [['tools/preflight.py', f'projects/{ad}']]
    results = []
    with log.open('w') as f:
        for cmd in steps:
            f.write(f'===== {" ".join(cmd)}\n'); f.flush()
            try:
                r = subprocess.run([MAC_PY, *cmd], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, timeout=2400)
                results.append((cmd[0].split('/')[-1] + ' ' + cmd[1 if carried else -1].split('/')[-1], r.returncode))
            except subprocess.TimeoutExpired:
                results.append((cmd[0], -9))
            if results[-1][1] != 0:
                break
    tail = log.read_text()[-1200:]
    return results, log, tail


@contextlib.contextmanager
def collect_lock():
    """One collect at a time on this Mac (a session and the watcher may both try): the second one waits its turn."""
    STATE.mkdir(exist_ok=True)
    with (STATE / 'collect.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print('another collect is running on this Mac: waiting for it to finish ...', flush=True)
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def next_step(r, st):
    """One line telling a person (or the next session) what to do with a collected run."""
    ad, recipe, state = r['ad'], r['recipe'], st.get('state')
    if state == 'blocked':
        return f'fix or acknowledge the listed shots in projects/{ad}/plan.json, then: ctl.py submit raw {ad} --go'
    if state == 'done' and recipe in P.FRAME_REVIEW:
        return (f'owner reviews the stills (projects/{ad}/REVIEW.html). Changes: ctl.py submit ai-frames-revise {ad} --redo "{ad}:<beat>:frame:<note>" --go'
                f'   Approved: ctl.py submit ai-clips {ad} --go')
    if state == 'done' and recipe == 'inserts':
        return f'the inserts are in projects/{ad}/CLIPS: place them in the real-footage plan, then submit raw'
    if state == 'done':
        return f'answer every box in projects/{ad}/PREFLIGHT.md, then tools/frameio.py push {ad} --batch "<name>"'
    if P.is_paid(recipe):
        resume = {'ai-frames': 'ai-frames', 'ai-clips': 'ai-clips', 'ai-frames-revise': None, 'ai-revise': None, 'inserts': 'inserts'}.get(recipe, 'ai-resume')
        if resume:
            return (f'read the error above. Nothing paid is lost: ctl.py submit {resume} {ad} --go continues from the saved task ids '
                    '(only what is still missing is generated)')
        done = {(int(x[0]), x[1]) for row in st.get('steps', []) for x in row.get('redos_done', [])}
        left = [x for x in r.get('redos', []) if (int(x[0]), x[1]) not in done]
        if left and len(left) < len(r.get('redos', [])):
            items = ' '.join('--redo ' + json.dumps(f'{ad}:{x[0]}:{x[1]}:{x[2]}') for x in left)
            return (f'read the error above. {len(done)} redo(s) finished and are saved: do NOT send them again (each would be paid again). '
                    f'Only the rest: ctl.py submit {recipe} {ad} {items} --go')
        return 'read the error above, then submit the redo again'
    return 'read the error above, fix it, submit again'


def collect_one(vol, r):
    """Collect one finished run: settle, download, Mac checks, record. Returns (run, state, stop message) or None
    when the run is still working."""
    stopped = None
    st = state_of(r)
    if st.get('state') not in P.TERMINAL:
        print(describe(r, st), '  (still working: skipped)')
        return None
    print(describe(r, st))
    stopped = settle_run(r, st) or stopped
    if st.get('never_started'):   # the submit died before the cloud call: nothing ran, nothing to download
        r.update(run_update(r['run'], collected=True, final_state='failed', kie_credits=0.0, collected_at=int(time.time()),
                            next=f"no cloud run was started: submit {r['ad']} again"))
        print('  no cloud run was started for this submit: closed. Submit the ad again.')
        return r, st, stopped
    kie = sum(float(x.get('kie_credits') or 0) for x in st.get('steps', []))
    ad, raw = r['ad'], r['recipe'] == 'raw'
    # always pull: a paid worker that died still checkpointed its task ids and finished files into the manifest
    n = pull(vol, ad, r['plan_sha'], strict=any(x.get('log') for x in st.get('steps', [])))
    print(f'  downloaded {n} files into projects/{ad}' + (f"; kie used {kie:.0f} of cap {r.get('kie_cap')}" if r.get('kie_cap') else ''))
    kie_log = STATE / f'kie-{datetime.date.today():%Y-%m}.jsonl'
    if r.get('kie_cap') and not (kie_log.exists() and f'"run": "{r["run"]}"' in kie_log.read_text()):   # once per run
        with kie_log.open('a') as f:
            f.write(json.dumps({'run': r['run'], 'ad': ad, 'batch': r.get('batch'), 'credits': kie, 'cap': r['kie_cap'],
                                'tasks': sum(int(x.get('kie_tasks') or 0) for x in st.get('steps', []))}) + '\n')
    check = ROOT / 'projects' / ad / 'SHOT_CHECK.json'
    if raw and check.exists():
        rows = flag_rows(json.loads(check.read_text()).get('issues', []))
        flags = ROOT / 'footage/moments/flags.jsonl'
        seen = set(flags.read_text().splitlines()) if flags.exists() else set()
        new = [json.dumps(x, sort_keys=True) for x in rows if json.dumps(x, sort_keys=True) not in seen]
        if new:
            with flags.open('a') as f:
                f.write('\n'.join(new) + '\n')
            print(f'  {len(new)} clip windows flagged for the clip search (footage/moments/flags.jsonl)')
    result = {'collected': True, 'final_state': st['state'], 'kie_credits': kie, 'collected_at': int(time.time())}
    if st['state'] == 'blocked':
        md = ROOT / 'projects' / ad / 'SHOT_CHECK.md'
        print(f'  BLOCKED before rendering ({md}):')
        print('\n'.join('    ' + ln for ln in md.read_text().splitlines() if 'BLOCK' in ln) if md.exists() else '')
    elif st['state'] == 'done' and r['recipe'] in P.FRAME_REVIEW:
        page = subprocess.run([MAC_PY, 'tools/ad.py', f'projects/{ad}', 'review'], cwd=ROOT, capture_output=True, text=True)
        result['review_page'] = 'built' if page.returncode == 0 else 'FAILED'
        print(f"  stills ready for the owner's review: projects/{ad}/REVIEW.html" + ('' if page.returncode == 0 else f' (page build failed: {page.stderr[-300:]})'))
    elif st['state'] == 'done' and r['recipe'] in ('raw', 'ai', 'ai-resume', 'ai-clips', 'ai-revise', 'ai-finish'):
        cloud = cloud_checks_of(st)
        carried = None
        if cloud:
            result['cloud_checks'] = cloud['verdict']
            print(f"  cloud final checks: {cloud['verdict']}" + (f" ({'; '.join(cloud['fails'][:4])})" if cloud['fails'] else ''))
            media = ROOT / 'projects' / ad / '.cloud' / 'media-checks.json'
            if cfg().get('trust_cloud_checks') is True and cloud['verdict'] == 'PASS' and media.exists():
                carried = media   # preflight still refuses it unless it is for this exact file, then measures everything here
        results, log, tail = mac_gate(ad, raw, carried)
        ok = all(code == 0 for _, code in results)
        result['mac_gate'] = 'PASS' if ok else 'FAIL'
        print(f"  Mac final checks{' (its own part; the video checks came from the cloud)' if carried else ''}: "
              f"{', '.join(f'{n} rc={c}' for n, c in results)} -> {'PASS' if ok else 'FAIL'} ({log})")
        if cloud and not carried:   # both measured the same render: keep the comparison, it is the proof for trusting the cloud
            row = parity_row(r, cloud, results)
            with (STATE / 'check-parity.jsonl').open('a') as f:
                f.write(json.dumps(row) + '\n')
            if not row['agree']:
                print(f"  NOTE: the cloud's checks and the Mac's differ (cloud only: {row['cloud_only']}, rawedit verify cloud {row['cloud_verify']} / Mac {row['mac_verify']}). The Mac's result counts.")
        if not ok:
            print('\n'.join('    ' + ln for ln in tail.splitlines()[-12:]))
    elif st['state'] in ('failed', 'crashed'):
        last = (st.get('steps') or [{}])[-1]
        print('    ' + str(last.get('tail') or last.get('error') or st.get('error') or '')[-700:].replace('\n', '\n    '))
    result['next'] = next_step(r, st)
    print('  next: ' + result['next'])
    r.update(run_update(r['run'], **result))
    return r, st, stopped


def collect(args, quiet_empty=False):
    import modal
    todo = pick_runs(args, runs_load())
    if not todo:
        if not quiet_empty:
            print('nothing to collect (the watcher collects finished runs on its own: see `ctl.py history` for results and next steps)')
        return []
    done = []
    with collect_lock():
        vol = modal.Volume.from_name(VOLUME, create_if_missing=True)
        ledger(); stopped = None
        live = runs_load()   # another collect may have taken some of these while we waited for the lock
        for r in sorted((live[x['run']] for x in todo if x['run'] in live and not live[x['run']].get('collected')), key=lambda r: r['submitted']):
            try:
                got = collect_one(vol, r)
            except (SystemExit, Exception) as e:   # one ad's download or checks failing must not stop the others
                print(f"  {r['ad']}: NOT collected ({type(e).__name__}: {str(e)[:300]}). It stays open; run collect again.")
                continue
            if got:
                stopped = got[2] or stopped
                done.append(got[:2])

    if stopped:
        print(f'GLOBAL STOP (tell the owner: the monthly Modal limit was reached or a paid worker crashed): {stopped}. '
              'No new cloud work until a person lifts it (cloud/controller/GLOBAL_STOP.json).')
    if done:
        board_refresh()
    return done


def summary_line(r, st):
    state = st.get('state')
    word = ('stills ready for your review' if state == 'done' and r['recipe'] in P.FRAME_REVIEW else
            f"finished, Mac checks {r.get('mac_gate')}" if state == 'done' and r.get('mac_gate') else
            'finished' if state == 'done' else 'blocked by the shot check' if state == 'blocked' else 'FAILED')
    return f"{r['ad']} ({r['recipe']}): {word}"


def notify(text):
    """Slack DM to the owner through bin/slack-post (it adds the @-mention). Silent when slack_user_id is empty."""
    user = str(cfg().get('slack_user_id') or '').strip()
    if not user or not SLACK_POST.exists():
        return False
    try:
        return subprocess.run([sys.executable, str(SLACK_POST), user, '-'], input=text, text=True, capture_output=True, timeout=120).returncode == 0
    except Exception:
        return False


def notify_queued(text=None):
    """Post a Slack note; a note that could not be posted is kept and tried again on the next pass (oldest first)."""
    queue = STATE / 'slack-unsent.jsonl'
    if not str(cfg().get('slack_user_id') or '').strip() or not SLACK_POST.exists():
        return False   # Slack is switched off: nothing is queued
    pending = [json.loads(ln) for ln in queue.read_text().splitlines() if ln.strip()] if queue.exists() else []
    if text:
        pending.append({'at': int(time.time()), 'text': text})
    while pending and notify(pending[0]['text']):
        pending.pop(0)
    if pending:
        queue.write_text('\n'.join(json.dumps(x) for x in pending[-50:]) + '\n')
    else:
        queue.unlink(missing_ok=True)
    return not pending


def board_refresh(rows=None, quiet=True, thumb_budget=8):
    """Rewrite the ad board page (cloud/dash.py). It is only a view: a failure here never stops controller work."""
    try:
        import dash
        if rows is not None:   # the run registry may have moved on (collect) since `rows` was read: keep open runs only
            open_now = {k for k, r in runs_load().items() if not r.get('collected')}
            rows = [(r, st) for r, st in rows if r['run'] in open_now]
        return dash.write(rows, thumb_budget=thumb_budget, usage_scan=1.5)
    except Exception as e:
        if not quiet:
            print(f'ad board not updated: {type(e).__name__}: {e}')


def usage_cmd(args):
    """`ctl.py usage`: rebuild the usage page (cost per batch, revision rounds, make time, live kie balance) and open it.
    `--index` reads every Claude transcript once (minutes, the first time); `--archive` takes in the kie records of the
    projects archived to iCloud; `--verify` checks every logged kie task against kie's own record (free reads, a few
    minutes the first time; each rebuild checks the new ones by itself); `--no-open` only rewrites the page."""
    import usage
    board_helper(quiet=True)
    if '--archive' in args:
        got = usage.take_in_archive()
        print('the iCloud archive did not answer in time: try again later' if got is None
              else f'archive: {got[0]} kie tasks ({got[2]:,.0f} credits) and {got[1]} ads added')
    if '--verify' in args:
        done, left, failed = usage.verify()
        print(f'checked against kie: {done} tasks' + (f', {left} still to check (run it again)' if left else '') + (f', {failed} lookups failed' if failed else ''))
    page = usage.write(scan=None if '--index' in args else 20.0, max_age=0)
    data = usage.gather(max_age=600)
    bal, left = data['bal'], (data['claude'].get('pending') or 0) / 1e9
    print(f"kie balance: {bal['credits']:,.0f} credits" if bal.get('credits') is not None else f"kie balance not read ({bal.get('error')})")
    a = data.get('audit') or {}
    print(f"kie tasks: {a.get('tasks', 0):,} ({a.get('credits', 0):,.0f} credits), {a.get('checked', 0):,} checked against kie's own record"
          + (f", {a['waiting']:,} waiting (ctl.py usage --verify)" if a.get('waiting') else '')
          + (f", {a['differ']} differed from the log by {a['differ_credits']:+,.1f} credits in all" if a.get('differ') else ''))
    if left:
        print(f'Claude transcripts still to read: {left:.1f} GB (ctl.py usage --index reads them all)')
    print(page)
    if '--no-open' not in args:
        subprocess.run(['open', str(page)])
        return None


def board_helper(quiet=True):
    """Keep the board's small local helper running (cloud/frame_review.py): it is what saves the owner's frame approvals
    when he presses the button. Never started from a test run; a failure here never stops controller work."""
    if os.environ.get('PP_NO_BOARD_HELPER') or 'unittest' in sys.modules:
        return None
    try:
        import frame_review
        state = frame_review.ensure()
    except Exception as e:
        state = f'failed ({type(e).__name__})'
    if not quiet or state.startswith('failed'):
        print(f'board helper: {state}')
    return state


def reviews_cmd(args):
    """`ctl.py reviews`: the owner's frame decisions that still wait for a session. `--done <ad>` marks one handled."""
    import frame_review
    for flag, state in (('--working', 'working'), ('--revised', 'done')):
        if flag in args:   # a session took / finished a "Revisions done" batch
            for b in [a for a in args if not a.startswith('--')]:
                busy = job_note(b)
                if state == 'working' and 'IS WORKING ON IT' in busy:   # two Claudes on one batch would undo each other
                    print(f'{b}:{busy}')
                    continue
                try:
                    got = frame_review.mark_revisions(b, state)
                    if state == 'done' and got.get('state') == 'waiting':   # he sent more videos while this round was running
                        print(f"{b}: this round is done. The owner sent more videos of this batch meanwhile ({', '.join(got.get('ads') or [])}): "
                              'they are the next round, and the watcher starts a Claude job on them.')
                    else:
                        print(f'{b}: revisions {state}')
                except ValueError as e:
                    print(e)
            board_refresh()
            return
    if '--done' in args:
        for ad in [a for a in args if not a.startswith('--')]:
            done = frame_review.mark_handled(ad)
            pk = frame_review.picks_of(frame_review.ROOT / 'projects' / ad)
            if pk:
                pk['handled_at'] = time.time()
                (frame_review.ROOT / 'projects' / ad / 'OPTIONS_PICK.json').write_text(json.dumps(pk, indent=1))
            print(f'{ad}: ' + ('marked as dealt with' if done or pk else 'no decision on file'))
        board_refresh()
        return
    for ad, d in frame_review.pending_picks():
        print(f"{ad}: CLIP PICKS by the owner {time.strftime('%m-%d %H:%M', time.localtime(d['sent_at']))}")
        for x in d['slots']:
            print(f"  {x['slot']}: " + (x['pick_name'] or 'none of these') + (f" — {x['note']}" if x['note'] else '') + (f"  ({x['pick_file']})" if x['pick_file'] else ''))
            for k, v in x['notes'].items():
                print(f'    note on {k}: {v}')
        print(f'  next: use the pick in the ad (no need to ask him again), then mark it: ctl.py reviews --done {ad}')
    handoff = revision_rows() + delivery_rows()
    for line in handoff:
        print(line)
    rows = frame_review.pending()
    if not rows and not frame_review.pending_picks() and not handoff:
        print('no frame decisions, clip picks or Drive hand-offs are waiting')
    for ad, d in rows:
        auto = d.get('follow_up') or {}
        print(f"{ad}: {d['verdict'].upper()} by the owner {time.strftime('%m-%d %H:%M', time.localtime(d['sent_at']))} (from the {d.get('source')})")
        print('  ' + frame_review.text_form(d).strip().replace('\n', '\n  '))
        if auto:
            print(f"  started by itself: {auto.get('cmd')} -> " + ('still starting' if auto.get('exit') is None else f"exit {auto.get('exit')}: {auto.get('tail', '')[-300:]}"))
        elif d['verdict'] == 'approved':
            print(f'  next: build the clips for {ad} (no need to ask him again), then `ctl.py reviews --done {ad}` if clips do not land in CLIPS/')
        else:
            print(f'  next: redo what he asked, rebuild the page (tools/ad.py projects/{ad} review); new frames clear this by themselves')


def revision_rows():
    """Batches where the owner pressed "Revisions done" on the board and no new version is up yet."""
    try:
        import frame_review
        reqs = frame_review.revision_requests()
    except Exception:
        return []
    out = []
    for b, r in sorted(reqs.items()):
        if r.get('state') not in ('pulling', 'waiting', 'working'):
            continue
        notes = {a: n for a, n in (r.get('notes') or {}).items() if a in (r.get('ads') or [a])}   # only the videos he sent
        when = time.strftime('%m-%d %H:%M', time.localtime(r.get('pressed_at') or 0))
        busy = job_note(b)
        if 'IS WORKING ON IT' in busy:
            out.append(f"{b}: REVISIONS DONE pressed by the owner {when} ({r['state']}).{busy}")
            continue
        out.append(f"{b}: REVISIONS DONE pressed by the owner {when} ({r['state']}) - "
                   + (', '.join(f'{a} {n} note(s)' for a, n in notes.items()) or 'notes still being pulled')
                   + (f"; could not pull: {r.get('errors')}" if r.get('errors') else '') + busy
                   + f"\n  next: `ctl.py reviews --working \"{b}\"`, read the notes (feedback/log.jsonl, src frameio, or "
                   f"`.venv/bin/python tools/frameio.py pull <ad> --dry`), apply them to the videos listed here only (the ones he sent: the batch button leaves approved videos out, "
                   f"the row button sends one video; never revise an approved video), preflight, push each "
                   f"new version; the board clears each ad when its new version is up, then `ctl.py reviews --revised \"{b}\"`. Do not ask him again.")
    return out


def delivery_rows():
    """Drive hand-offs (cloud/deliver.py) that need a session: a stopped upload, or a batch he ticked as in the media buyer
    sheet whose Drive files still carry working names (rename them to his Ad Name, then `deliver.py --renamed "<batch>"`)."""
    try:
        import deliver
        recs = deliver.records()
    except Exception:
        return []
    out = []
    for b, r in sorted(recs.items()):
        if r.get('state') == 'failed':
            out.append(f"{b}: DRIVE UPLOAD STOPPED: {r.get('error')}\n  next: fix it, then `{MODAL_PY} cloud/deliver.py \"{b}\"` (the board's Try again does the same)")
        elif r.get('state') == 'delivered' and r.get('in_sheet') and not r.get('renamed'):
            out.append(f"{b}: in the media buyer sheet, Drive files not renamed yet ({r.get('url')})\n"
                       f"  next: read his Ad Name for this link in the naming sheet (read only), rename the folder and files to it "
                       f"(GOOGLEDRIVE_UPDATE_FILE_METADATA_PATCH, field 'title'), then `{MODAL_PY} cloud/deliver.py --renamed \"{b}\"`")
        elif r.get('state') == 'delivered' and not r.get('frameio_cleaned', True):
            out.append(f"{b}: on Drive but still on Frame.io (clean failed)\n  next: `.venv/bin/python tools/frameio.py clean {(r.get('ads') or ['?'])[0]}`")
    return out


def frame_decisions_line():
    """One line for `status`, so every session sees a waiting approval without being told."""
    try:
        import frame_review
        rows = frame_review.pending()
    except Exception:
        return None
    stopped = [b for b, r in __import__('deliver').records().items() if r.get('state') == 'failed']
    revise = [b for b, r in frame_review.revision_requests().items() if r.get('state') in ('pulling', 'waiting', 'working')]
    parts = ([f'{b} REVISIONS DONE (' + ('an unattended Claude job is on it: leave it' if 'IS WORKING ON IT' in job_note(b) else 'apply his Frame.io notes now') + ')'
              for b in revise] + [f"{ad} {d['verdict']}" for ad, d in rows]
             + [f'{b} Drive upload stopped' for b in stopped])
    return ('OWNER DECISIONS WAITING (ctl.py reviews): ' + ', '.join(parts)) if parts else None


def dash_cmd(args):
    """`ctl.py dash`: refresh the ad board with live cloud step detail and open it. `--no-open` only rewrites it.
    `--hide "<ad or batch>" ...` takes ads off the board, `--unhide ...` puts them back, `--hidden` lists them."""
    import dash
    names = [a for a in args if not a.startswith('--')]
    if '--hide' in args or '--unhide' in args:
        if not names:
            sys.exit('name the ad(s) or batch(es): ctl.py dash --hide "<ad or batch>"')
        dash.hide(names, on='--hide' in args)
    if '--hidden' in args or '--hide' in args or '--unhide' in args:
        off = dash.hidden()
        print('hidden ads: ' + (', '.join(off['ads']) or 'none'))
        print('hidden batches: ' + (', '.join(off['batches']) or 'none'))
    rows = None
    try:
        rows = status([], quiet=True)
    except BaseException as e:   # no network / no Modal login: the page still shows everything that is on the Mac
        if isinstance(e, KeyboardInterrupt):
            raise
        print(f'(cloud not reachable right now, showing what is on this Mac: {type(e).__name__})')
    board_helper(quiet=False)
    page = board_refresh(rows, quiet=False, thumb_budget=60)
    if page:
        print(page)
        if not {'--no-open', '--hide', '--unhide', '--hidden'} & set(args):
            subprocess.run(['open', str(page)])


def watch_pass():
    """One look at the cloud: collect what finished, tell the owner, refresh the dashboard. Returns open runs left."""
    notify_queued()
    rows = status([], quiet=True)
    if any(st.get('state') in P.TERMINAL for _, st in rows):
        done = collect([], quiet_empty=True)
        if done:
            by_batch = {}
            for r, st in done:
                by_batch.setdefault(r.get('batch') or 'no name', []).append(summary_line(r, st))
            still = sum(1 for r in runs_load().values() if not r.get('collected'))
            lines = ['Cloud ads collected on the Mac:']
            for batch, items in by_batch.items():
                lines += [f'*{batch}*'] + [f'  - {x}' for x in items]
            lines.append(f'{still} run(s) still working in the cloud.' if still else 'Nothing else is running in the cloud.')
            print('\n'.join(lines))   # no Slack note per collect (only the 16 h waiting reminder)
    stop, told = STATE / 'GLOBAL_STOP.json', STATE / 'stop-notified'
    if stop.exists() and (not told.exists() or told.read_text() != str(stop.stat().st_mtime_ns)):
        why = stop.read_text()[:400]
        print(f'GLOBAL STOP is set: {why}')
        notify_queued(f'Cloud ad controller STOPPED (no new cloud work until someone lifts it): {why}')
        told.write_text(str(stop.stat().st_mtime_ns))
    (STATE / 'watch-heartbeat').write_text(str(int(time.time())))
    auto_push()
    claude_sweep()
    remind_waiting()
    board_refresh(rows)
    return sum(1 for r in runs_load().values() if not r.get('collected'))


def auto_push():
    """Finished, checked ads go to Frame.io with no one asking. Every ad the board shows as
    'Uploading next' (finished, preflight run on THIS file, every box answered, no FAIL) is pushed by the watcher.
    frameio.py push keeps its own gate, so nothing unchecked can go up. One try per render (file size + mtime):
    a refused push is reported once on Slack, not retried every pass. `"auto_push": false` in config.json turns it off."""
    if not cfg().get('auto_push', True):
        return []
    try:
        import dash
        cards = dash.gather(thumbs=False)['cards']
    except Exception as e:
        print(f'auto-push: board not readable ({type(e).__name__}: {e})')
        return []
    seen_f = STATE / 'autopush.json'
    seen = json.loads(seen_f.read_text()) if seen_f.exists() else {}
    pushed, refused = [], []
    for c in cards:
        if c.get('tab') != 'prep' or c.get('status') != 'Uploading next':
            continue
        ad, m = c['ad'], ROOT / 'projects' / c['ad'] / 'MASTER.mp4'
        if not m.exists():
            continue
        key = f'{m.stat().st_size}:{int(m.stat().st_mtime)}'
        if seen.get(ad) == key:
            continue
        seen[ad] = key
        seen_f.write_text(json.dumps(seen, indent=1))
        cmd = [MAC_PY, 'tools/frameio.py', 'push', ad] + (['--batch', c['batch']] if c.get('batch') else [])
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)
        out = (r.stdout + r.stderr).strip().splitlines()
        link = next((l for l in reversed(out) if l.startswith('https://')), '')
        if r.returncode == 0 and link:
            pushed.append(f'  - {ad}: {link}')
        else:
            refused.append(f'  - {ad}: {(out[-1] if out else "no output")[:200]}')
    if pushed or refused:
        msg = []
        if pushed:
            msg += ['Pushed to Frame.io for your review:'] + pushed
        if refused:
            msg += ['Could not push (a Claude session fixes it):'] + refused
        print('\n'.join(msg))   # no Slack note; the board shows it
    return pushed


def claude_sweep(dry=False):
    """Revisions and stopped checks must not wait for an open Claude session. Every watcher pass starts
    (or starts again) the unattended Claude job of each batch that waits for one: cloud/claude_job.py sweep(). A batch an
    open session is busy on is left alone; `"claude_auto": false` in config.json switches it off. Never from a test run."""
    if os.environ.get('PP_NO_CLAUDE_JOBS') or 'unittest' in sys.modules:
        return []
    try:
        import claude_job
        import dash
        import frame_review
        if not claude_job.enabled():
            return []
        got = claude_job.sweep(dash.gather(thumbs=False)['cards'], dry=dry, spawn=claude_job.spawn_runner, mark=frame_review.mark_revisions)
    except Exception as e:   # the watcher's collecting must never stop because of this
        print(f'claude jobs: not looked at ({type(e).__name__}: {e})')
        return []
    for key, kind, result in got:
        print(time.strftime('[%m-%d %H:%M:%S] ') + f'claude job ({kind}) for "{key}": {result}', flush=True)
    return got


def jobs_cmd(args):
    """`ctl.py jobs`: the unattended Claude jobs. `--sweep` starts what waits now, `--dry` only says what would start."""
    import claude_job
    if '--sweep' in args or '--dry' in args:
        got = claude_sweep(dry='--dry' in args)
        if not got:
            print('nothing waits for a Claude job' + ('' if claude_job.enabled() else ' ("claude_auto" is false in cloud/controller/config.json)'))
        board_refresh()
    print('\n'.join(claude_job.status_lines()) or 'no Claude jobs on record')


def job_note(key):
    """' An unattended Claude job is on it ...' for status / reviews, so an open session does not start on the same batch."""
    try:
        import claude_job
        rec = claude_job.record(key)
        if os.environ.get('PP_CLAUDE_JOB') == key:   # the job itself is reading this
            return ''
        if rec and claude_job.live(key):
            return (f" AN UNATTENDED CLAUDE JOB IS WORKING ON IT (started {time.strftime('%H:%M', time.localtime(rec.get('started_at') or rec.get('asked_at') or 0))}, "
                    f"log {rec.get('log')}): leave this batch to it.")
        if rec and rec.get('state') == 'blocked':
            return f" The unattended Claude job stopped and needs the owner: {rec.get('blocked')}"
    except Exception:
        pass
    return ''


def remind_waiting():
    """The only Slack DM besides a GLOBAL STOP. When an ad has sat in a 'waiting for you' state
    (frames/clip picks, ready to review on Frame.io, tick in the sheet) untouched for `remind_after_h` hours (16),
    send one reminder listing every such ad; again every 16 h while it still waits. Any change of state resets it."""
    hours = float(cfg().get('remind_after_h', 16))
    try:
        import dash
        cards = dash.gather(thumbs=False)['cards']
    except Exception as e:
        print(f'reminder: board not readable ({type(e).__name__}: {e})')
        return []
    f = STATE / 'waiting.json'
    old = json.loads(f.read_text()) if f.exists() else {}
    now, new, due = time.time(), {}, []
    for c in cards:
        if c.get('tone') != 'you':
            continue
        key, state = c['ad'], f"{c.get('tab')}|{c.get('status')}"
        rec = old.get(key) if (old.get(key) or {}).get('state') == state else {'state': state, 'since': now, 'reminded': 0}
        if now - rec['since'] >= hours * 3600 and now - rec.get('reminded', 0) >= hours * 3600:
            link = (c.get('action') or [None, None])[1] or ''
            due.append(f"  - {c.get('title') or key} ({c.get('status')}, waiting {int((now - rec['since']) // 3600)} h) {link}".rstrip())
            rec['reminded'] = now
        new[key] = rec
    f.write_text(json.dumps(new, indent=1))
    if due:
        notify_queued('Reminder: these have been waiting on you for 16+ hours:\n' + '\n'.join(due))
    return due


def watch(args):
    """Collect whatever has finished, tell the owner on Slack, repeat. `--once` (the launchd job, every 10 minutes)
    does not stop after one look while runs are open: it keeps looking every `watch_fast_s` seconds for up to
    `watch_linger_s`, so a finished ad is collected within about a minute instead of up to ten."""
    began, c, said = time.monotonic(), cfg(), False
    board_helper()
    while True:
        left = 0
        try:
            left = watch_pass()
            if left and not said:   # one dated line per watcher start that found work, so the log can be read later
                print(time.strftime('[%m-%d %H:%M:%S] ') + f'watching {left} open run(s)', flush=True)
                said = True
        except SystemExit as e:
            print(f'watch: {e}')
        except Exception as e:   # a network blip must not kill the watcher
            print(f'watch: {type(e).__name__}: {e}')
        if '--once' in args:
            if not left or time.monotonic() - began > int(c.get('watch_linger_s', 540)):
                return
            time.sleep(int(c.get('watch_fast_s', 45)))
        else:
            time.sleep(int(c.get('watch_fast_s', 45)) if left else int(c.get('watch_every_s', 300)))


def revise_plan(args):
    """Open owner notes (Frame.io comments, review-page notes and chat notes in the feedback log) -> a batch file
    skeleton. Each timed note is matched to the beat (AI ad) or shot (real footage) on screen at that second. A person
    or Claude session then decides the fix for each note (fill "redo" / edit plan.json shots), sets "skip": false and
    runs `submit --from <file> --go`. Review-page notes that already say redo-frame / redo-clip are pre-filled."""
    sys.path.insert(0, str(ROOT / 'tools'))
    import feedback as fb
    names = [a for a in args if not a.startswith('--')]
    by_ad = {}
    for r in fb.read_log():
        if r.get('status') == 'open' and (not names or r.get('ad') in names):
            by_ad.setdefault(r.get('ad'), []).append(r)
    jobs = []
    for ad, notes in sorted(by_ad.items(), key=lambda kv: str(kv[0])):
        proj = ROOT / 'projects' / str(ad)
        if not (proj / 'plan.json').exists():
            continue
        plan = json.loads((proj / 'plan.json').read_text())
        if plan.get('locked'):
            continue
        raw = bool(plan.get('shots'))
        frame_stage = not raw and not any((proj / 'CLIPS').glob('clip_*.mp4'))   # still in the starting-frame review
        items, redo = [], []
        for n in notes:
            t = n.get('time')
            place = ('beat', n['beat'], '') if n.get('beat') else time_to_place(plan, float(t)) if isinstance(t, (int, float)) else None
            items.append({'id': n.get('id'), 'at': t, 'where': f'{place[0]} {place[1]}: {place[2]}'.strip(': ') if place else 'whole ad',
                          'note': n.get('text')})
            what = 'frame' if frame_stage or 'frame' in str(n.get('decision')) else 'clip' if 'clip' in str(n.get('decision')) else None
            if not raw and place and place[0] == 'beat' and what and (frame_stage or n.get('decision')):
                redo.append([place[1], what, re.sub(r'^\[[^\]]*\]\s*', '', str(n.get('text') or ''))[:600]])
        job = {'ad': ad, 'recipe': 'raw' if raw else 'ai-frames-revise' if frame_stage else 'ai-revise', 'notes': items, 'skip': True}
        if not raw:
            job['redo'] = redo
        job['_how'] = ('real footage: change the named shots in plan.json, then set "skip": false' if raw else
                       'check / fill "redo" with [beat, "frame"|"clip", "what to change"] for each note, then set "skip": false '
                       '(caption / music / text-only notes: change plan.json and use recipe "ai-finish" instead)')
        jobs.append(job)
    out = STATE / f'revise-{time.strftime("%Y%m%d-%H%M%S")}.json'
    STATE.mkdir(exist_ok=True)
    out.write_text(json.dumps({'batch': f'revisions {time.strftime("%m-%d %H.%M")}', 'jobs': jobs}, indent=1) + '\n')
    for j in jobs:
        print(f"{j['ad']} ({j['recipe']}): {len(j['notes'])} open note(s)" + (f", {len(j['redo'])} redo(s) pre-filled" if j.get('redo') else ''))
        for it in j['notes']:
            when = f"@{it['at']}s " if it['at'] is not None else ''
            print(f"   #{it['id']} {when}[{it['where'][:70]}] {str(it['note'])[:110]}")
    print(f'\n{len(jobs)} ad(s) with open notes -> {out}\nDecide each fix in that file, set "skip": false, then: ctl.py submit --from {out} --go')
    return out


def history(args):
    n = int(args[0]) if args and args[0].isdigit() else 20
    rows = sorted((r for r in runs_load().values() if r.get('collected')), key=lambda r: r['submitted'])[-n:]
    for r in rows:
        when = time.strftime('%m-%d %H:%M', time.localtime(r['submitted']))
        print(f"{when}  {(r.get('batch') or '-')[:24]:24s} {r['run']:44s} {str(r.get('final_state')).upper():8s}"
              + (f" Mac checks {r['mac_gate']}" if r.get('mac_gate') else '') + (f" kie {r['kie_credits']:.0f}" if r.get('kie_credits') else ''))
        if r.get('next') and '--next' in args:
            print(f"      next: {r['next']}")


def main():
    a = sys.argv[1:]
    if not a or a[0] in ('-h', '--help', 'help'):
        sys.exit(__doc__)
    cmd, rest = a[0], a[1:]
    if cmd == 'submit' and (len(rest) >= 2):
        submit(rest)
    elif cmd == 'status':
        status(rest)
        line = frame_decisions_line()
        if line:
            print(line)
    elif cmd == 'wait':
        wait(rest)
    elif cmd == 'collect':
        collect(rest)
    elif cmd == 'watch':
        watch(rest)
    elif cmd == 'revise-plan':
        revise_plan(rest)
    elif cmd == 'history':
        history(rest)
    elif cmd == 'dash':
        dash_cmd(rest)
    elif cmd == 'usage':
        usage_cmd(rest)
    elif cmd == 'reviews':
        reviews_cmd(rest)
    elif cmd == 'jobs':
        jobs_cmd(rest)
    elif cmd == 'assets' and rest:
        print('\n'.join(assets_of(rest[0])))
    elif cmd == 'notes':
        subprocess.run([MAC_PY, 'tools/frameio.py', 'pull', '--all'], cwd=ROOT)
        subprocess.run([MAC_PY, 'tools/feedback.py', 'open'], cwd=ROOT)
    elif cmd == 'migrate':
        import modal
        guard()
        budget, key, t0 = ledger(), f'admin-migrate-{int(time.time())}', time.monotonic()
        budget.reserve(key, str(bound('admin')), 'function', {'family': 'ads-admin', 'paid_call': False, 'diagnostic_only': True})
        try:
            print(modal.Function.from_name(APP, 'admin').remote('migrate'))
        finally:
            wall = time.monotonic() - t0
            budget.finish(key, 'DONE', str(min((D(str(wall)) + 40) * unit('admin'), bound('admin')).quantize(D('.0001'))), wall)
    elif cmd == 'deploy':
        sys.exit(subprocess.run([MODAL_PY, '-m', 'modal', 'deploy', 'controller/app.py'], cwd=C).returncode)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
