"""Unattended Claude jobs on this Mac: the owner presses "Revisions done" (or a finished ad stops at a check) and a
headless Claude does the work, with no Claude session open.

  the board helper (cloud/frame_review.py) and the watcher (ctl.py watch) call start() / sweep()
        -> one detached runner process per batch: `claude_job.py run "<batch>"`
        -> `claude -p <the job prompt>` on the owner's Claude login (his plan; never the paid API key)
        -> record  cloud/controller/claude-jobs/<batch>.json      what is running, since when, how it ended
           lock    cloud/controller/claude-jobs/<batch>.lock      held by the runner: ONE Claude job per batch
           log     cloud/.scratch/claude-jobs/<batch>-<time>.log  everything Claude did (stream-json lines)

  .modal-env/bin/python cloud/claude_job.py status                 # every job: running / done / failed / blocked
  .modal-env/bin/python cloud/claude_job.py start "<batch>"         # start the revision job of a batch by hand
  .modal-env/bin/python cloud/claude_job.py stop "<batch>"          # stop a running job
  .modal-env/bin/python cloud/claude_job.py blocked "<batch>" "<why, in plain words>"   # the job itself: it needs the owner
  .modal-env/bin/python cloud/claude_job.py sweep [--dry]           # what the watcher does every pass
  .modal-env/bin/python cloud/claude_job.py smoke                  # a one-command test job: proves Claude can start unattended

The board reads work() to say what is true: a live job, activity seen from another session, or
"Stalled — no Claude working on it" when nothing has moved for `claude_stall_min` minutes (30).

Settings (cloud/controller/config.json, else config.example.json; every key is optional):
  claude_auto            true   false switches every automatic start off (the board still tells the truth)
  claude_auto_from       epoch  finished ads that stop at a check are only picked up when they were made after this moment
  claude_stall_min       30     minutes without any activity before a batch counts as stalled / is taken over
  claude_job_timeout_s   10800  a job is stopped after this long
  claude_job_tries       3      automatic starts per "Revisions done" press
  claude_max_jobs        2      jobs running at the same time
  claude_job_paid        false  true lets a job start paid redos (kie credits) his notes ask for, inside kie_cap_per_ad;
                                false: it does every free fix and reports the paid ones on the board for the owner's OK
  claude_job_model / claude_job_effort   unset: the owner's own Claude Code defaults (Opus, medium)
Stdlib only, so the helper can import it on any of the Mac's Pythons.
"""
import calendar
import fcntl
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

C = pathlib.Path(__file__).resolve().parent
if str(C) not in sys.path:
    sys.path.insert(0, str(C))
import names  # noqa: E402

ROOT = C.parent
STATE = C / 'controller'
LOGS = C / '.scratch' / 'claude-jobs'
MODAL_PY = os.environ.get('MODAL_PYTHON') or sys.executable   # the Python that has `modal` (runs cloud/ctl.py)
TRANSCRIPTS = pathlib.Path.home() / '.claude' / 'projects'
DEFAULTS = {'claude_auto': True, 'claude_auto_from': None, 'claude_stall_min': 30, 'claude_job_timeout_s': 3 * 3600,
            'claude_job_tries': 3, 'claude_max_jobs': 2, 'claude_job_model': None, 'claude_job_effort': None, 'claude_job_paid': False}
ACTIVE = ('pulling', 'waiting', 'working')        # a "Revisions done" request somebody still has to finish
FIX_STATUS = ('Claude to fix', 'Final checks')    # board rows that wait for a Claude with nobody asking
TAIL = 1_000_000                                  # bytes read from the end of each recently written session transcript
OWNER_FILES = {'.DS_Store', 'APPROVED.json', 'APPROVED.log.jsonl', 'FRAME_REVIEW.json', 'FRAME_REVIEW.log.jsonl', 'FRAME_REVIEW.txt',
               'OPTIONS_PICK.json', 'OPTIONS_PICK.log.jsonl'}   # written by the owner's button presses, not by a Claude at work
PATH = f"{pathlib.Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
NO_API = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_SIMPLE', 'CLAUDE_CODE_USE_BEDROCK',
          'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY')   # the job runs on the owner's Claude login, never a paid key


def load(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return default


def cfg():
    return {**DEFAULTS, **names.config(STATE)}


def enabled():
    return bool(cfg().get('claude_auto'))


FIX_PREFIX = 'fix: '   # a fix job's key is never a batch's own name: that name belongs to the batch's revision job


def fix_key(name):
    return FIX_PREFIX + str(name)


def slug(key):
    key = str(key)
    if key.startswith(FIX_PREFIX):   # '@' never comes out of a plain name, so the two kinds cannot share a record file
        return 'fix@' + slug(key[len(FIX_PREFIX):])
    return re.sub(r'[^A-Za-z0-9._-]+', '-', key).strip('-')[:80] or 'job'


def batch_busy(batch, reqs=None, runs=None):
    """Why a finished ad of this batch is NOT ours to pick up ('' when it is free): somebody still has the batch's
    "Revisions done" request (a Claude session or the batch's own revision job), or a cloud run of the batch is open.
    Counted by the batch NAME, so a hook that was never on Frame.io is covered too (a hook
    that is not in the request's ad list still belongs to the session revising its batch)."""
    if not batch:
        return ''
    reqs = reqs if reqs is not None else (load(STATE / 'revision-requests.json', {}) or {})
    if (reqs.get(batch) or {}).get('state') in ACTIVE:
        return 'its batch is being revised'
    runs = runs if runs is not None else (load(STATE / 'runs.json', {}) or {})
    if any(r.get('batch') == batch and not r.get('collected') for r in runs.values()):
        return 'a cloud run of its batch is open'
    return ''


def record(key):
    return load(STATE / 'claude-jobs' / f'{slug(key)}.json')


def records():
    folder = STATE / 'claude-jobs'
    return [r for r in (load(f) for f in sorted(folder.glob('*.json'))) if isinstance(r, dict)] if folder.is_dir() else []


def save(key, **fields):
    """Merge fields into the job's record (the runner, the helper and the job itself may all write)."""
    folder = STATE / 'claude-jobs'
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / '.records.lock', 'a') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        rec = {**(record(key) or {}), **fields, 'key': key}
        tmp = folder / f'{slug(key)}.json.part'
        tmp.write_text(json.dumps(rec, indent=1))
        tmp.replace(folder / f'{slug(key)}.json')
        return rec


def lock_path(key):
    return STATE / 'claude-jobs' / f'{slug(key)}.lock'


def live(key):
    """True while a runner holds this batch's lock (the lock dies with the process, so a crashed job never looks alive)."""
    f = lock_path(key)
    if not f.exists():
        return False
    with open(f, 'a') as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(lk, fcntl.LOCK_UN)
    return False


# ---- is anybody working on these ads? ---------------------------------------------------------------------------------

def newest_file(folder, depth=2):
    """Newest change inside a project folder (two levels: plan.json, PREFLIGHT.md, EDIT_KIT/, SEGMENTS/, .cloud/ ...)."""
    best = 0.0
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return best
    for e in entries:
        if e.name in OWNER_FILES:
            continue
        try:
            if e.is_dir(follow_symlinks=False):
                if depth > 1:
                    best = max(best, newest_file(e.path, depth - 1))
            else:
                best = max(best, e.stat(follow_symlinks=False).st_mtime)
        except OSError:
            pass
    return best


_SESSIONS = {}   # one read of the recent session tails serves every batch on the board for a few seconds


def recent_sessions(since):
    """[(when, tool call text)]: every tool call a Claude Code session (an open one, a subagent, one of our jobs) made
    after `since`, read from the tail of each transcript that was written after `since`."""
    key = (str(TRANSCRIPTS), int(since // 60), int(time.time() // 15))
    if key in _SESSIONS and 'unittest' not in sys.modules:
        return _SESSIONS[key]
    out = []
    for folder, _, files in os.walk(TRANSCRIPTS) if TRANSCRIPTS.is_dir() else []:
        for name in files:
            if not name.endswith('.jsonl'):
                continue
            path = os.path.join(folder, name)
            try:
                st = os.stat(path)
                if st.st_mtime <= since:
                    continue
                with open(path, 'rb') as f:
                    f.seek(max(0, st.st_size - TAIL))
                    lines = f.read().split(b'\n')
            except OSError:
                continue
            for line in lines:
                if b'"tool_use"' not in line:
                    continue
                try:
                    d = json.loads(line)
                    if d.get('type') != 'assistant':
                        continue
                    try:
                        when = calendar.timegm(time.strptime(str(d.get('timestamp'))[:19], '%Y-%m-%dT%H:%M:%S'))
                    except ValueError:
                        when = st.st_mtime
                    if when <= since:
                        continue
                    for block in d['message']['content']:
                        if block.get('type') == 'tool_use':
                            out.append((float(when), json.dumps(block.get('input'))))
                except (ValueError, KeyError, TypeError, AttributeError):
                    continue
    _SESSIONS.clear()
    _SESSIONS[key] = out
    return out


def session_activity(names, since):
    """The newest tool call of any Claude session that worked inside one of these ads' project folders
    (`projects/<ad>` in the call itself; an ad that is only mentioned, listed or printed does not count).
    It is how the board tells a Claude that is busy on the ad from no Claude at all."""
    want = [re.compile(r'projects/' + re.escape(n) + r'(?![A-Za-z0-9_-])') for n in names if n]
    return max([t for t, text in recent_sessions(since) if any(w.search(text) for w in want)] + [0.0]) if want else 0.0


def activity(ads, key=None, now=None, runs=None, window=None):
    """(newest sign of work on these ads, what it was). Signs: a cloud run that is open or just came back, a changed file
    in a project folder, a revise-plan batch file naming the ad, a Claude session writing about the ad, our own job's log."""
    now = now or time.time()
    window = window if window is not None else float(cfg()['claude_stall_min']) * 60
    seen = [(0.0, 'nothing')]
    runs = runs if runs is not None else (load(STATE / 'runs.json', {}) or {})
    for r in runs.values():
        if r.get('ad') in ads:
            if not r.get('collected'):
                seen.append((now, 'a cloud run is open'))
            seen.append((float(r.get('collected_at') or r.get('submitted') or 0), 'a cloud run'))
    for ad in ads:
        seen.append((newest_file(ROOT / 'projects' / ad), f'files of {ad}'))
    for f in STATE.glob('revise-*.json'):
        try:
            if f.stat().st_mtime > now - window and any(f'"{ad}"' in f.read_text() for ad in ads):
                seen.append((f.stat().st_mtime, 'a revision batch file'))
        except OSError:
            pass
    rec = record(key) if key else None
    if rec and rec.get('log'):
        try:
            seen.append((os.stat(rec['log']).st_mtime, 'the Claude job'))
        except OSError:
            pass
    seen.append((session_activity(ads, now - window), 'a Claude session'))
    return max(seen)


def work(key, ads, anchor, now=None, runs=None):
    """What is true about the work on this batch right now, for the board and for the watcher:
    {job, live, last, idle, what, stalled, blocked, ended}. `anchor` = the moment the work was asked for (it counts as
    activity, so nothing is called stalled in its first `claude_stall_min` minutes)."""
    now = now or time.time()
    c = cfg()
    rec = record(key)
    is_live = live(key)
    last, what = activity(ads, key, now, runs)
    last = max(last, float(anchor or 0))
    idle = max(0.0, now - min(last, now))
    blocked = rec.get('blocked') if rec and rec.get('state') == 'blocked' and float(rec.get('blocked_at') or 0) >= float(anchor or 0) else None
    return {'job': rec, 'live': is_live, 'last': last, 'idle': idle, 'what': what, 'blocked': blocked,
            'stalled': not is_live and not blocked and idle > float(c['claude_stall_min']) * 60,
            'ended': (rec or {}).get('state') if rec and not is_live and rec.get('state') in ('failed', 'timeout') else None}


# ---- the job -----------------------------------------------------------------------------------------------------------

RULES = '''Rules for this job:
- Nobody is watching and nobody can answer a question. Never ask; decide, and write down what you decided.
- Work only on the ads named above. Other Claude sessions may be working on other ads at the same time: leave their
  project folders, their cloud runs and their Frame.io files alone. If `ctl.py submit` says an ad already has an open
  run, wait for it (`ctl.py wait`) instead of working around it.
- Follow AGENTS.md, feedback/OWNER_TASTE.md and the skill for this kind of ad (raw-ugc-editor for real footage, the
  ad's own skill in plan.json otherwise). Prefer the cloud (`cloud/ctl.py`, guide: cloud/docs/CONTROLLER.md).
- Never look at frames or images yourself; use the tools' text checks (preflight, qc, master_qc, claude-lean).
- Money: {money} Never raise the kie cap per ad in cloud/controller/config.json, never lift a GLOBAL STOP,
  never use a paid Anthropic API key.
- Work ONLY on the ads listed as Ads above. Never re-render, revise or re-push an ad that has an APPROVED.json in its
  project folder (the owner approved it; it is finished), even when a note would otherwise apply to every hook (T28).
  The one exception is an ad listed above whose APPROVED.json names an older file than the newest one in its
  frameio.json (`file_id`): that approval is void, he sent the newer version back with notes, so revise it.
- Never touch a locked ad, never approve anything, never upload to Google Drive, never delete from Frame.io,
  never edit tools/ or cloud/ code, never install background jobs.
- If you cannot finish something (a note you cannot act on without guessing at a paid redo, a cap or GLOBAL STOP in the
  way, a broken tool, a permission that is refused), finish everything else first, then run
    {mpy} cloud/claude_job.py blocked "{key}" "<two plain sentences for the owner: what is stuck and what he must do>"
  and stop. That sentence is shown to him on the ad board.
- End with a short summary: per ad, what changed and whether its new version is on Frame.io.'''

REVISION = '''You are the unattended revision worker of the ad pipeline. The owner pressed "Revisions done" on the
ad board for the Frame.io batch "{key}". Ads: {ads}. Open notes per ad when he pressed: {notes}.

Take his Frame.io notes on this batch to finished, checked new versions on Frame.io. Work in {root}.

1. Run `{mpy} cloud/ctl.py reviews --working "{key}"`, then read the notes:
   `{mpy} cloud/ctl.py reviews` and `.venv/bin/python tools/feedback.py open` (they are already pulled
   into feedback/log.jsonl, src frameio). Learn every NEW note the way AGENTS.md "After owner feedback" says.
2. Decide the fix for every note and apply it to every listed ad it applies to (taste rules T27/T28; never an approved ad).
   `ctl.py revise-plan <ad> <ad> ...` writes the batch file with each note matched to its beat or shot; fill it in,
   then `ctl.py submit --from <file> --go`, `ctl.py wait`, `ctl.py collect` (the watcher may have collected already:
   `ctl.py history --next`). A text, caption or music change that needs no cloud run can be done locally.
3. For every ad: fix every FAIL in PREFLIGHT.md, answer every box truthfully ([x] / [n/a]), then push the new version:
   `.venv/bin/python tools/frameio.py push <ad> --batch "{key}"`. An ad whose notes change nothing in it needs no new version.
4. When every ad that needed a change has its new version on Frame.io:
   `{mpy} cloud/ctl.py reviews --revised "{key}"`.
{earlier}
''' + RULES

FIX = '''You are the unattended finishing worker of the ad pipeline. These ads came back from the cloud and stopped
at a check, and no Claude session has touched them since: {ads}.
What the ad board says about each:
{rows}

Finish them. Work in {root}. For each ad read `{mpy} cloud/ctl.py history --next` (the next step the
controller printed), projects/<ad>/PREFLIGHT.md and the newest log in projects/<ad>/.cloud/.
- A failed final check: fix the cause (not the check), render again through the cloud, and check again.
- A run the shot check blocked, or that failed in the cloud: fix the plan or acknowledge the known limit as
  CONTROLLER.md "The shot check" says, then submit again.
- Open PREFLIGHT boxes: answer every box truthfully ([x] / [n/a]); the watcher then pushes the ad to Frame.io by itself
  (or push it: `.venv/bin/python tools/frameio.py push <ad> --batch "<its batch>"`).
{earlier}
''' + RULES


SMOKE = '''This is a start-up test of the ad board's unattended Claude (no real work). Run exactly this one command with Bash,
then reply with the first line it printed and nothing else:
  {mpy} cloud/ctl.py jobs'''


PAID_OK = 'a paid redo (kie credits) that his notes clearly ask for is fine inside the kie cap per ad; nothing paid beyond that.'
PAID_NO = ('start NOTHING that spends kie credits (no ai-revise, ai-frames-revise, ai-clips, ai-resume, inserts, no redo). Do every '
           'fix that is free; for a note that needs a paid redo, report it with `claude_job.py blocked` and name the exact command.')


def prompt_for(rec):
    if rec.get('kind') == 'smoke':
        return SMOKE.format(mpy=MODAL_PY)
    money = PAID_OK if cfg().get('claude_job_paid') is True else PAID_NO
    earlier = ''
    if int(rec.get('tries') or 1) > 1:
        earlier = ('\nAn earlier unattended run on this already stopped part-way (' + str(rec.get('ended_why') or 'no reason on record')
                   + '). Check what is already done (frameio.py status, ctl.py history) before redoing anything.\n')
    ads = ', '.join(rec.get('ads') or [])
    if rec.get('kind') == 'fix':
        rows = '\n'.join(f"  - {a}: {t}" for a, t in (rec.get('rows') or {}).items()) or '  (see the ad board)'
        return FIX.format(key=rec['key'], ads=ads, rows=rows, root=ROOT, earlier=earlier, money=money, mpy=MODAL_PY)
    notes = ', '.join(f'{a} {n}' for a, n in (rec.get('notes') or {}).items()) or 'not counted'
    return REVISION.format(key=rec['key'], ads=ads, notes=notes, root=ROOT, earlier=earlier, money=money, mpy=MODAL_PY)


def claude_bin():
    return shutil.which('claude', path=PATH) or str(pathlib.Path.home() / '.local/bin/claude')


def command(rec, c=None):
    """The headless call. The owner's own settings, skills, CLAUDE.md and memory load as in any session (the job needs
    them); MCP servers do not (none is needed, and a server waiting for a login must not hang an unattended run).
    Permission mode `auto` with nobody to prompt: what his sessions may do without asking, and nothing else."""
    c = c or cfg()
    cmd = [claude_bin(), '-p', prompt_for(rec), '--permission-mode', 'auto', '--permission-prompts', 'none',
           '--output-format', 'stream-json', '--verbose', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
           '--session-id', rec['session_id'], '--name', f"ad board: {rec['key']}"[:60]]
    if c.get('claude_job_model'):
        cmd += ['--model', str(c['claude_job_model'])]
    if c.get('claude_job_effort'):
        cmd += ['--effort', str(c['claude_job_effort'])]
    awake = '/usr/bin/caffeinate'   # the Mac must not fall asleep from idleness in the middle of a job
    return ([awake, '-i', '-s'] if os.path.exists(awake) else []) + cmd


def job_env(key=''):
    env = {k: v for k, v in os.environ.items() if k not in NO_API}
    env['PATH'] = PATH + (':' + env['PATH'] if env.get('PATH') else '')
    env['PP_CLAUDE_JOB'] = str(key)   # ctl.py tells every other session to leave this batch to the job; the job itself is not told off
    return env


def family(pid):
    """pid and every process below it (a job's tools may sit in their own process groups)."""
    try:
        rows = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid='], capture_output=True, text=True, timeout=20).stdout.split()
    except Exception:
        return [pid]
    kids = {}
    for p, pp in zip(rows[::2], rows[1::2]):
        kids.setdefault(int(pp), []).append(int(p))
    out, todo = [], [pid]
    while todo:
        x = todo.pop()
        out.append(x)
        todo += kids.get(x, [])
    return out


def kill_tree(pid):
    pids = family(pid)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for p in pids:
            try:
                os.kill(p, sig)
            except OSError:
                pass
        time.sleep(4 if sig == signal.SIGTERM else 0)


def result_of(log):
    """(ok, last words) from the log's final stream-json line; (None, tail) when the job never got that far."""
    try:
        with open(log, 'rb') as f:
            f.seek(max(0, os.path.getsize(log) - 400_000))
            lines = f.read().decode('utf-8', 'replace').splitlines()
    except OSError:
        return None, ''
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get('type') == 'result':
            return (not d.get('is_error')), ' '.join(str(d.get('result') or d.get('subtype') or '').split())[-700:]
    return None, ' '.join(' '.join(lines[-6:]).split())[-400:]


def refresh_board():
    try:
        if str(C) not in sys.path:
            sys.path.insert(0, str(C))
        import dash
        dash.write(thumbs=False)
    except Exception:
        pass


def run(key, popen=subprocess.Popen, refresh=refresh_board):
    """The runner (its own process): hold the batch's lock, run Claude, stop it at the time limit, write how it ended."""
    rec = record(key)
    if not rec:
        return 'no such job'
    (STATE / 'claude-jobs').mkdir(parents=True, exist_ok=True)
    with open(lock_path(key), 'a') as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 'running'   # another runner has this batch: one Claude job per batch
        c = cfg()
        limit = float(c['claude_job_timeout_s'])
        log = pathlib.Path(rec['log'])
        log.parent.mkdir(parents=True, exist_ok=True)
        began = time.time()
        with open(log, 'ab') as out:
            out.write((json.dumps({'type': 'job', 'key': key, 'kind': rec.get('kind'), 'ads': rec.get('ads'), 'try': rec.get('tries'),
                                   'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'limit_s': limit}) + '\n').encode())
            out.flush()
            try:
                proc = popen(command(rec, c), cwd=str(ROOT), env=job_env(key), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             start_new_session=True)
            except OSError as e:
                save(key, state='failed', ended_at=time.time(), exit=-1, ended_why=f'Claude could not be started ({type(e).__name__})')
                refresh()
                return 'failed'
            rec = save(key, state='running', pid=os.getpid(), claude_pid=proc.pid, started_at=began, ended_at=None, exit=None,
                       ended_why=None, blocked=None if rec.get('state') != 'blocked' else rec.get('blocked'))
            refresh()
            try:
                code, timed_out = proc.wait(timeout=limit), False
            except subprocess.TimeoutExpired:
                kill_tree(proc.pid)
                code, timed_out = proc.wait(), True
        ok, words = result_of(log)
        now_rec = record(key) or {}
        if now_rec.get('state') == 'blocked' and float(now_rec.get('blocked_at') or 0) >= began:
            state, why = 'blocked', now_rec.get('blocked')          # the job said it needs the owner: that stands
        elif timed_out:
            state, why = 'timeout', f'stopped at the {limit / 3600:.1f} h time limit'
        elif code == 0 and ok is not False:
            state, why = 'done', None
        else:
            state, why = 'failed', (words or f'claude exit {code}')[:300]
        save(key, state=state, ended_at=time.time(), exit=code, ended_why=why, result=words, seconds=round(time.time() - began))
    refresh()
    return state


def spawn_runner(key):
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / 'runner.log', 'a') as out:
        subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve()), 'run', key], stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                         start_new_session=True, cwd=str(C))


def start(kind, key, ads, spawn=None, now=None, anchor=None, force=False, **more):
    """Start the job for this batch unless one is running. Returns 'started' | 'running' | 'off' | 'busy' | 'tries'.
    Never starts anything from a test run unless the test passes its own `spawn`."""
    now = now or time.time()
    c = cfg()
    if not force and not c.get('claude_auto'):
        return 'off'
    if spawn is None and (os.environ.get('PP_NO_CLAUDE_JOBS') or 'unittest' in sys.modules):
        return 'off'
    if live(key):
        return 'running'
    if not force and sum(1 for r in records() if r.get('key') != key and live(r['key'])) >= int(c['claude_max_jobs']):
        return 'busy'
    old = record(key) or {}
    same = old.get('anchor') == anchor and old.get('kind') == kind    # the same request as last time: count the tries
    tries = int(old.get('tries') or 0) + 1 if same else 1
    if not force and tries > int(c['claude_job_tries']):
        return 'tries'
    LOGS.mkdir(parents=True, exist_ok=True)
    save(key, kind=kind, ads=list(ads), state='starting', asked_at=now, anchor=anchor, tries=tries, session_id=str(uuid.uuid4()),
         log=str(LOGS / f"{slug(key)}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}.log"), pid=None, claude_pid=None,
         started_at=None, ended_at=None, exit=None, result=None, blocked=None, blocked_at=None,
         ended_why=old.get('ended_why') if same else None, **more)
    (spawn or spawn_runner)(key)
    return 'started'


def stop(key):
    rec = record(key)
    if not rec or not live(key):
        return False
    for pid in (rec.get('claude_pid'), ):
        if pid:
            kill_tree(int(pid))
    return True


def blocked(key, why, now=None):
    """Called by the job itself: it cannot finish without the owner. The board shows the sentence."""
    if not record(key):
        raise ValueError(f"No Claude job on record for '{key}'.")
    return save(key, state='blocked', blocked=' '.join(str(why).split())[:600], blocked_at=now or time.time())


# ---- the watcher's part ------------------------------------------------------------------------------------------------

def pushed_after(ad, t):
    """The ad's newest Frame.io upload is newer than t (his notes on the older version are answered)."""
    files = (load(ROOT / 'projects' / ad / 'frameio.json', {}) or {}).get('files') or []
    try:
        return bool(files) and time.mktime(time.strptime(str(files[-1].get('pushed'))[:19], '%Y-%m-%dT%H:%M:%S')) > t
    except (ValueError, TypeError, OverflowError):
        return False


def sweep(cards=None, reqs=None, now=None, spawn=None, dry=False, mark=None):
    """One look by the watcher: start (or start again) the Claude job of every batch that waits for one.
      - "Revisions done" batches pressed since this was switched on: at once when the helper could not start the job
        itself, again when a job or session stopped part-way and nothing has moved for `claude_stall_min` minutes;
      - finished ads the board shows as 'Claude to fix' or 'Final checks' that nobody has touched for that long.
    A batch an open Claude session took by hand before the switch-on is never taken over. Returns [(key, kind, outcome)]."""
    now = now or time.time()
    c = cfg()
    out = []
    if not c.get('claude_auto'):
        return out
    stall = float(c['claude_stall_min']) * 60
    if reqs is None:
        reqs = load(STATE / 'revision-requests.json', {}) or {}
    revising = set()
    for batch, req in sorted(reqs.items()):
        if req.get('state') not in ACTIVE:
            continue
        ads = list(req.get('ads') or [])
        revising.update(ads)
        if not req.get('auto') or req.get('state') == 'pulling' or not ads:
            continue
        pressed = float(req.get('pressed_at') or 0)
        todo = [a for a in ads if (req.get('notes') or {}).get(a)]
        own = req.get('ad_pressed') or {}   # a video sent with its own row button, or added later, has its own press time
        if todo and all(pushed_after(a, float(own.get(a) or pressed)) for a in todo) and not live(batch):
            if not dry and mark:
                mark(batch, 'done')    # every ad with notes has its new version up: nothing left to start
            out.append((batch, 'revision', 'finished'))
            continue
        w = work(batch, ads, max(pressed, float(req.get('pulled_at') or 0)), now)
        if w['live'] or w['blocked']:
            continue
        fresh = req.get('state') == 'waiting' and not (w['job'] and w['job'].get('anchor') == pressed)
        if not fresh and w['idle'] <= stall:
            continue
        if fresh and now - float(req.get('pulled_at') or pressed) < 120:
            continue   # the helper starts it itself right after the pull; this is only the safety net
        out.append((batch, 'revision', 'would start' if dry else start('revision', batch, ads, spawn=spawn, now=now, anchor=pressed,
                                                                         notes=req.get('notes') or {})))
    since = c.get('claude_auto_from')
    runs = load(STATE / 'runs.json', {}) or {}
    groups, mates = {}, {}
    for card in cards or []:
        mates.setdefault(card.get('batch') or card['ad'], set()).add(card['ad'])   # every ad of the batch, whatever its state
    for r in runs.values():
        if r.get('batch') and r.get('ad'):
            mates.setdefault(r['batch'], set()).add(r['ad'])
    for card in cards or []:
        if card.get('status') not in FIX_STATUS or card.get('test') or card['ad'] in revising or since is None:
            continue
        if float(card.get('when') or 0) < float(since):
            continue   # older than the switch-on: an open session may own it
        if batch_busy(card.get('batch'), reqs, runs):
            continue   # the batch is in somebody's hands: its stopped hook is theirs too
        groups.setdefault(card.get('batch') or card['ad'], []).append(card)
    for name, items in sorted(groups.items()):
        key = fix_key(name)
        ads = [x['ad'] for x in items]
        anchor = max(float(x.get('when') or 0) for x in items)
        w = work(key, ads, anchor, now, runs)
        if w['live'] or w['blocked'] or w['idle'] <= stall:
            continue
        if now - activity(sorted(mates.get(name) or ads), key, now, runs)[0] <= stall:
            continue   # someone is working on another ad of this batch: they have not left, they have not got to this one
        out.append((key, 'fix', 'would start' if dry else start('fix', key, ads, spawn=spawn, now=now, anchor=anchor,
                                                                rows={x['ad']: f"{x.get('status')}: {x.get('detail')}"[:300] for x in items})))
    return out


def status_lines(now=None):
    now = now or time.time()
    out = []
    for r in records():
        on = live(r['key'])
        when = r.get('started_at') or r.get('asked_at') or 0
        age = f"{(now - when) / 60:.0f} min ago" if when else '?'
        state = 'RUNNING' if on else str(r.get('state')).upper()
        out.append(f"{r['key']}: {r.get('kind')} job {state} (try {r.get('tries')}, started {age})"
                   + (f" - {r.get('blocked') or r.get('ended_why')}" if (r.get('blocked') or r.get('ended_why')) and not on else '')
                   + f"\n  ads: {', '.join(r.get('ads') or [])}\n  log: {r.get('log')}")
    return out


def main(a):
    if a[:1] == ['run'] and len(a) == 2:
        print(time.strftime('[%m-%d %H:%M:%S] ') + f'{a[1]}: {run(a[1])}', flush=True)
    elif a[:1] == ['status']:
        print('\n'.join(status_lines()) or 'no Claude jobs on record')
    elif a[:1] == ['blocked'] and len(a) == 3:
        try:
            blocked(a[1], a[2])
            print(f'{a[1]}: marked as waiting for the owner; the ad board shows your sentence')
        except ValueError as e:
            sys.exit(str(e))
        refresh_board()
    elif a[:1] == ['stop'] and len(a) == 2:
        print('stopped' if stop(a[1]) else 'no running job for that batch')
    elif a[:1] == ['start'] and len(a) == 2:
        req = (load(STATE / 'revision-requests.json', {}) or {}).get(a[1])
        if not req:
            sys.exit(f"No Revisions done request for '{a[1]}'. Press Revisions done on the ad board first.")
        print(start('revision', a[1], req.get('ads') or [], spawn=spawn_runner, anchor=float(req.get('pressed_at') or 0),
                    notes=req.get('notes') or {}, force=True))
    elif a[:1] == ['smoke']:   # proves the whole start path with a one-command job: runner, lock, login, permissions, log
        print(start('smoke', 'zz-smoke', [], spawn=spawn_runner, anchor=time.time(), force=True))
        print(f"log: {(record('zz-smoke') or {}).get('log')}\nthen: claude_job.py status")
    elif a[:1] == ['sweep']:
        if str(C) not in sys.path:
            sys.path.insert(0, str(C))
        import dash
        import frame_review
        got = sweep(dash.gather(thumbs=False)['cards'], dry='--dry' in a, spawn=spawn_runner, mark=frame_review.mark_revisions)
        print('\n'.join(f'{k}: {kind} job {res}' for k, kind, res in got) or 'nothing waits for a Claude job')
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
