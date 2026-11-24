"""The usage page: what each batch costs, how many revision rounds it took and how long it took to make
(cloud/.scratch/dashboard/usage.html, opened from the small "Usage" button at the top right of the ad board).

  .modal-env/bin/python cloud/ctl.py usage             # refresh it and open it
  .modal-env/bin/python cloud/ctl.py usage --index     # read every Claude transcript once (minutes)
  .modal-env/bin/python cloud/ctl.py usage --archive   # take in the projects archived to iCloud
  .modal-env/bin/python cloud/ctl.py usage --verify    # check every logged task against kie's own record

Everything on it is MEASURED, never estimated, and what is not on record shows a dash (exact or not shown):
  kie credits   every task id in projects/<ad>/**/*jobs*.jsonl (any depth) and product-kit/, kept in
                controller/usage/kie-tasks.json so an archived project keeps its history. Each task is then
                checked against kie's own record (GET /jobs/recordInfo, kept in controller/usage/kie-verified.json):
                kie's credits and kie's start and finish times replace the log's. A task the log never saw finish
                counts only after kie has said what it cost.
  dollars       credits x the owner's real price: kie_pack_usd / kie_pack_credits in controller/config.json
                (for example $500 buys 105,000 credits).
  balance       read live from kie (GET /chat/credit); every reading is kept in controller/usage/balance.jsonl, so
                top-ups and kie use outside the video projects show up.
  first pass    everything spent on a video up to the first time it went to Frame.io.
  revisions     everything spent on it after that. Rounds = Frame.io versions after v1.
  no split      a video that never went to Frame.io, and shared work made while only part of its batch had reached
                Frame.io: counted in the total, never called first pass or revisions. Rounds show a dash.
  make time     the time something was actually working on the ad: kie tasks running, cloud runs, and Claude working
                on it in a session (read from the Claude Code transcripts). Overlaps count once. Waiting for the owner
                is not counted. Shown only where every task has a time and the work began after the first saved
                Claude session; the Claude part follows rules (STICK_S, THINK_S, TOOL_S), so it is a close measurement.
  Claude        tokens of the sessions that worked on the ad (his plan: no bill, so no dollar figure is shown).

It is a VIEW: it writes only its own cache under controller/usage/ and the page. Stdlib only.
"""
import calendar
import collections
import concurrent.futures
import contextlib
import datetime
import fcntl
import html
import json
import os
import pathlib
import re
import time
import urllib.parse
import sys
import urllib.request

C = pathlib.Path(__file__).resolve().parent
if str(C) not in sys.path:
    sys.path.insert(0, str(C))
import names as _names  # noqa: E402

ROOT = C.parent
REPO_NAME = ROOT.name   # the repo folder's name: a Claude session whose cwd or paths name it worked in this repo
STATE = C / 'controller'
OUT = C / '.scratch' / 'dashboard'
TRANSCRIPTS = pathlib.Path.home() / '.claude' / 'projects'
ARCHIVE = pathlib.Path(os.environ.get('ADMACHINE_ARCHIVE') or pathlib.Path.home() / 'Library/Mobile Documents/com~apple~CloudDocs/Archive/ad-projects')   # where finished projects are archived (optional)
KIE_CREDIT_URL = 'https://api.kie.ai/api/v1/chat/credit'
KIE_TASK_URL = 'https://api.kie.ai/api/v1/jobs/recordInfo?taskId='
TEST_AD = re.compile(r'^(zz-|cloud-test)')
HOOK = re.compile(r'-h\d+$')
HOOK_FILE = re.compile(r'[-_]h(\d+)\.mp4$', re.I)
FORMATS = ['Animated', 'Song ad', 'Real footage edit', 'AI UGC', 'Drama', 'Other', 'Tests']
TASK_MAX_S = 3600          # a kie task "running" longer than this is a resumed job, not an hour of work
TOPUP_MIN = 500            # a balance that rose by more than this between two readings is a top-up
STICK_S = 30 * 60          # a Claude session stays on an ad this long after it last named it
THINK_S = 15 * 60          # the longest silence before Claude speaks that still counts as work
TOOL_S = 2 * 3600          # the longest tool call that still counts as work
BIG_LINE = 200_000
MANY_ADS = 6               # one command naming more ads than this is housekeeping, not work on an ad
OPEN_S = 2 * 3600          # a task with no finish line in the log is asked about at kie once it is this old
COVER_S = 48 * 3600        # make time is shown for work that began at least this long after the first saved Claude session


def load(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except Exception:
        return default


def store():
    return STATE / 'usage'


def save(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.part')
    tmp.write_text(json.dumps(data, separators=(',', ':')))
    tmp.replace(path)


def stamp(text):
    """'2026-11-22T03:29:32' (local time) -> epoch seconds; None when it cannot be read."""
    try:
        return datetime.datetime.strptime(str(text)[:19], '%Y-%m-%dT%H:%M:%S').timestamp()
    except Exception:
        return None


def day(t):
    return datetime.date.fromtimestamp(t).isoformat()


def rate():
    """(dollars per credit, pack dollars, pack credits) from the owner's real top-up."""
    c = _names.config(STATE)
    usd, credits = float(c.get('kie_pack_usd') or 500), float(c.get('kie_pack_credits') or 105000)
    return usd / credits, usd, credits


def pretty(ad, plan=None):
    title = (plan or {}).get('title') or (plan or {}).get('name')
    if isinstance(title, str) and 2 < len(title) < 70:
        return title
    words = re.sub(r' +', ' ', re.sub(r'-h(\d+)$', ' · Hook \\1', ad).replace('---', ' ').replace('-', ' '))
    return words[:1].upper() + words[1:]


# ---- kie tasks and ad records ---------------------------------------------------------------------------------------

def category(model):
    m = str(model or '').lower()
    if 'music' in m:
        return 'Music'
    if any(x in m for x in ('avatar', 'omnihuman', 'infinitalk', 'lip-sync')):
        return 'Talking head'
    if any(x in m for x in ('banana', 'image', 'recraft')) and 'image-to-video' not in m:
        return 'Images'
    if any(x in m for x in ('kling', 'seedance', 'hailuo', 'veo', 'video', 'wan')):
        return 'Video clips'
    return 'Other'


SKILL_FORMAT = {'song-ad-machine': 'Song ad', 'singing-ad-storyboard': 'Song ad', 'animated-ad-machine': 'Animated', 'vox-animated-ad': 'Animated',
                'finn-xplains-video': 'Animated', 'raw-ugc-editor': 'Real footage edit', 'ugc-talking-head': 'AI UGC', 'drama-ad-machine': 'Drama'}


def format_of(ad, plan, models=()):
    """The ad's format from what its own plan records (the skill that made it, else the plan's own fields), else from
    a folder name that states it. Never from which kie models it used: a cartoon with a music bed is not a song ad."""
    if TEST_AD.match(ad):
        return 'Tests'
    skill, name = str(plan.get('skill') or ''), ad.lower()
    if skill in SKILL_FORMAT:
        return SKILL_FORMAT[skill]
    if plan.get('song') or 'song' in name.split('-'):
        return 'Song ad'
    if plan.get('mode') in ('A_material', 'B_talking_character') or re.search(r'clay|pixar|cartoon|diorama|felt|lego', name):
        return 'Animated'
    if plan.get('shots') or plan.get('aroll'):
        return 'Real footage edit'
    return 'Other'


def job_files(proj):
    """Every kie job log in a project, at any depth (hooks/FIX3/jobs.jsonl, ai/jobs/jobs_x.jsonl ...)."""
    found = []
    for folder, dirs, files in os.walk(proj):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        found += [pathlib.Path(folder) / f for f in files if f.endswith('.jsonl') and 'jobs' in f.lower()]
    return sorted(found)


def videos_in(proj, siblings=()):
    """How many finished videos a project folder holds, from what is on disk: 0 when nothing proves one.
    Proof: MASTER.mp4, or EDIT_KIT/ORDER.txt (the assemblers write it right after rendering the master; the master of an
    archived ad was moved out), or finished hook cuts kept in the one folder (MASTER-h1.mp4, industry-ironbark-h2.mp4)
    when the hooks have no folders of their own. A storyboard, a delivery note or an empty EDIT_KIT proves nothing."""
    try:
        names = os.listdir(proj)
    except OSError:
        return 0
    try:
        names_out = os.listdir(proj / 'out')
    except OSError:
        names_out = []
    lead = proj.name.split('-')[0].lower()
    cuts = {int(HOOK_FILE.search(n).group(1)) for n in names + names_out
            if HOOK_FILE.search(n) and (n.upper().startswith('MASTER') or n.lower().startswith(lead))}
    own_folders = any(HOOK.search(x) and HOOK.sub('', x) == proj.name for x in siblings)
    if cuts and not own_folders:
        return len(cuts)
    return 1 if 'MASTER.mp4' in names or (proj / 'EDIT_KIT' / 'ORDER.txt').exists() else 0


def scan_projects(pdir, runs=None, recs=None):
    """Every project folder -> (kie tasks {taskId: [ad, key, model, start, end, credits, state]}, ad records {ad: {...}}).
    A task the log never saw finish keeps credits None: it counts only once kie itself has said what it cost."""
    tasks, metas = {}, {}
    run_batch = {}
    for r in sorted((runs or {}).values(), key=lambda r: r.get('submitted') or 0):
        if r.get('batch'):
            run_batch[r['ad']] = r['batch']
    sent = {}
    for key, r in (recs or {}).items():
        if r.get('state') == 'delivered':
            for ad in r.get('ads') or []:
                sent[ad] = (r.get('batch') or key, float(r.get('delivered_at') or 0) or True)
    if not pdir.is_dir():
        return tasks, metas
    folders = sorted(p for p in pdir.iterdir() if p.is_dir() and not p.name.startswith('.'))
    siblings = {p.name for p in folders}
    for proj in folders:
        ad, models = proj.name, set()
        for f in job_files(proj):
            try:
                lines = f.read_text(errors='replace').splitlines()
            except OSError:
                continue
            for ln in lines:
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                tid = d.get('taskId') if isinstance(d, dict) else None
                if not tid:
                    continue
                rec = tasks.setdefault(tid, [ad, d.get('key'), None, None, None, None, None])
                if rec[0] != ad:   # a hook folder copied from its base carries the base's records: they stay with the base
                    continue
                if d.get('model'):
                    rec[2] = d['model']
                    models.add(d['model'])
                if d.get('state') == 'submitted':
                    rec[3] = stamp(d.get('ts')) or rec[3]
                elif d.get('state') == 'success' and d.get('creditsConsumed') is not None:
                    rec[4], rec[5], rec[6] = stamp(d.get('ts')) or rec[4], float(d['creditsConsumed']), 'success'
                elif d.get('state') == 'fail' and rec[6] != 'success':
                    rec[6] = 'fail'
        plan = load(proj / 'plan.json', {}) or {}
        fio = load(proj / 'frameio.json', {}) or {}
        files = {x.get('id'): x for x in (fio.get('history') or []) + (fio.get('files') or []) if isinstance(x, dict)}
        pushes = sorted(t for t in (stamp(x.get('pushed')) for x in files.values()) if t)
        versions = max([int(x.get('v') or 0) for x in files.values()] + [len(pushes)])
        ok = load(proj / 'APPROVED.json', {}) or {}
        # delivered through the board, or taken off Frame.io after his OK (frameio.py clean), or locked as launched
        approved = sent.get(ad, (None, None))[1] or (stamp(fio.get('cleaned')) if not fio.get('files') else None) or (True if plan.get('locked') else None)
        n = 0   # finished videos in this folder; tests and clip options are never videos
        if not TEST_AD.match(ad) and not (proj / 'OPTIONS.json').exists() and '---' not in ad:
            n = videos_in(proj, siblings) or (1 if pushes or ad in sent else 0)
        metas[ad] = {'title': pretty(ad, plan), 'fmt': format_of(ad, plan, models), 'pushes': pushes, 'versions': versions,
                     'batch': fio.get('batch') or sent.get(ad, (None,))[0] or run_batch.get(ad) or None,
                     'n': n, 'video': bool(n),
                     'approved': approved, 'on_fio': bool(fio.get('files')), 'ok_at': ok.get('at') or ok.get('approved_at')}
    return tasks, metas


def merged(name, fresh, keep_gone=None):
    """The durable copy of `fresh` under controller/usage/: what is on disk now wins, what left the disk is kept."""
    path = store() / name
    old = load(path, {}) or {}
    new = dict(old)
    if keep_gone:
        for k, v in new.items():
            if k not in fresh:
                keep_gone(v)
    new.update(fresh)
    if new != old:
        save(path, new)
    return new


def feedback_facts():
    """Owner notes per ad from feedback/log.jsonl: {ad: {'notes': n, 'days': {...}, 'first': ts}}."""
    out = {}
    try:
        lines = (ROOT / 'feedback' / 'log.jsonl').read_text(errors='replace').splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(r, dict) or not r.get('ad') or r.get('status') in ('like', 'approved') or r.get('kind') == 'like':
            continue
        a = out.setdefault(r['ad'], {'notes': 0, 'days': set(), 'first': None})
        a['notes'] += 1
        t = stamp(r.get('ts'))
        if t and r.get('src') in ('frameio', 'chat'):   # 'chat-history' rows carry the day they were imported, not the day he said it
            a['days'].add(day(t))
            a['first'] = min(a['first'] or t, t)
    return out


def cloud_runs(runs):
    """Cloud runs per ad with their real length and Modal cost: {ad: [(start, seconds, usd)]}."""
    wall, usd = {}, collections.Counter()
    for f in sorted(STATE.glob('ledger-*.json')):
        for c in (load(f, {}) or {}).get('calls') or []:
            m = re.match(r'(.+)-(?:pipeline|s\d+-[\w-]+)$', str(c.get('id') or ''))
            if not m:
                continue
            try:
                usd[m.group(1)] += float(c.get('estimate_usd') or 0)
                wall[m.group(1)] = max(wall.get(m.group(1), 0), float(c.get('wall_seconds') or 0))
            except (TypeError, ValueError):
                pass
    out = {}
    for r in runs.values():
        if r.get('run') in wall or r.get('run') in usd:
            out.setdefault(r['ad'], []).append((float(r.get('submitted') or 0), wall.get(r['run'], 0), usd.get(r['run'], 0)))
    return out


# ---- time: merged spans ---------------------------------------------------------------------------------------------

def union(spans):
    """Sorted, merged copy of [(start, end)]."""
    out = []
    for s, e in sorted([s, e] for s, e in spans if e > s):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def seconds(spans):
    return sum(e - s for s, e in union(spans))


def split(spans, cut):
    """(spans before the cut, spans after it). No cut: everything is before."""
    if not cut:
        return list(spans), []
    a, b = [], []
    for s, e in spans:
        if e <= cut:
            a.append((s, e))
        elif s >= cut:
            b.append((s, e))
        else:
            a.append((s, cut))
            b.append((cut, e))
    return a, b


# ---- Claude: which sessions worked on which ad -------------------------------------------------------------------------

TS = re.compile(rb'"timestamp":"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]+')


def iso_utc(text):
    """'2026-11-21T06:18:34.762Z' -> epoch seconds."""
    try:
        return calendar.timegm(time.strptime(str(text)[:19], '%Y-%m-%dT%H:%M:%S'))
    except ValueError:
        return None


def ts_of(chunk):
    m = TS.search(chunk)
    return calendar.timegm(tuple(int(x) for x in m.groups())) if m else None


def named_ads(d, known):
    """The ad folders a Claude message's tool calls name (only for work inside this repo)."""
    here = REPO_NAME in str(d.get('cwd') or '')
    found = set()
    for block in (d.get('message') or {}).get('content') or []:
        if isinstance(block, dict) and block.get('type') == 'tool_use':
            given = block.get('input') or {}   # where it worked, not what it wrote: a note that lists ten ads is not work on them
            text = ' '.join(str(given.get(k) or '') for k in ('command', 'file_path', 'path', 'notebook_path')) if isinstance(given, dict) else ''
            if ARCHIVE.name in text or re.search(r'Mobile\\? Documents|CloudDocs|icloud', text, re.I):
                continue   # moving a project to the iCloud archive (or reading it back) is housekeeping, not work on the ad
            if here or REPO_NAME in text:
                found |= {w.strip('._-') for w in NAME.findall(text)} & known
    return sorted(found) if len(found) <= MANY_ADS else []   # a sweep over many ads (a rename, the board) is not work on each of them


def scan_file(path, st, known, agg, segs):
    """Read what was added to one transcript since last time. `st` is that file's saved position and state."""
    def event(t, kind):
        last = st.get('t')
        if t is None or (last and not last - 120 <= t <= last + 6 * 3600):
            return False
        cur = st.get('cur')
        if cur and t - (st.get('cur_t') or 0) > STICK_S:
            cur = st['cur'] = None
        if last and cur and kind != 'u' and 0 < t - last <= (TOOL_S if kind == 'r' else THINK_S):
            for ad in cur:
                spans = segs.setdefault(ad, [])
                if spans and last <= spans[-1][1] + 1 and last >= spans[-1][0]:
                    spans[-1][1] = max(spans[-1][1], t)
                else:
                    spans.append([last, t])
        st['t'] = max(t, last or 0)
        return True

    with open(path, 'rb') as f:
        f.seek(st.get('off', 0))
        for line in f:
            if not line.endswith(b'\n'):
                break   # still being written: next time
            st['off'] = st.get('off', 0) + len(line)
            if not line.startswith(b'{"parentUuid"'):
                continue   # bookkeeping records (api requests, attachments): not a message
            head = line[:700]
            if b'"role":"assistant"' in head or b'"type":"assistant"' in head:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get('type') != 'assistant':
                    continue
                t = iso_utc(d.get('timestamp'))
                ads = named_ads(d, known)
                if ads and t:
                    st['cur'], st['cur_t'] = ads, t
                if not event(t, 'a'):
                    continue
                m = d.get('message') or {}
                u = m.get('usage') or {}
                if st.get('cur') and m.get('id') and m.get('id') != st.get('mid') and m.get('model') != '<synthetic>':
                    vals = [int(u.get(k) or 0) for k in ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')]
                    share = len(st['cur'])
                    for ad in st['cur']:
                        row = agg.setdefault(ad, {}).setdefault(day(t), [0, 0, 0, 0, 0])
                        for i, v in enumerate(vals):
                            row[i] += v / share
                        row[4] += 1 / share
                st['mid'] = m.get('id')
            elif b'"role":"user"' in head or b'"type":"user"' in head:
                if len(line) <= BIG_LINE:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if d.get('type') != 'user':
                        continue
                    content = (d.get('message') or {}).get('content')
                    tool = isinstance(content, list) and any(isinstance(x, dict) and x.get('type') == 'tool_result' for x in content)
                    event(iso_utc(d.get('timestamp')), 'r' if tool else 'u')
                else:   # a pasted picture or a long tool result: too big to parse for one time stamp
                    event(ts_of(line[-6000:]) or ts_of(line[:6000]), 'r' if b'"tool_use_id"' in line[:6000] else 'u')


def first_stamp(root):
    """The earliest moment any saved Claude session covers (sessions are chronological: the first stamp of each file)."""
    best = None
    for f in root.rglob('*.jsonl'):
        try:
            with open(f, 'rb') as h:
                t = ts_of(h.read(65536))
        except OSError:
            continue
        if t and (best is None or t < best):
            best = t
    return best


def claude_index(known, budget=0.0, root=None, now=None):
    """The saved index of Claude work per ad, after reading new transcript lines for up to `budget` seconds
    (None = no limit). -> {'agg': {ad: {day: [in, out, cache read, cache write, messages]}}, 'segs': {ad: [[s, e]]}, 'pending': bytes}."""
    root = root or TRANSCRIPTS
    path = store() / 'claude-index.json'
    idx = load(path, None) or {'v': 1, 'files': {}, 'agg': {}, 'segs': {}, 'pending': None}
    if budget == 0 or not root.is_dir():
        return idx
    store().mkdir(parents=True, exist_ok=True)
    with open(store() / 'claude-index.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return idx   # another process is reading them right now
        idx = load(path, None) or idx
        started, todo = time.monotonic(), []
        for f in root.rglob('*.jsonl'):
            try:
                s = f.stat()
            except OSError:
                continue
            rel = str(f.relative_to(root))
            if s.st_size > (idx['files'].get(rel) or {}).get('off', 0):
                todo.append((s.st_mtime, s.st_size, rel, f))
        left = 0
        for _, size, rel, f in sorted(todo, reverse=True):
            st = idx['files'].setdefault(rel, {'off': 0})
            if budget is not None and time.monotonic() - started > budget:
                left += size - st.get('off', 0)
                continue
            try:
                scan_file(f, st, known, idx['agg'], idx['segs'])
            except OSError:
                pass
        idx['segs'] = {ad: union(spans) for ad, spans in idx['segs'].items()}
        idx['pending'], idx['at'] = left, now or time.time()
        fresh = 'first' not in idx
        if fresh:   # the first moment any saved session covers: work before it cannot be timed
            idx['first'] = first_stamp(root)
        if todo or fresh:
            save(path, idx)
    return idx


# ---- the live kie balance ---------------------------------------------------------------------------------------------

def kie_key():
    """The key from the repo's .env. Never printed, logged or put on the page."""
    try:
        for line in (ROOT / '.env').read_text().splitlines():
            if line.startswith('KIE_API_KEY='):
                return line.split('=', 1)[1].strip().strip('"\'') or None
    except OSError:
        pass
    return None


def fetch_balance(timeout=8):
    key = kie_key()
    if not key:
        return None
    req = urllib.request.Request(KIE_CREDIT_URL, headers={'Authorization': f'Bearer {key}', 'User-Agent': 'ad-board'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return float(json.loads(r.read())['data'])


def balance_rows():
    rows = []
    try:
        for ln in (store() / 'balance.jsonl').read_text().splitlines():
            try:
                r = json.loads(ln)
                rows.append((float(r['t']), float(r['credits'])))
            except (ValueError, KeyError, TypeError):
                pass
    except OSError:
        pass
    return rows


def balance(max_age=60, fetch=None, now=None):
    """The kie balance, read live unless a reading younger than `max_age` seconds exists.
    -> {'credits': n or None, 't': when it was read, 'error': why the live read failed or None}."""
    now = now or time.time()
    last = load(store() / 'balance-last.json', None)
    if last and now - float(last.get('t') or 0) <= max_age:
        return {'credits': last['credits'], 't': last['t'], 'error': None}
    try:
        value = (fetch or fetch_balance)()
    except Exception as e:
        value, why = None, type(e).__name__
    else:
        why = None if value is not None else 'no key'
    if value is None:
        return {'credits': (last or {}).get('credits'), 't': (last or {}).get('t'), 'error': why}
    rows = balance_rows()
    store().mkdir(parents=True, exist_ok=True)
    if not rows or abs(rows[-1][1] - value) >= 0.01 or now - rows[-1][0] >= 1800:
        with open(store() / 'balance.jsonl', 'a') as f:
            f.write(json.dumps({'t': round(now), 'credits': value}) + '\n')
    save(store() / 'balance-last.json', {'t': now, 'credits': value})
    return {'credits': value, 't': now, 'error': None}


def balance_story(rows):
    """From the saved readings: top-ups, and how much the balance fell in total since the first reading."""
    tops, fell = [], 0.0
    for (_, a), (t, b) in zip(rows, rows[1:]):
        if b - a > TOPUP_MIN:
            tops.append({'t': t, 'credits': b - a})
        elif a > b:
            fell += a - b
    return tops, fell


# ---- every task checked against kie's own record ---------------------------------------------------------------------

def kie_task(task_id, key, timeout=30):
    """kie's own record of one task -> [state, credits, created, completed] (epoch seconds). state is 'success', 'fail',
    'none' (kie has no record of this id) or whatever kie calls a task that is still running."""
    req = urllib.request.Request(KIE_TASK_URL + urllib.parse.quote(str(task_id), safe=''),
                                 headers={'Authorization': f'Bearer {key}', 'User-Agent': 'ad-board'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    if isinstance(d, dict) and d.get('code') == 429:
        raise OSError('kie asked us to slow down')
    data = d.get('data') if isinstance(d, dict) else None
    if not isinstance(data, dict) or not data.get('state'):
        return ['none', None, None, None]
    when = lambda v: round(float(v) / 1000) if v else None
    credits = data.get('creditsConsumed')
    return [str(data['state']), float(credits) if credits is not None else None, when(data.get('createTime')), when(data.get('completeTime'))]


def verify(limit=None, budget=None, workers=6, lookup=None, now=None):
    """Ask kie about every task in the logs it has not been asked about yet, and keep the answers in
    controller/usage/kie-verified.json. Reads only, free. -> (asked now, still to ask, lookups that failed)."""
    now = now or time.time()
    if lookup is None:
        key = kie_key()
        if not key:
            return 0, 0, 0
        lookup = lambda tid: kie_task(tid, key)
    tasks = load(store() / 'kie-tasks.json', {}) or {}
    path = store() / 'kie-verified.json'
    seen = load(path, {}) or {}
    todo = [tid for tid, rec in tasks.items() if tid not in seen
            and (rec[5] is not None or (rec + [None])[6] == 'fail' or not rec[3] or now - rec[3] > OPEN_S)]
    left = len(todo)
    todo = todo[:limit] if limit else todo
    if not todo:
        return 0, 0, 0
    store().mkdir(parents=True, exist_ok=True)
    done = failed = 0
    with open(store() / 'kie-verified.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0, left, 0   # another process is asking right now
        seen = load(path, {}) or seen
        started = time.monotonic()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
        try:
            jobs = {pool.submit(lookup, tid): tid for tid in todo if tid not in seen}
            try:
                for job in concurrent.futures.as_completed(jobs, timeout=budget):
                    try:
                        got = job.result()
                    except Exception:
                        failed += 1
                        if failed > 25 and failed > done:
                            break   # kie is down or refusing: stop, the rest waits for the next run
                        continue
                    if got and got[0] in ('success', 'fail', 'none'):   # a task still running is asked about again later
                        seen[jobs[job]] = got
                        done += 1
                        if done % 250 == 0:
                            save(path, seen)
            except concurrent.futures.TimeoutError:
                pass
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
            if done:
                save(path, seen)
    return done, left - done, failed


def settle(tasks, seen):
    """Each logged task as kie records it. -> ({taskId: [ad, key, model, start, end, credits]}, what the check found).
    Where kie has answered, its credits and its times replace the log's. A task the log never saw finish and kie has not
    answered for is left out: nothing is counted that neither side has confirmed."""
    out = {}
    audit = {'tasks': 0, 'checked': 0, 'waiting': 0, 'differ': 0, 'differ_credits': 0.0, 'recovered': 0, 'recovered_credits': 0.0, 'unknown': 0}
    for tid, rec in tasks.items():
        ad, key, model, t0, t1, cr = rec[:6]
        v = seen.get(tid)
        if v and v[0] in ('success', 'fail'):
            kc = float(v[1] or 0)
            if cr is None:
                if kc:
                    audit['recovered'] += 1
                    audit['recovered_credits'] += kc
            elif abs(kc - cr) > 0.005:
                audit['differ'] += 1
                audit['differ_credits'] += kc - cr
            cr, t0, t1 = kc, v[2] or t0, v[3] or t1
            if not cr:
                continue   # a failed task kie did not charge for
            audit['checked'] += 1
        elif cr is None:
            continue
        elif v:
            audit['unknown'] += 1   # kie no longer has a record of it: the log's own figure stands
        else:
            audit['waiting'] += 1
        audit['tasks'] += 1
        out[tid] = [ad, key, model, t0, t1, cr]
    audit['differ_credits'], audit['recovered_credits'] = round(audit['differ_credits'], 2), round(audit['recovered_credits'], 2)
    return out, audit


# ---- everything together --------------------------------------------------------------------------------------------

def batch_names(metas, used):
    """ad -> batch name. An ad with no batch of its own sits with its base ad, then with the batch its own hooks are in,
    then with the one batch that shares its first name part (a hub folder), then alone under its own name."""
    out = {ad: m['batch'] for ad, m in metas.items() if m.get('batch')}
    lead = collections.defaultdict(set)
    for ad, b in out.items():
        lead[ad.split('-')[0]].add(b)
    for ad in sorted(used):
        if ad in out:
            continue
        base = HOOK.sub('', ad.split('---')[0])
        m = metas.get(ad) or {}
        mine = {b for k, b in out.items() if k != ad and HOOK.sub('', k) == ad and metas.get(k, {}).get('batch')}
        if base != ad and base in out:
            out[ad] = out[base]
        elif len(mine) == 1:   # the folder its hooks were cut from: it belongs to the batch those hooks are in
            out[ad] = next(iter(mine))
        elif not m.get('video') and len(lead.get(ad.split('-')[0], ())) == 1:
            out[ad] = next(iter(lead[ad.split('-')[0]]))
        else:
            out[ad] = pretty(base)
    return out


def gather(now=None, scan=0.0, fetch=None, max_age=60):
    now = now or time.time()
    per_credit, pack_usd, pack_credits = rate()
    runs = load(STATE / 'runs.json', {}) or {}
    recs = load(STATE / 'deliveries.json', {}) or {}
    local_tasks, local_metas = scan_projects(ROOT / 'projects', runs, recs)
    kit_tasks, kit_metas = scan_projects(ROOT / 'product-kit')   # product stills every ad shares
    for ad, m in kit_metas.items():
        if ad not in local_metas:
            m.update(video=False, n=0, batch='Product kit', kit=True, title='Product kit: ' + ad)
            local_metas[ad] = m
    for tid, rec in kit_tasks.items():
        local_tasks.setdefault(tid, rec)
    for m in local_metas.values():
        m['local'] = True
    tasks, audit = settle(merged('kie-tasks.json', local_tasks), load(store() / 'kie-verified.json', {}) or {})
    metas = merged('ads.json', local_metas, keep_gone=lambda m: m.update(local=False))
    notes = feedback_facts()
    cloud = cloud_runs(runs)
    known = {a for a, m in metas.items() if not m.get('kit') and ('-' in a or re.search(r'\d', a))} | {r['ad'] for r in runs.values()}
    idx = claude_index(known, budget=scan, now=now)
    # work time is only complete from the first Claude session still on this Mac
    cover = idx.get('first') or min((s[0] for spans in idx['segs'].values() for s in spans), default=None)

    by_ad = collections.defaultdict(list)
    for tid, (ad, key, model, t0, t1, cr) in tasks.items():
        by_ad[ad].append((key, model, t0, t1, cr))
    used = set(by_ad) | set(cloud) | set(idx['segs']) | {ad for ad, m in metas.items() if m.get('video') and (m.get('pushes') or m.get('approved'))}
    used = {ad for ad in used if ad in metas or ad in by_ad}
    names = batch_names(metas, used)
    groups = collections.defaultdict(list)
    for ad in used:
        groups[names[ad]].append(ad)

    batches = []
    for name, ads in groups.items():
        # The split is exact or it is not shown. A video splits at its own first Frame.io push. Shared work (a hub folder)
        # is first pass until the batch's first video reached Frame.io and revisions once every video has; in between,
        # and for a video that never went to Frame.io, the spend is counted in the total only ("x": no split).
        firsts = [((metas[a].get('pushes') or [None])[0]) for a in ads if (metas.get(a) or {}).get('video')]
        lo = min((c for c in firsts if c), default=None)
        hi = max(firsts) if firsts and all(firsts) else None
        b = {'name': name, 'f': 0.0, 'r': 0.0, 'x': 0.0, 'u': 0.0, 'cats': collections.Counter(), 'days': {}, 'ads': [], 'modal': 0.0, 'runs': 0,
             'cl': [0.0, 0.0, 0.0, 0.0], 'notes': 0, 'rounds': None, 'last': 0.0}
        first_spans, rev_spans, open_spans, claude_spans, timed, seen_claude = [], [], [], [], True, 0.0
        for ad in sorted(ads):
            m = metas.get(ad) or {'title': pretty(ad), 'fmt': format_of(ad, {}, [x[1] for x in by_ad[ad]]), 'video': False}
            video = bool(m.get('video'))
            own = (m.get('pushes') or [None])[0]
            c1, c2 = (own, own) if video else (lo, hi)
            fmt = m['fmt']
            if fmt == 'Other':   # a hook folder with no plan of its own is the format of the ad it is a hook of
                fmt = (metas.get(HOOK.sub('', ad)) or {}).get('fmt') or fmt
            row = {'ad': ad, 'title': m['title'], 'f': 0.0, 'r': 0.0, 'x': 0.0, 'video': video, 'n': int(m.get('n') or video), 'fmt': fmt}
            spans, starts, dated = [], [], True
            for key, model, t0, t1, cr in by_ad[ad]:
                t = t1 or t0
                phase = 'x' if not t else 'f' if c1 and t <= c1 else 'r' if c2 and t > c2 else 'x'
                row[phase] += cr
                b['cats'][category(model)] += cr
                if t:
                    d = b['days'].setdefault(day(t), [0.0, 0.0, 0.0])
                    d['frx'.index(phase)] += cr
                    b['last'] = max(b['last'], t)
                    starts.append(t0 or t)
                else:
                    b['u'] += cr
                    dated = False
                if t0 and t1 and 0 < t1 - t0 <= TASK_MAX_S:
                    spans.append((t0, t1))
            for start, secs, usd in cloud.get(ad, []):
                b['modal'] += usd
                b['runs'] += 1
                b['last'] = max(b['last'], start + secs)
                starts.append(start)
                if secs:
                    spans.append((start, start + secs))
            mine = [tuple(x) for x in idx['segs'].get(ad, [])]
            claude_spans += mine
            starts += [s for s, _ in mine[:1]]
            for d, vals in (idx['agg'].get(ad) or {}).items():
                for i in range(4):
                    b['cl'][i] += vals[i]
            work = union(spans + mine)
            a, rest = split(work, c1) if c1 else ([], work)
            mid, r = (split(rest, c2) if c2 else (rest, [])) if c1 else (rest, [])
            first_spans += a
            rev_spans += r
            open_spans += mid
            # make time only where the whole life of the ad is on record: every task dated, begun after Claude sessions were kept
            whole = dated and cover is not None and (not starts or min(starts) >= cover + COVER_S)
            timed = timed and whole
            row['s'] = round(seconds(work)) if whole else None
            n = notes.get(ad) or {}
            row['notes'] = n.get('notes', 0)
            # a round = a new version sent to Frame.io after the first. Never on Frame.io: not known, so not shown.
            row['rounds'] = max(0, int(m.get('versions') or 0) - 1) if video and own else None
            row['st'] = ('Approved' if m.get('approved') else 'Archived' if not m.get('local', True) else 'On Frame.io' if m.get('on_fio') else 'In production')
            b['last'] = max([b['last']] + list(m.get('pushes') or []) + ([m['approved']] if isinstance(m.get('approved'), float) else []))
            seen_claude = max([seen_claude] + [e for _, e in mine[-1:]])
            for k in 'frx':
                row[k] = round(row[k], 1)
                b[k] += row[k]
            b['notes'] += row['notes']
            if row['rounds'] is not None:
                b['rounds'] = max(b['rounds'] or 0, row['rounds'])
            b['ads'].append(row)
        videos = [x for x in b['ads'] if x['video']]
        if not (b['f'] or b['r'] or b['x'] or first_spans or rev_spans or open_spans):
            continue
        b['last'] = b['last'] or seen_claude   # an edit of real footage has no kie task: its Claude sessions date it
        fmts = collections.Counter(x['fmt'] for x in (videos or b['ads']))
        b['fmt'] = fmts.most_common(1)[0][0]
        b['videos'] = sum(x['n'] for x in videos)
        states = {x['st'] for x in videos}
        b['status'] = ('No finished video on record' if not videos else 'Approved' if states == {'Approved'} else 'On Frame.io' if 'On Frame.io' in states
                       else 'Archived' if states <= {'Archived', 'Approved'} else 'In production')
        b['s'] = round(seconds(first_spans + rev_spans + open_spans)) if timed else None
        b['fs'], b['rs'], b['xs'] = round(seconds(first_spans)), round(seconds(rev_spans)), round(seconds(open_spans))
        b['cs'] = round(seconds(claude_spans))
        for k in 'frxu':
            b[k] = round(b[k], 1)
        b['cats'] = {k: round(v, 1) for k, v in b['cats'].most_common() if v}
        b['days'] = {d: [round(x, 1) for x in v] for d, v in b['days'].items()}
        b['cl'] = [round(x) for x in b['cl']]
        b['modal'] = round(b['modal'], 4)
        batches.append(b)
    batches.sort(key=lambda b: (-b['last'], b['name']))

    bal = balance(max_age=max_age, fetch=fetch, now=now)
    rows = balance_rows()
    tops, fell = balance_story(rows)
    week = sum(sum(v) for b in batches for d, v in b['days'].items() if d > day(now - 7 * 86400))
    since = rows[0][0] if rows else None
    logged = sum(cr for _, (ad, key, model, t0, t1, cr) in tasks.items() if since and (t1 or t0 or 0) >= since)
    ledger = load(STATE / f"ledger-{datetime.date.fromtimestamp(now).strftime('%Y-%m')}.json", {}) or {}
    low = _names.config(STATE).get('kie_low_credits')
    audit['credits'] = round(sum(v[5] for v in tasks.values()), 1)
    audit['undated'] = round(sum(b['u'] for b in batches), 1)
    return {'now': now, 'rate': per_credit, 'pack': [pack_usd, pack_credits], 'bal': bal, 'week': round(week, 1), 'low': float(low) if low else None,
            'tops': tops[-5:], 'since': since, 'fell': round(fell, 1), 'logged': round(logged, 1), 'audit': audit, 'cover': cover,
            'formats': [f for f in FORMATS if any(b['fmt'] == f for b in batches)], 'batches': batches,
            'claude': {'pending': idx.get('pending'), 'at': idx.get('at')},
            'modal': [float(ledger.get('estimated_total_usd') or 0), float(ledger.get('cap_usd') or 0)]}


def take_in_archive(folder=None, seconds_per_file=20):
    """One-time: add the kie records of projects archived to iCloud. Their files download on first read; a file that
    does not arrive in time is skipped and can be taken in on the next run."""
    import threading
    folder = pathlib.Path(folder or ARCHIVE)
    got = {}

    def work():
        got['data'] = scan_projects(folder)

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(seconds_per_file * 30)
    if 'data' not in got:
        return None
    tasks, metas = got['data']
    old_t, old_m = load(store() / 'kie-tasks.json', {}) or {}, load(store() / 'ads.json', {}) or {}
    for m in metas.values():
        m['local'] = False
    new_t = {k: v for k, v in tasks.items() if k not in old_t}
    new_m = {k: v for k, v in metas.items() if k not in old_m}
    old_t.update(new_t)
    old_m.update({k: v for k, v in metas.items() if k not in old_m or not old_m[k].get('local')})
    save(store() / 'kie-tasks.json', old_t)
    save(store() / 'ads.json', old_m)
    return len(new_t), len(new_m), sum(v[5] or 0 for v in new_t.values())


def pill():
    """What the ad board's small button shows: the last balance reading and whether it is running low."""
    last = load(store() / 'balance-last.json', None) or {}
    page = load(store() / 'summary.json', {}) or {}
    return {'credits': last.get('credits'), 'low': bool(page.get('low_now'))}


def low_now(data):
    c = data['bal'].get('credits')
    if c is None:
        return False
    per_day = data['week'] / 7
    return c < data['low'] if data.get('low') else bool(per_day and c / per_day < 3)


# ---- the page ---------------------------------------------------------------------------------------------------------

CSS = '''
:root{--paper:#f5f4ef;--surface:#fff;--ink:#16150f;--soft:#4a4840;--mute:#8a867b;--line:#e3e0d6;--hair:#eeebe3;
--live:#1c7c54;--bad:#b83227;--wait:#a86a12;--tint:#efede6;--s1:#2a78d6;--s2:#eb6834;--s0:#c9c5b8;
--sans:"Instrument Sans",-apple-system,"SF Pro Text",system-ui,sans-serif;--serif:"Instrument Serif","New York",ui-serif,Georgia,serif}
@media (prefers-color-scheme:dark){:root{--paper:#0f0f0d;--surface:#181816;--ink:#f1eee6;--soft:#c2beb3;--mute:#807c72;--line:#2a2925;--hair:#21201d;
--live:#4fbf8c;--bad:#ee6a5c;--wait:#dba54a;--tint:#1f1e1b;--s1:#3987e5;--s2:#d95926;--s0:#716e65}}
*{box-sizing:border-box}html{background:var(--paper)}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 var(--sans);-webkit-font-smoothing:antialiased}
.wrap{max-width:1040px;margin:0 auto;padding:36px 32px 72px}
.back{color:var(--mute);font-size:13px;text-decoration:none}.back:hover{color:var(--ink)}
.top{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;flex-wrap:wrap;margin-top:6px}
.brand{font:400 44px/1 var(--serif);letter-spacing:-.01em;margin:0}
.meta{color:var(--mute);font-size:13px;text-align:right}.meta b{font-weight:500;color:var(--soft)}
.lnk{appearance:none;border:0;background:none;font:inherit;color:var(--soft);cursor:pointer;padding:0;text-decoration:underline}.lnk:hover{color:var(--ink)}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:30px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px;min-width:0}
.kpi .k{font:600 12px/1.2 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--mute)}
.kpi .v{font:500 30px/1.1 var(--sans);letter-spacing:-.02em;font-variant-numeric:tabular-nums;margin-top:10px;white-space:nowrap}
.kpi .v small{font-size:14px;font-weight:500;color:var(--mute);letter-spacing:0;margin-left:5px}
.kpi .s{color:var(--soft);font-size:13px;margin-top:4px}.kpi .n{color:var(--mute);font-size:12.5px;margin-top:6px}
.kpi.low{border-color:var(--wait)}.kpi.low .n{color:var(--wait);font-weight:600}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--live);margin-right:6px;vertical-align:1px}.dot.off{background:var(--mute)}
.filters{display:flex;gap:10px 26px;flex-wrap:wrap;align-items:center;margin-top:26px}
.fl{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.fl>span{font-size:12.5px;color:var(--mute)}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--surface);flex-wrap:wrap}
.seg button{appearance:none;border:0;background:none;font:inherit;font-size:13.5px;font-weight:500;color:var(--soft);padding:7px 13px;cursor:pointer;white-space:nowrap}
.seg button+button{border-left:1px solid var(--line)}.seg button[aria-pressed=true]{background:var(--ink);color:var(--paper)}
.chk{display:inline-flex;align-items:center;gap:7px;font-size:13.5px;color:var(--soft);cursor:pointer;user-select:none}.chk input{width:16px;height:16px;margin:0;accent-color:var(--ink)}
.tabs{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:22px}
.tab{appearance:none;font:inherit;color:inherit;text-align:left;cursor:pointer;background:transparent;border:1px solid var(--line);border-radius:14px;padding:13px 18px;display:grid;gap:1px}
.tab:hover{border-color:var(--mute)}.tab .l{font-weight:600;font-size:15px}.tab .h{color:var(--mute);font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tab[aria-selected=true]{background:var(--ink);border-color:var(--ink);color:var(--paper)}.tab[aria-selected=true] .h{color:color-mix(in srgb,var(--paper) 62%,transparent)}
button:focus-visible,summary:focus-visible,a:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.panel{margin-top:24px}.panel[hidden]{display:none}
.bar{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:10px;flex-wrap:wrap}
.bar p{margin:0;color:var(--soft);font-size:14px}.bar select{font:inherit;font-size:13.5px;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:9px;padding:6px 10px}
.list{background:var(--surface);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.cols,.b>summary{display:grid;grid-template-columns:minmax(0,1fr) 108px 108px 108px 76px 104px;gap:14px;align-items:center;padding:13px 18px}
.cols{font:600 11.5px/1.2 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--mute);border-bottom:1px solid var(--hair);padding-top:11px;padding-bottom:11px}
.cols span:not(:first-child),.b>summary>div:not(:first-child){text-align:right}
.b{border-top:1px solid var(--hair)}.b:first-of-type{border-top:0}
.b>summary{list-style:none;cursor:pointer}.b>summary::-webkit-details-marker{display:none}.b>summary:hover{background:color-mix(in srgb,var(--tint) 55%,transparent)}
.b h3{margin:0;font:600 15.5px/1.3 var(--sans);overflow-wrap:anywhere;padding-left:18px;text-indent:-18px}.b h3::before{content:"▸";display:inline-block;width:18px;text-indent:0;font-size:14px;color:var(--soft);transition:transform .15s}
.b[open] h3::before{transform:rotate(90deg)}
.sub{color:var(--mute);font-size:12.5px;margin-top:1px;padding-left:18px}
.m{font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}.c{color:var(--mute);font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}
.zero .m{color:var(--mute);font-weight:500}
.d{padding:4px 18px 18px 36px}
.d table{width:100%;border-collapse:collapse;font-size:13.5px;table-layout:fixed}
.d th:nth-child(2),.d th:nth-child(3),.d th:nth-child(4){width:122px}.d th:nth-child(5){width:90px}.d th:nth-child(6){width:118px}.tbl .d th{width:auto}.d th{font:600 11px/1.2 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--mute);text-align:right;padding:8px 0 6px 14px;border-bottom:1px solid var(--hair)}
.d th:first-child,.d td:first-child{text-align:left;padding-left:0}.d td{padding:8px 0 8px 14px;text-align:right;border-bottom:1px solid var(--hair);font-variant-numeric:tabular-nums;white-space:nowrap}
.d td:first-child{white-space:normal;overflow-wrap:anywhere}.d td i{font-style:normal;color:var(--mute);font-size:12px}.d td{vertical-align:top}
.fold{margin-top:14px}.fold>summary{list-style:none;cursor:pointer;border:1px dashed var(--line);border-radius:12px;padding:11px 16px;color:var(--soft);font-size:13.5px;font-weight:500}
.fold>summary::-webkit-details-marker{display:none}.fold>summary::before{content:"▸";display:inline-block;width:18px;color:var(--soft)}.fold[open]>summary::before{content:"▾"}
.fold>summary:hover{border-color:var(--mute)}.fold[open]>summary{margin-bottom:10px}
.facts{margin:12px 0 0;padding:0;list-style:none;color:var(--soft);font-size:13.5px;display:grid;gap:4px}.facts b{font-weight:600;color:var(--ink)}
.empty{border:1px dashed var(--line);border-radius:14px;padding:40px 20px;text-align:center;color:var(--mute)}
.legend{display:flex;gap:6px 18px;flex-wrap:wrap;font-size:13px;color:var(--soft)}.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:7px;vertical-align:-1px}
.f{display:grid;grid-template-columns:190px minmax(0,1fr) 112px 70px 100px 104px;gap:16px;align-items:center;padding:14px 18px;border-top:1px solid var(--hair)}
.f:first-of-type,.f.cols+.f{border-top:0}.f.cols{border-bottom:1px solid var(--hair);white-space:nowrap}.f>*:nth-child(n+3){text-align:right}
.f.four{grid-template-columns:190px 1fr 1fr 1fr}.f.four>*:nth-child(n+2){text-align:right}
.f h3{margin:0;font:600 15px/1.3 var(--sans)}.f .sub{padding-left:0}
.track{display:flex;align-items:center;gap:2px;min-width:0}.track u{display:block;height:14px;min-width:3px;text-decoration:none}
.track u.a{background:var(--s1)}.track u.r{background:var(--s2)}.track u.x{background:var(--s0)}.track u:first-child{border-radius:4px 0 0 4px}.track u:last-child{border-radius:0 4px 4px 0}.track u:only-child{border-radius:4px}
.kpis.three{grid-template-columns:repeat(3,1fr)}
.chart{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:18px 18px 10px}
.chart svg{display:block;width:100%;height:auto;overflow:visible}.chart text{font:11.5px var(--sans);fill:var(--mute)}.chart text.val{fill:var(--soft);font-weight:600}
.chart .grid{stroke:var(--hair);stroke-width:1}.chart .base{stroke:var(--line);stroke-width:1}
.chart .hit{fill:transparent}.chart .hit:hover{fill:color-mix(in srgb,var(--ink) 5%,transparent)}
.tbl{margin-top:12px}.tbl summary{cursor:pointer;color:var(--soft);font-size:13px}.tbl .d{padding:6px 0 0}
#tip{position:fixed;z-index:9;pointer-events:none;background:var(--ink);color:var(--paper);border-radius:9px;padding:8px 11px;font-size:12.5px;line-height:1.45;max-width:260px;opacity:0;transition:opacity .08s}
#tip b{font-weight:600}#tip i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px}
.note{margin:14px 2px 0;color:var(--mute);font-size:12.5px;max-width:86ch}
footer{margin-top:40px;color:var(--mute);font-size:12.5px;max-width:92ch}
@media (max-width:900px){.kpis,.kpis.three{grid-template-columns:1fr 1fr}.tabs{grid-template-columns:1fr 1fr}
.cols,.b>summary{grid-template-columns:minmax(0,1fr) 100px 64px 92px}.cols span:nth-child(2),.cols span:nth-child(3),.b>summary>div:nth-child(2),.b>summary>div:nth-child(3){display:none}
.f.cols{display:none}.f,.f.four{grid-template-columns:1fr 1fr 1fr;gap:10px 14px}.f .fn{grid-column:1/3}.f.four .fn{grid-column:1/-1}.f .fp{grid-column:3}.f .track{grid-column:1/-1;grid-row:2}
.f>[data-l],.f.four>[data-l]{text-align:left}.f>[data-l]::before{content:attr(data-l);display:block;font:500 11.5px/1.3 var(--sans);color:var(--mute)}}
@media (max-width:620px){.wrap{padding:24px 16px 56px}.brand{font-size:36px}.meta{text-align:left}.kpi{padding:14px}.kpi .v{font-size:23px}.tab .h{display:none}
.cols,.b>summary{grid-template-columns:minmax(0,1fr) 92px;padding-left:14px;padding-right:14px}.cols span:nth-child(n+5),.b>summary>div:nth-child(n+5){display:none}
.d{padding:0 14px 16px}.d thead{display:none}.d table,.d tbody{display:block}.d tr{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px 10px;padding:12px 0;border-bottom:1px solid var(--hair)}
.d td{display:block;border:0;padding:0;text-align:left}.d td:first-child{grid-column:1/-1;font-weight:600}.d td[data-l]::before{content:attr(data-l);display:block;font:500 11.5px/1.3 var(--sans);color:var(--mute)}
.seg button{padding:7px 10px}.seg{flex-wrap:nowrap;overflow-x:auto;max-width:100%}.fl{min-width:0;max-width:100%}.d table{table-layout:auto}}
'''

JS = r'''
const RATE=D.rate,nf=new Intl.NumberFormat('en-US'),$=s=>document.querySelector(s);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const usd=c=>{const v=c*RATE;return '$'+(v>=1000?nf.format(Math.round(v)):v.toFixed(2))};
const cr=c=>nf.format(Math.round(c));
const dur=s=>{if(!s)return '—';const m=Math.round(s/60);if(m<1)return 'under 1 min';if(m<60)return m+' min';const h=Math.floor(m/60),r=m%60;return h>=20?nf.format(Math.round(m/60))+' h':h+' h'+(r?' '+r+' min':'')};
const tok=n=>n>=1e9?(n/1e9).toFixed(1)+' billion':n>=1e6?(n/1e6).toFixed(1)+' million':n>=1e3?Math.round(n/1e3)+'k':String(Math.round(n));
const dkey=t=>{const d=new Date(t*1000);return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')};
const dname=k=>new Date(k+'T12:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric'});
const ago=t=>{const d=Math.max(0,Date.now()/1000-t);return d<90?'just now':d<3600?Math.round(d/60)+' min ago':d<86400?Math.round(d/3600)+' h ago':Math.round(d/86400)+' d ago'};
const about=s=>s==null||!s?'—':'≈ '+dur(s);
const money=(c,l)=>`<div class="${c?'':'zero'}"${l?` data-l="${l}"`:''}><div class="m">${usd(c)}</div><div class="c">${c?cr(c)+' credits':'no kie credits'}</div></div>`;
const nosplit=`<div class="zero" title="No first pass and revision split: never went to Frame.io"><div class="m">—</div></div>`;
const plural=(n,w)=>n+' '+w+(n===1?'':w.endsWith('ch')?'es':'s');
const all3=o=>o.f+o.r+o.x;
let S={period:'7',fmt:'All',sort:'new',tab:'batches'};
try{Object.assign(S,JSON.parse(localStorage.getItem('usage-view')||'{}'))}catch(e){}
if(S.fmt!=='All'&&!D.formats.includes(S.fmt))S.fmt='All';
const keep=()=>{try{localStorage.setItem('usage-view',JSON.stringify(S))}catch(e){}};
const from=()=>S.period==='all'?0:D.now-(+S.period)*86400;
const match=b=>(S.fmt==='All'||b.fmt===S.fmt);
const view=()=>D.batches.filter(b=>match(b)&&(S.period==='all'||b.last>=from()));
const periodWord=()=>S.period==='all'?'all time':'the last '+S.period+' days';
function spent(){let f=0,r=0,x=0;const k=S.period==='all'?'':dkey(from());
  D.batches.filter(match).forEach(b=>{for(const d in b.days)if(d>k){f+=b.days[d][0];r+=b.days[d][1];x+=b.days[d][2]}if(S.period==='all')x+=b.u});return [f,r,x]}
function kpis(){
  const bal=LIVE.credits,perDay=D.week/7,left=bal!=null&&perDay?bal/perDay:null,low=bal!=null&&(D.low?bal<D.low:left!=null&&left<3);
  const [f,r,x]=spent(),t=f+r+x,bs=view().filter(b=>b.videos),vids=bs.reduce((a,b)=>a+b.videos,0),tot=bs.reduce((a,b)=>a+all3(b),0);
  const tb=bs.filter(b=>b.s!=null&&b.s>0),tv=tb.reduce((a,b)=>a+b.videos,0),secs=tb.reduce((a,b)=>a+b.s,0);
  const run=left==null?'':left>=60?'Over 60 days left at this pace':`About ${left<1.5?'1 day':Math.round(left)+' days'} left at this pace`;
  $('#kpis').innerHTML=`<div class="kpi${low?' low':''}"><div class="k">kie balance</div>
    <div class="v">${bal==null?'—':cr(bal)}<small>credits</small></div><div class="s">${bal==null?'Not read yet':'worth '+usd(bal)}</div>
    <div class="n">${low?'Time to top up. ':''}${run}</div><div class="n"><i class="dot${LIVE.error?' off':''}"></i>${LIVE.t?(LIVE.error?'Last read ':'Read from kie ')+ago(LIVE.t):'kie could not be reached'}</div></div>
  <div class="kpi"><div class="k">Spent, ${esc(periodWord())}</div><div class="v">${usd(t)}</div><div class="s">${cr(t)} credits</div>
    <div class="n">${!t?'Nothing spent':f+r?`Revisions were ${Math.round(100*r/(f+r))}% of ${x?'the '+usd(f+r)+' that went through Frame.io':'it'}`:'No first pass and revision split for this spend'}</div></div>
  <div class="kpi"><div class="k">Average per video</div><div class="v">${vids?usd(tot/vids):'—'}</div><div class="s">${vids?cr(tot/vids)+' credits':'No videos in view'}</div>
    <div class="n">${vids?plural(vids,'video')+' in '+plural(bs.length,'batch')+'. Other work is left out':''}</div></div>
  <div class="kpi"><div class="k">Make time per video</div><div class="v">${tv?about(secs/tv):'—'}</div><div class="s">${tv?'working time, not waiting':''}</div>
    <div class="n">${tv?'Measured from the work logs, not a stopwatch':''}</div></div>`}
function brow(b,open){
  const t=all3(b),vids=b.videos?plural(b.videos,'video'):'',each=b.videos>1&&t?`${usd(t/b.videos)} each`:'';
  const cats=Object.entries(b.cats).map(([k,v])=>`${esc(k)} ${cr(v)}`).join(' · ');
  const cell=(c,l)=>`<td data-l="${l}">${usd(c)}<br><i>${c?cr(c)+' credits':'no kie credits'}</i></td>`,none=l=>`<td data-l="${l}" title="No first pass and revision split: never went to Frame.io">—</td>`;
  const part=(o,k,l)=>o.x&&!(o.f+o.r)?none(l):cell(o[k],l);
  const rows=b.ads.map(a=>`<tr><td>${esc(a.title)}${a.video?(a.n>1?` <i>${a.n} hook cuts in one folder</i>`:''):' <i>shared work, not a video</i>'}</td>${part(a,'f','First pass')}${part(a,'r','Revisions')}${cell(all3(a),'Total')}<td data-l="Rounds">${a.rounds==null?'—':a.rounds}</td><td data-l="Make time">${about(a.s)}</td></tr>`).join('');
  const facts=[cats&&`<li><b>Where the credits went:</b> ${cats}</li>`,
    b.x&&`<li><b>No split:</b> ${usd(b.x)} (${cr(b.x)} credits) is in the total only. It was spent on a video that never went to Frame.io, or on shared work made while some of the batch was already in review, so it cannot be called first pass or revisions.</li>`,
    b.s!=null&&b.s>0&&`<li><b>Make time:</b> ${b.xs?about(b.s):about(b.fs)+' on the first pass, '+about(b.rs)+' on revisions'}${b.cs?'. Claude was working for '+about(b.cs)+' of it':''}</li>`,
    b.s==null&&`<li><b>Make time</b> is not shown: part of this work has no recorded times.</li>`,
    b.s!=null&&b.cl[1]&&`<li><b>Claude usage:</b> ${tok(b.cl[1])} tokens written</li>`,
    b.runs&&`<li><b>Cloud runs:</b> ${b.runs}, $${b.modal.toFixed(2)} of cloud compute</li>`,
    b.notes&&`<li><b>Notes you left:</b> ${b.notes}</li>`,
    b.videos>1&&b.s>0&&`<li>Work done on several videos at once counts once in the batch’s make time, so it can be less than the videos added up.</li>`].filter(Boolean).join('');
  const split=b.x&&!(b.f+b.r)?nosplit+nosplit:money(b.f)+money(b.r);
  return `<details class="b" data-name="${esc(b.name)}"${open.has(b.name)?' open':''}><summary><div><h3>${esc(b.name)}</h3><div class="sub">${[esc(b.fmt),vids,each,esc(b.status),b.x&&b.f+b.r?usd(b.x)+' with no split':''].filter(Boolean).join(' · ')}</div></div>
    ${split}${money(t)}<div class="m">${b.rounds==null?'—':b.rounds}</div><div class="m">${about(b.s)}</div></summary>
    <div class="d"><table><thead><tr><th>Video</th><th>First pass</th><th>Revisions</th><th>Total</th><th>Rounds</th><th>Make time</th></tr></thead><tbody>${rows}</tbody></table><ul class="facts">${facts}</ul></div></details>`}
function batches(){
  const key={new:b=>-b.last,cost:b=>-all3(b),rev:b=>-(b.rounds||0)*1e9-b.r,time:b=>-(b.s||0)}[S.sort],all=view().sort((a,b)=>key(a)-key(b));
  const bs=all.filter(b=>b.videos),rest=all.filter(b=>!b.videos),open=new Set([...document.querySelectorAll('.b[open]')].map(x=>x.dataset.name)),was=$('#rest')&&$('#rest').open;
  const head='<div class="cols"><span>Batch</span><span>First pass</span><span>Revisions</span><span>Total</span><span>Rounds</span><span>Make time</span></div>';
  $('#p-batches .count').textContent=bs.length?`${plural(bs.length,'batch')} worked on in ${periodWord()}. Each row is the batch’s full cost so far.`:'';
  $('#blist').innerHTML=(bs.length?`<div class="list">${head}${bs.map(b=>brow(b,open)).join('')}</div>`
    :`<div class="empty">No batch with a finished video was worked on in ${esc(periodWord())}${S.fmt==='All'?'':' in this format'}.</div>`)
    +(rest.length?`<details class="fold" id="rest"${was?' open':''}><summary>Other work, no finished video on record · ${plural(rest.length,'item')} · ${usd(rest.reduce((a,b)=>a+all3(b),0))}</summary>
      <div class="list">${head}${rest.map(b=>brow(b,open)).join('')}</div></details>`:'')}
function byFormat(){const out={};view().filter(b=>b.videos).forEach(b=>{const o=out[b.fmt]=out[b.fmt]||{fmt:b.fmt,n:0,v:0,f:0,r:0,x:0,s:0,tv:0,rounds:0,rn:0,cl:0,cs:0};
  o.n++;o.v+=b.videos;o.f+=b.f;o.r+=b.r;o.x+=b.x;if(b.s!=null){o.s+=b.s;o.tv+=b.videos;o.cl+=b.cl[1];o.cs+=b.cs}
  b.ads.forEach(a=>{if(a.video&&a.rounds!=null){o.rounds+=a.rounds;o.rn++}})});
  return D.formats.map(f=>out[f]).filter(Boolean)}
function formats(){
  const fs=byFormat(),max=Math.max(1e-9,...fs.map(o=>all3(o)/o.v)),rest=view().filter(b=>!b.videos),other=rest.reduce((a,b)=>a+all3(b),0);
  $('#flist').innerHTML=(fs.length?`<div class="list"><div class="f cols"><span>Format</span><span>Average cost of one video</span><span></span><span>Rounds</span><span>Make time</span><span>Revision share</span></div>`+fs.map(o=>{
    const a=o.f/o.v,r=o.r/o.v,x=o.x/o.v,t=a+r+x,seg=(v,c)=>v?`<u class="${c}" style="width:${(100*v/max).toFixed(2)}%"></u>`:'';
    const tip=`data-tip="<b>${esc(o.fmt)}</b>, one video on average<br><i style='background:var(--s1)'></i>First pass ${usd(a)} · ${cr(a)} credits<br><i style='background:var(--s2)'></i>Revisions ${usd(r)} · ${cr(r)} credits${x?`<br><i style='background:var(--s0)'></i>No split ${usd(x)} · ${cr(x)} credits`:''}"`;
    return `<div class="f"><div class="fn"><h3>${esc(o.fmt)}</h3><div class="sub">${plural(o.v,'video')} in ${plural(o.n,'batch')}</div></div>
      <div class="track" ${tip}>${seg(a,'a')}${seg(r,'r')}${seg(x,'x')}</div>
      <div class="fp${t?'':' zero'}"><div class="m">${usd(t)}</div><div class="c">${t?cr(t)+' credits':'no kie credits'}</div></div>
      <div data-l="Rounds"><div class="m">${o.rn?(o.rounds/o.rn).toFixed(1):'—'}</div>${o.rn&&o.rn<o.v?`<div class="c">from ${o.rn} of ${o.v}</div>`:''}</div><div class="m" data-l="Make time">${o.tv&&o.s?about(o.s/o.tv):'—'}</div><div class="m" data-l="Revision share">${a+r?Math.round(100*r/(a+r))+'%':'—'}</div></div>`}).join('')+'</div>'
    :`<div class="empty">No finished videos to compare in ${esc(periodWord())}.</div>`)
    +(other?`<p class="note">Not in these averages: ${usd(other)} (${cr(other)} credits) of other work with no finished video on record: tests, clip options, statics, and older work whose finished file is not in its folder.</p>`:'')
    +(fs.some(o=>o.x)?`<p class="note">Grey is spend with no first pass and revision split: videos that never went to Frame.io. Rounds and revision share use only the videos that did, and make time only the videos with recorded work times.</p>`:'')}
function timeline(){
  const bs=D.batches.filter(match),sum={};let first=null;
  bs.forEach(b=>{for(const d in b.days){const v=sum[d]=sum[d]||[0,0,0];for(let i=0;i<3;i++)v[i]+=b.days[d][i];if(!first||d<first)first=d}});
  const end=new Date(dkey(D.now)+'T12:00:00'),n=S.period==='all'?(first?Math.min(120,Math.round((end-new Date(first+'T12:00:00'))/864e5)+1):0):+S.period,days=[];
  for(let i=n-1;i>=0;i--){const k=dkey(end/1000-i*86400),v=sum[k]||[0,0,0];days.push([k,v[0],v[1],v[2]])}
  const of=d=>d[1]+d[2]+d[3],total=days.reduce((a,d)=>a+of(d),0);
  if(!total){$('#tchart').innerHTML=`<div class="empty">No kie spend in ${esc(periodWord())}.</div>`;$('#tsum').textContent='';return}
  const W=1000,H=280,L=52,R=8,T=12,B=30,pw=W-L-R,ph=H-T-B,top=Math.max(...days.map(d=>of(d)*RATE));
  const step=[1,2,5,10,20,25,50,100,200,250,500,1000,2000,5000].find(s=>top/s<=4)||Math.ceil(top/4),ymax=Math.ceil(top/step)*step||step,y=v=>T+ph-ph*v/ymax;
  const band=pw/days.length,bw=Math.max(3,Math.min(34,band*.62)),every=Math.ceil(days.length/10);
  let g='';for(let v=0;v<=ymax+1e-9;v+=step)g+=`<line class="${v?'grid':'base'}" x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L-8}" y="${y(v)+4}" text-anchor="end">$${nf.format(v)}</text>`;
  const top4=(x,yy,w,h)=>{const r=Math.min(4,h,w/2);return `M${x},${yy+h}V${yy+r}Q${x},${yy} ${x+r},${yy}H${x+w-r}Q${x+w},${yy} ${x+w},${yy+r}V${yy+h}Z`};
  const names=['First pass','Revisions','No split'],fill=['var(--s1)','var(--s2)','var(--s0)'];
  days.forEach((d,i)=>{const x=L+band*i+(band-bw)/2,parts=[1,2,3].map(j=>d[j]*RATE),last=parts[2]?2:parts[1]?1:0;let base=0;
    parts.forEach((v,j)=>{if(!v)return;const h=ph*v/ymax,gap=base?2:0,yy=y(base+v);
      if(h>gap)g+=j===last?`<path d="${top4(x,yy,bw,h-gap)}" fill="${fill[j]}"/>`:`<rect x="${x}" y="${yy}" width="${bw}" height="${h-gap}" fill="${fill[j]}"/>`;base+=v});
    if(i%every===0||i===days.length-1&&days.length>1&&i%every>every/2)g+=`<text x="${L+band*(i+.5)}" y="${H-9}" text-anchor="middle">${dname(d[0])}</text>`;
    g+=`<rect class="hit" x="${L+band*i}" y="${T}" width="${band}" height="${ph}" data-tip="<b>${dname(d[0])}</b>${[1,2,3].map(j=>d[j]||j<3?`<br><i style='background:${fill[j-1]}'></i>${names[j-1]} ${usd(d[j])} · ${cr(d[j])} credits`:'').join('')}<br>Total ${usd(of(d))}"/>`});
  const busy=days.reduce((a,d)=>of(d)>of(a)?d:a),undated=S.period==='all'?bs.reduce((a,b)=>a+b.u,0):0;
  days.forEach((d,i)=>{const v=of(d);if(v&&(days.length<=14||d===busy))g+=`<text class="val" x="${L+band*(i+.5)}" y="${y(v*RATE)-6}" text-anchor="middle">$${nf.format(Math.round(v*RATE))}</text>`});
  $('#tsum').textContent=`${usd(total)} in ${S.period==='all'?'the days shown':periodWord()} · ${usd(total/days.length)} a day on average · busiest day ${dname(busy[0])} (${usd(of(busy))})`
    +(undated?` · ${usd(undated)} more has no date on record and is not on the chart`:'');
  $('#tchart').innerHTML=`<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="kie spend per day: first pass, revisions and spend with no split">${g}</svg></div>
    <details class="tbl"><summary>Show the days as a table</summary><div class="d"><table><thead><tr><th>Day</th><th>First pass</th><th>Revisions</th><th>No split</th><th>Total</th><th>Credits</th></tr></thead><tbody>${
    days.filter(d=>of(d)).reverse().map(d=>`<tr><td>${dname(d[0])}</td><td>${usd(d[1])}</td><td>${usd(d[2])}</td><td>${usd(d[3])}</td><td><b>${usd(of(d))}</b></td><td>${cr(of(d))}</td></tr>`).join('')}</tbody></table></div></details>`}
function claude(){
  const bs=view().filter(b=>b.videos&&b.s!=null),rest=view().filter(b=>!b.videos&&b.s!=null),cs=bs.reduce((a,b)=>a+b.cs,0),out=bs.reduce((a,b)=>a+b.cl[1],0),fs=byFormat().filter(o=>o.tv),pend=D.claude.pending;
  const vids=bs.reduce((a,b)=>a+b.videos,0),other=rest.reduce((a,b)=>a+b.cs,0);
  $('#clist').innerHTML=`<div class="kpis three" style="margin-top:0">
    <div class="kpi"><div class="k">Claude working time</div><div class="v">${about(cs)}</div><div class="s">${vids?about(cs/vids)+' per video':'on the batches in view'}</div></div>
    <div class="kpi"><div class="k">Claude usage</div><div class="v">${tok(out)}</div><div class="s">tokens Claude wrote on these batches</div></div>
    <div class="kpi"><div class="k">Cloud compute, this month</div><div class="v">$${D.modal[0].toFixed(2)}</div><div class="s">${D.modal[1]?'of your $'+D.modal[1].toFixed(0)+' monthly limit':''}</div></div></div>`
    +(fs.length?`<div class="list" style="margin-top:14px"><div class="f four cols"><span>Format</span><span>Claude time per video</span><span>Tokens written per video</span><span>Videos</span></div>`
      +fs.map(o=>`<div class="f four"><div class="fn"><h3>${esc(o.fmt)}</h3></div><div class="m" data-l="Claude time per video">${about(o.cs/o.tv)}</div><div class="m" data-l="Tokens per video">${tok(o.cl/o.tv)}</div><div class="m" data-l="Videos">${o.tv}</div></div>`).join('')+'</div>':'')
    +`<p class="note">Claude runs on your plan, so there is no bill to show: this is how much Claude work each format takes. Claude’s time is already inside each batch’s make time. It is read from the saved Claude sessions: a session counts toward an ad while it is working in that ad’s folder, so it is a close measurement, not a stopwatch. Batches with no recorded work times are left out.${
      other?' Other work with no finished video on record took '+dur(other)+' more.':''}${pend?` Older Claude sessions are still being read (${(pend/1e9).toFixed(1)} GB to go), so these numbers will rise.`:''} ElevenLabs voice credits are not on this page yet.</p>`}
function draw(){kpis();batches();formats();timeline();claude();
  document.querySelectorAll('[data-period]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.period===S.period));
  document.querySelectorAll('[data-fmt]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.fmt===S.fmt));
  $('#sort').value=S.sort;
  document.querySelectorAll('.tab').forEach(t=>t.setAttribute('aria-selected',t.dataset.tab===S.tab));
  document.querySelectorAll('.panel').forEach(p=>p.hidden=p.dataset.tab!==S.tab);keep()}
let LIVE=Object.assign({},D.bal);
$('#fmts').innerHTML=['All',...D.formats].map(f=>`<button data-fmt="${esc(f)}">${esc(f)}</button>`).join('');
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;const d=b.dataset;
  if(d.period){S.period=d.period;draw()}else if(d.fmt){S.fmt=d.fmt;draw()}else if(d.tab){S.tab=d.tab;draw()}else if(b.id==='refresh')live(true)});
$('#sort').addEventListener('change',e=>{S.sort=e.target.value;draw()});
const tip=$('#tip');
document.addEventListener('mousemove',e=>{const t=e.target.closest('[data-tip]');if(!t){tip.style.opacity=0;return}
  tip.innerHTML=t.dataset.tip;tip.style.opacity=1;const w=tip.offsetWidth,h=tip.offsetHeight;
  tip.style.left=Math.max(8,Math.min(innerWidth-w-8,e.clientX+14))+'px';tip.style.top=Math.max(8,e.clientY-h-12)+'px'});
// The balance is read from kie the moment the page opens (through the board helper on this Mac), and the page is rebuilt when its numbers are old.
async function live(force){const b=$('#refresh');if(force){b.disabled=true;b.textContent='Refreshing…'}
  try{const r=await fetch(BASE+'/usage',{method:'POST',headers:{'Content-Type':'text/plain'},body:JSON.stringify({token:TOKEN,rebuild:force||Date.now()/1000-D.now>120})});
    const j=await r.json();if(!j.ok)throw new Error(j.error||'');
    if(j.credits!=null)LIVE={credits:j.credits,t:j.t,error:j.error};
    if(j.rebuilt){let n=0;try{n=+sessionStorage.getItem('usage-reload')||0;sessionStorage.setItem('usage-reload',Date.now())}catch(e){}
      if(force||Date.now()-n>60000){location.reload();return}}
    kpis()}
  catch(e){if(force)$('#said').textContent='The board helper is not running. Run ctl.py usage once, or tell Claude.'}
  if(force){b.disabled=false;b.textContent='Refresh'}}
draw();live(false);
'''


def e(x):
    return html.escape(str(x if x is not None else ''), quote=True)


def render(data, base='', token=''):
    fonts = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
             '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Instrument+Serif&display=swap">')
    clock = datetime.datetime.fromtimestamp(data['now']).strftime('%-I:%M %p')
    usd, credits = data['pack']
    price = f"${usd:,.0f} buys {credits:,.0f} credits · ${1000 * data['rate']:.2f} per 1,000"
    tabs = [('batches', 'Batches', 'Cost, revisions and time of each'), ('formats', 'By format', 'Average per video'),
            ('timeline', 'Timeline', 'Spend day by day'), ('claude', 'Claude and cloud', 'The other usage')]
    legend = ('<div class="legend"><span><i style="background:var(--s1)"></i>First pass</span><span><i style="background:var(--s2)"></i>Revisions</span>'
              '<span><i style="background:var(--s0)"></i>No split</span></div>')
    a = data.get('audit') or {}
    check = f"{a.get('checked', 0):,} of {a.get('tasks', 0):,} kie tasks have been checked against kie’s own record of the task"
    if a.get('waiting'):
        check += f", {a['waiting']:,} are still to be checked"
    if a.get('unknown'):
        check += f"; {a['unknown']:,} are no longer on kie’s side and use the credits logged when they ran"
    since = data.get('since')
    fell = (f" Since {datetime.datetime.fromtimestamp(since).strftime('%b %-d, %-I:%M %p')} the balance readings fell by {data.get('fell', 0):,.0f} credits "
            f"and {data.get('logged', 0):,.0f} credits of tasks are listed here for the same time." if since and data.get('fell') else '')
    blob = json.dumps(data, separators=(',', ':')).replace('</', '<\\/')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Usage</title>{fonts}<style>{CSS}</style></head><body><div class="wrap">'
            f'<a class="back" href="index.html">← Ad Board</a>'
            f'<header class="top"><h1 class="brand">Usage</h1><div class="meta">Updated <b>{e(clock)}</b> · <button class="lnk" id="refresh">Refresh</button>'
            f'<br>{e(price)}<br><span id="said"></span></div></header>'
            f'<section class="kpis" id="kpis" aria-label="Summary"></section>'
            f'<div class="filters"><div class="fl"><span>Period</span><div class="seg"><button data-period="7">7 days</button><button data-period="30">30 days</button>'
            f'<button data-period="all">All time</button></div></div><div class="fl"><span>Format</span><div class="seg" id="fmts"></div></div></div>'
            f'<nav class="tabs" role="tablist" aria-label="Views">'
            + ''.join(f'<button class="tab" role="tab" data-tab="{k}" aria-selected="false"><span class="l">{e(n)}</span><span class="h">{e(h)}</span></button>' for k, n, h in tabs)
            + '</nav>'
            f'<section class="panel" id="p-batches" data-tab="batches"><div class="bar"><p class="count"></p><label class="fl"><span>Sort</span><select id="sort">'
            f'<option value="new">Newest first</option><option value="cost">Most expensive</option><option value="rev">Most revisions</option><option value="time">Longest to make</option>'
            f'</select></label></div><div id="blist"></div>'
            f'<p class="note">First pass: everything spent until the video first reached you on Frame.io. Revisions: everything after that. '
            f'A video that never went to Frame.io has no split, so it shows a dash and counts in the total only. '
            f'Rounds: new versions sent to Frame.io after the first. Make time: the time something was actually working on the ad (kie generating, cloud runs, Claude working), '
            f'never the time it waited for you. It carries a ≈ because the Claude part is measured from the saved sessions by rule: close, not to the minute. '
            f'Edits of real footage use no kie credits, so they show $0.00. Click a batch to see each video.</p></section>'
            f'<section class="panel" id="p-formats" data-tab="formats" hidden><div class="bar"><p>What one finished video costs in each format, on average.</p>{legend}</div><div id="flist"></div></section>'
            f'<section class="panel" id="p-timeline" data-tab="timeline" hidden><div class="bar"><p id="tsum"></p>{legend}</div><div id="tchart"></div></section>'
            f'<section class="panel" id="p-claude" data-tab="claude" hidden><div id="clist"></div></section>'
            f'<footer>Credits are what kie itself reports for each task, in dollars at your real price: {e(check)}. No dollar or credit figure here is an estimate, and a number that is not on record shows a dash. '
            f'kie use outside the video projects (statics made in the brand workspace, one-off tests) lowers the balance but is not listed under a batch.{e(fell)}</footer>'
            f'</div><div id="tip" role="tooltip"></div><script>const D={blob},BASE={json.dumps(base)},TOKEN={json.dumps(token)};{JS}</script></body></html>')


def write(scan=0.0, fetch=None, max_age=60, now=None):
    """Rebuild the page. `scan` = seconds to spend reading new Claude transcript lines (0: none, None: no limit)."""
    import frame_review
    if scan != 0:   # tasks finished since the last rebuild are checked against kie's own record (free reads, a few seconds at most)
        with contextlib.suppress(Exception):
            verify(limit=80, budget=4)
    data = gather(now=now, scan=scan, fetch=fetch, max_age=max_age)
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / f'usage.html.{os.getpid()}.part'
    tmp.write_text(render(data, f'http://{frame_review.HOST}:{frame_review.PORT}', frame_review.token()))
    tmp.replace(OUT / 'usage.html')
    with contextlib.suppress(OSError):
        save(store() / 'summary.json', {'at': data['now'], 'low_now': low_now(data), 'week': data['week']})
    return OUT / 'usage.html'


def handle(payload):
    """The page's own refresh, through the board helper: a live balance read, and a rebuild when asked."""
    import frame_review
    import secrets
    if not isinstance(payload, dict) or not secrets.compare_digest(str(payload.get('token') or ''), frame_review.token()):
        return 403, {'ok': False, 'error': 'This page is out of date. Reopen it with `ctl.py usage`.'}
    bal = balance(max_age=20)
    rebuilt = False
    if payload.get('rebuild'):
        write(scan=3.0, max_age=20)
        rebuilt = True
    return 200, {'ok': True, 'credits': bal['credits'], 't': bal['t'], 'error': bal['error'], 'rebuilt': rebuilt}


if __name__ == '__main__':
    print(write(scan=5.0))
