"""Frame approvals from the browser: the owner presses a button, the decision lands on disk, nothing has to be pasted.

  the ad board ("Approve frames") and each REVIEW.html ("Send to Claude")
        -> POST http://127.0.0.1:8790/frames  (this file, `frame_review.py serve`, started by `ctl.py dash` and the watcher)
        -> projects/<ad>/FRAME_REVIEW.json   the newest decision (what every session and the board read)
           projects/<ad>/FRAME_REVIEW.log.jsonl   every decision ever sent
           projects/<ad>/FRAME_REVIEW.txt    the same notes as text (fed to tools/feedback.py ingest when he asked for changes)

What happens next:
  an AI ad made by the cloud controller (newest run = a finished ai-frames / ai-frames-revise):
      all approved      -> `ctl.py submit ai-clips <ad> --go` starts by itself
      frames to redo    -> `ctl.py submit ai-frames-revise <ad> --redo ... --go` starts by itself (his notes are the redo notes)
  any other ad (built by hand on the Mac): the decision waits in FRAME_REVIEW.json; `ctl.py reviews` lists what is waiting,
      `ctl.py status` prints it, and the board shows it under In progress.

The server listens on this Mac only (127.0.0.1) and refuses any request without the token that only local pages carry
(cloud/controller/board-token). Stdlib only, so it runs on any of the Mac's Pythons.
"""
import http.server
import json
import os
import pathlib
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.request

C = pathlib.Path(__file__).resolve().parent
ROOT = C.parent
STATE = C / 'controller'
HOST, PORT = '127.0.0.1', 8790
NAME = 'FRAME_REVIEW.json'
AD = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,80}')
SCENE = re.compile(r'scene_(\d+)(?:_v(\d+))?\.png$')
DECISIONS = ('approve', 'redo-frame', 'redo-clip')
FRAME_RECIPES = {'ai-frames', 'ai-frames-revise'}
TEST_AD = re.compile(r'^(zz-|cloud-test)')
LOG = C / '.scratch' / 'frame-review.log'


def load(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return default


def token():
    """The secret only this Mac's own pages know. Made once."""
    f = STATE / 'board-token'
    try:
        t = f.read_text().strip()
    except OSError:
        t = ''
    if len(t) < 20:
        t = secrets.token_urlsafe(24)
        STATE.mkdir(parents=True, exist_ok=True)
        f.write_text(t)
        os.chmod(f, 0o600)
    return t


def newest_frames(proj):
    """{beat: Path} with the newest version of each starting frame."""
    best = {}
    folder = pathlib.Path(proj) / 'FRAMES'
    if folder.is_dir():
        for f in folder.glob('scene_*.png'):
            m = SCENE.fullmatch(f.name)
            if m and (int(m.group(1)) not in best or int(m.group(2) or 1) > best[int(m.group(1))][0]):
                best[int(m.group(1))] = (int(m.group(2) or 1), f)
    return {n: best[n][1] for n in sorted(best)}


def read(proj):
    d = load(pathlib.Path(proj) / NAME)
    return d if isinstance(d, dict) and isinstance(d.get('beats'), dict) else None


def current(proj, frames=None):
    """The decision that still stands for the frames on disk, or None (never sent, or newer frames were made since)."""
    d = read(proj)
    if not d:
        return None
    frames = newest_frames(proj) if frames is None else frames
    files = list(frames.values()) if isinstance(frames, dict) else list(frames)
    made = max([f.stat().st_mtime for f in files if f.exists()] + [0])
    return None if made > float(d.get('sent_at') or 0) + 1 else d


def text_form(d):
    """The same lines the old "Copy notes" button made (tools/feedback.py ingest reads them)."""
    out = [f"REVIEW {d['ad']}"]
    for n in sorted(d['beats'], key=int):
        b = d['beats'][n]
        out.append(f"beat {n}: {b['decision']}" + (f" — {b['note']}" if b.get('note') else '') + (' [RULE]' if b.get('rule') and b.get('note') else ''))
    for t in d.get('master_notes') or []:
        out.append(f"master @{t['t']}s: {t['note']}" + (' [RULE]' if t.get('rule') else ''))
    if d.get('ad_note'):
        out.append(f"ad: {d['ad_note']}" + (' [RULE]' if d.get('ad_rule') else ''))
    return '\n'.join(out) + '\n'


def clean(payload, proj, now=None):
    """Browser payload -> the decision record. ValueError (in words the owner can read) when it cannot be accepted."""
    proj = pathlib.Path(proj)
    frames = newest_frames(proj)
    seen = payload.get('frames') or {}
    beats = {}
    if payload.get('approve_all'):
        if not frames:
            raise ValueError('This ad has no starting frames yet.')
        beats = {str(n): {'decision': 'approve', 'note': '', 'rule': False} for n in frames}
    else:
        for k, v in (payload.get('beats') or {}).items():
            if not str(k).isdigit() or not isinstance(v, dict):
                raise ValueError('The page sent something unreadable. Reload it and try again.')
            decision, note = str(v.get('d') or v.get('decision') or ''), ' '.join(str(v.get('note') or '').split())[:1500]
            if not decision and not note:
                continue
            if decision not in DECISIONS:
                raise ValueError(f'Beat {k} has a note but no choice. Pick Approve or Redo for it.')
            beats[str(int(k))] = {'decision': decision, 'note': note, 'rule': bool(v.get('rule'))}
            if v.get('frame'):
                seen[str(int(k))] = str(v['frame'])
        missing = [n for n in frames if str(n) not in beats]
        if missing:
            raise ValueError('No choice yet for beat ' + ', '.join(map(str, missing)) + '. Pick Approve or Redo for each frame.')
    for n, name in seen.items():   # he must be deciding on the frames that are on disk now, not an older page
        if str(n).isdigit() and int(n) in frames and name and frames[int(n)].name != name:
            raise ValueError(f'Beat {n} has a newer frame than this page shows. Reload the page and look again.')
    masters = [{'t': float(t.get('t') or 0), 'note': ' '.join(str(t.get('note') or '').split())[:1500], 'rule': bool(t.get('rule'))}
               for t in (payload.get('master_notes') or []) if isinstance(t, dict) and str(t.get('note') or '').strip()]
    ad_note = ' '.join(str(payload.get('ad_note') or '').split())[:1500]
    if not beats and not masters and not ad_note:
        raise ValueError('Nothing to send yet.')
    changes = [n for n, b in beats.items() if b['decision'] != 'approve']
    return {'ad': proj.name, 'sent_at': now or time.time(), 'source': str(payload.get('source') or 'page')[:20],
            'verdict': 'changes' if changes or masters or ad_note else 'approved', 'beats': beats, 'redo': sorted(map(int, changes)),
            'frames': {str(n): f.name for n, f in frames.items()}, 'master_notes': masters, 'ad_note': ad_note,
            'ad_rule': bool(payload.get('ad_rule')) and bool(ad_note), 'follow_up': None, 'handled_at': None}


def write(proj, d):
    proj = pathlib.Path(proj)
    tmp = proj / (NAME + '.part')
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(proj / NAME)


def save(ad, payload, now=None, root=None):
    """Validate and store one decision. Returns the record."""
    if not AD.fullmatch(str(ad or '')):
        raise ValueError('Unknown ad.')
    proj = (root or ROOT) / 'projects' / ad
    if not (proj / 'plan.json').exists():
        raise ValueError(f'No project named {ad} on this Mac.')
    d = clean(payload, proj, now)
    write(proj, d)
    with open(proj / 'FRAME_REVIEW.log.jsonl', 'a') as f:
        f.write(json.dumps(d) + '\n')
    (proj / 'FRAME_REVIEW.txt').write_text(text_form(d))
    return d


def follow_up(ad, d, state=None):
    """The controller command this decision starts by itself, or None when a person (a Claude session) has to act."""
    runs = [r for r in (load((state or STATE) / 'runs.json', {}) or {}).values() if r.get('ad') == ad]
    last = max(runs, key=lambda r: r.get('submitted') or 0) if runs else None
    if not last or not last.get('collected') or last.get('final_state') != 'done' or last.get('recipe') not in FRAME_RECIPES:
        return None
    if (last.get('collected_at') or 0) > d['sent_at']:
        return None
    batch = ['--batch', last['batch']] if last.get('batch') else []
    if d['verdict'] == 'approved':
        return ['submit', 'ai-clips', ad, '--go'] + batch
    todo = [(n, b) for n, b in sorted(d['beats'].items(), key=lambda x: int(x[0])) if b['decision'] != 'approve']
    if d.get('master_notes') or d.get('ad_note') or not todo or any(b['decision'] != 'redo-frame' or not b['note'] for _, b in todo):
        return None   # a whole-ad note, a clip redo before clips exist, or a redo with no note: needs a person
    cmd = ['submit', 'ai-frames-revise', ad, '--go'] + batch
    for n, b in todo:
        cmd += ['--redo', f"{ad}:{n}:frame:{b['note']}"]
    return cmd


def pending(root=None, now=None):
    """Decisions nobody has acted on yet: [(ad, record)]. Acted on = marked handled, a follow-up run started fine,
    newer frames exist (his redo was done), or clips exist (his approval was used)."""
    out = []
    projects = (root or ROOT) / 'projects'
    for f in sorted(projects.glob(f'*/{NAME}')) if projects.is_dir() else []:
        d = current(f.parent)
        if not d or d.get('handled_at') or (d.get('follow_up') or {}).get('exit') == 0:
            continue
        if d['verdict'] == 'approved' and any((f.parent / 'CLIPS').glob('clip_*.mp4')):
            continue
        out.append((f.parent.name, d))
    return out


def mark_handled(ad, root=None, now=None):
    proj = (root or ROOT) / 'projects' / ad
    d = read(proj)
    if not d:
        return False
    d['handled_at'] = now or time.time()
    write(proj, d)
    return True


# ---- clip / hook picks (tools/option_picker.py pages) ---------------------------------------------------------------

def options_of(proj):
    d = load(pathlib.Path(proj) / 'OPTIONS.json')
    return d if isinstance(d, dict) and isinstance(d.get('slots'), list) and d['slots'] else None


def picks_of(proj):
    """His picks for the option set that is on disk now, or None (none sent, or the options changed since)."""
    d, o = load(pathlib.Path(proj) / 'OPTIONS_PICK.json'), options_of(proj)
    return d if isinstance(d, dict) and o and d.get('sig') == o.get('sig') else None


def save_picks(ad, payload, now=None, root=None):
    if not AD.fullmatch(str(ad or '')):
        raise ValueError('Unknown ad.')
    proj = (root or ROOT) / 'projects' / ad
    o = options_of(proj)
    if not o:
        raise ValueError(f'No options page for {ad} on this Mac.')
    if payload.get('sig') != o.get('sig'):
        raise ValueError('The options changed since this page was made. Reload it and pick again.')
    got = payload.get('slots') or []
    if len(got) != len(o['slots']):
        raise ValueError('The page sent something unreadable. Reload it and try again.')
    out = []
    for slot, g in zip(o['slots'], got):
        ids = {x['id']: x for x in slot['options']}
        pick, note = str((g or {}).get('pick') or ''), ' '.join(str((g or {}).get('note') or '').split())[:1500]
        if pick != 'none' and pick not in ids:
            raise ValueError(f"Pick one option in '{slot['name']}' first.")
        if pick == 'none' and not note:
            raise ValueError(f"Say what to look for instead in '{slot['name']}'.")
        notes = {k: ' '.join(str(v).split())[:800] for k, v in ((g or {}).get('notes') or {}).items() if k in ids and str(v).strip()}
        out.append({'slot': slot['name'], 'pick': pick, 'pick_name': ids[pick]['name'] if pick in ids else None,
                    'pick_file': ids[pick]['file'] if pick in ids else None, 'note': note,
                    'notes': {ids[k]['name']: v for k, v in notes.items()}})
    d = {'ad': ad, 'sig': o['sig'], 'sent_at': now or time.time(), 'slots': out, 'handled_at': None}
    tmp = proj / 'OPTIONS_PICK.json.part'
    tmp.write_text(json.dumps(d, indent=1))
    tmp.replace(proj / 'OPTIONS_PICK.json')
    with open(proj / 'OPTIONS_PICK.log.jsonl', 'a') as f:
        f.write(json.dumps(d) + '\n')
    return d


def learn_picks(ad, d):
    """Taste rule T29: log which option he chose (and any note) so the next ad starts from his pattern."""
    py = ROOT / '.venv' / 'bin' / 'python'
    plan = ROOT / 'projects' / ad / 'plan.json'
    for x in d['slots']:
        words = (f"Picked '{x['pick_name']}' for {x['slot']}" if x['pick_name'] else f"None of the options for {x['slot']}") + (f": {x['note']}" if x['note'] else '')
        words += ''.join(f" (note on '{k}': {v})" for k, v in x['notes'].items())
        cmd = [str(py) if py.exists() else sys.executable, '-I', str(ROOT / 'tools' / 'feedback.py'), 'add', ad, words, '--src', 'picker']
        if not plan.exists():
            cmd += ['--skill', 'raw-ugc-editor']
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            log(f'{ad}: pick logged (exit {p.returncode})')
        except Exception as e:
            log(f'{ad}: pick NOT logged: {type(e).__name__}: {e}')


def pending_picks(root=None):
    out = []
    projects = (root or ROOT) / 'projects'
    for f in sorted(projects.glob('*/OPTIONS_PICK.json')) if projects.is_dir() else []:
        d = picks_of(f.parent)
        if d and not d.get('handled_at'):
            out.append((f.parent.name, d))
    return out


def handle_picks(payload, start=True):
    if not isinstance(payload, dict) or not secrets.compare_digest(str(payload.get('token') or ''), token()):
        return 403, {'ok': False, 'error': 'This page is out of date. Ask Claude to rebuild it.'}
    ad = str(payload.get('ad') or '')
    try:
        d = save_picks(ad, payload)
    except ValueError as e:
        return 400, {'ok': False, 'error': str(e)}
    log(f"{ad}: picks sent ({', '.join((x['pick_name'] or 'none') for x in d['slots'])}) -> waits for a session")
    if start and not TEST_AD.match(ad):
        threading.Thread(target=learn_picks, args=(ad, d), daemon=True).start()
    refresh_board()
    return 200, {'ok': True, 'message': 'Saved. Claude uses your pick next.'}


# ---- final approval (what is on Frame.io) -> Google Drive -> media buyer sheet tracker ---------------------------
# Approve on the board once a Frame.io video needs no more revisions; Claude puts it on Drive and
# gives the link; then a tick once it is in the media buyer's sheet. The hand-off itself is cloud/deliver.py.

APPROVED = 'APPROVED.json'


def deliver_mod():
    if str(C) not in sys.path:
        sys.path.insert(0, str(C))
    import deliver
    return deliver


def approve_ad(ad, now=None, root=None):
    """Write projects/<ad>/APPROVED.json for the version on Frame.io now. ValueError in plain words."""
    if not AD.fullmatch(ad or ''):
        raise ValueError('That ad name is not valid.')
    proj = (root or ROOT) / 'projects' / ad
    st = load(proj / 'frameio.json', {}) or {}
    files = st.get('files') or []
    if not files:
        raise ValueError(f'{ad} is not on Frame.io, so there is nothing to approve.')
    f = files[-1]
    d = {'ad': ad, 'batch': deliver_mod().batch_of(proj, st), 'file_id': f['id'], 'v': f.get('v'),
         'notes_at_approval': list((st.get('logged') or {}).get(f['id'], [])), 'approved_at': now or time.time()}
    (proj / APPROVED).write_text(json.dumps(d, indent=1))
    with open(proj / 'APPROVED.log.jsonl', 'a') as lg:
        lg.write(json.dumps(d) + '\n')
    return d


def start_delivery(batch):
    """Run cloud/deliver.py on its own (a Drive upload can take minutes and must outlive a helper restart)."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    deliver_mod().save_record(batch, {'batch': batch, 'state': 'queued', 'queued_at': time.time(), 'error': None})
    with open(C / '.scratch' / 'deliver.log', 'a') as out:
        subprocess.Popen([sys.executable, str(C / 'deliver.py'), batch], stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                         start_new_session=True, cwd=str(C))
    log(f'{batch}: all approved -> deliver.py started')


def handle_approve(payload, start=True):
    """{ad} approves one video, {ads: [...]} the videos he sees under one batch, {ad, undo: true} takes it back,
    {batch, retry: true} runs a stopped hand-off again. The Drive upload starts once every video of the batch is approved."""
    if not isinstance(payload, dict) or not secrets.compare_digest(str(payload.get('token') or ''), token()):
        return 403, {'ok': False, 'error': 'This page is out of date. Reopen the board with `ctl.py dash`.'}
    dv = deliver_mod()
    ad, batch = str(payload.get('ad') or ''), str(payload.get('batch') or '')
    try:
        if payload.get('undo'):
            if not AD.fullmatch(ad):
                raise ValueError('That ad name is not valid.')
            proj = ROOT / 'projects' / ad
            batch = dv.batch_of(proj)
            if (dv.records().get(batch) or {}).get('state') in ('queued', 'uploading', 'delivered'):
                raise ValueError('This batch is already going to Drive, so the approval can no longer be taken back.')
            (proj / APPROVED).unlink(missing_ok=True)
            log(f'{ad}: approval taken back')
            refresh_board()
            return 200, {'ok': True, 'message': 'Approval taken back.'}
        ads = [ad] if ad else [str(a) for a in payload.get('ads') or []][:40]
        if ads:   # one video, or the rows he sees under one batch ("Approve all")
            done = [approve_ad(a) for a in ads]
            batches = {x['batch'] for x in done}
            if len(batches) != 1:
                raise ValueError('Those videos are not in the same batch.')
            batch = batches.pop()
        elif not (batch and payload.get('retry')):
            raise ValueError('Nothing to approve was named.')
    except ValueError as e:
        return 400, {'ok': False, 'error': str(e)}
    ms, ok = dv.batch_state(batch)
    if ads:
        log(f"{', '.join(ads)}: approved for Drive ({len(ok)}/{len(ms)} of {batch})")
    if ms and len(ok) == len(ms):
        if (dv.records().get(batch) or {}).get('state') in ('queued', 'uploading'):
            return 200, {'ok': True, 'message': 'Already uploading to Drive.'}
        if start and not TEST_AD.match(ms[0].name):
            start_delivery(batch)
        refresh_board()
        return 200, {'ok': True, 'delivering': True, 'message': 'Approved. Uploading to Drive now; the link comes in Slack.'}
    refresh_board()
    left = len(ms) - len(ok)
    return 200, {'ok': True, 'delivering': False,
                 'message': f"Approved. {left} more in this batch, then it all goes to Drive."}


def handle_sheet(payload, start=True):
    """{batch, on}: the owner's tick for 'this is in the media buyer sheet'."""
    if not isinstance(payload, dict) or not secrets.compare_digest(str(payload.get('token') or ''), token()):
        return 403, {'ok': False, 'error': 'This page is out of date. Reopen the board with `ctl.py dash`.'}
    batch, on = str(payload.get('batch') or ''), bool(payload.get('on'))
    try:
        deliver_mod().set_in_sheet(batch, on)
    except ValueError as e:
        return 400, {'ok': False, 'error': str(e)}
    log(f"{batch}: {'in' if on else 'not in'} the media buyer sheet")
    refresh_board()
    return 200, {'ok': True, 'message': 'Marked as in the sheet.' if on else 'Marked as not in the sheet yet.'}


# ---- "Revisions done" (one button per batch, one per video) --------------------------------------------------------
# One button tells Claude the owner's revision notes are in the Frame.io comments (one per batch).
# Press -> the Frame.io comments of the ads he sent are pulled into feedback/log.jsonl -> controller/revision-requests.json
# says the batch waits -> an unattended Claude job starts on it (cloud/claude_job.py: headless `claude -p` on his Claude
# login, one per batch, no session has to be open; the watcher starts it again if it stops part-way). `ctl.py status` and
# `ctl.py reviews` still show the batch to any session. An ad's part is done once a newer version of it is on Frame.io.
#
# One button per video too (so a batch where only one video has notes sends only that one). The request's `ads` is the list of videos he sent, and nothing else is revised:
#   batch button   every video of the batch on Frame.io that is not approved and not locked
#   row button     that one video ({ad}); `ad_pressed` keeps its own press time
# A press on a batch whose request is still open ADDS to it (the other videos keep their press time and their job).
# A video added while a round of work is already running (`late`) is not given to that running job: when the round is
# marked done (`reviews --revised`, or the watcher sees every new version up) the late videos become the next round
# (state 'waiting' again, a new press time), and the watcher starts a Claude job on them.

REVISIONS = 'revision-requests.json'
PULLED = re.compile(r'(\d+) new comment')
OPEN = ('pulling', 'waiting', 'working')     # a request somebody still has to finish
PULLS = threading.Lock()                     # one pull at a time in this helper: two presses never interleave


def revision_requests():
    return load(STATE / REVISIONS, {}) or {}


def update_revision(batch, change):
    """Change one request under the file lock: `change(the entry now)` returns the fields to set."""
    import fcntl
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / 'revision-requests.lock', 'w') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        d = revision_requests()
        d[batch] = {**d.get(batch, {}), **change(dict(d.get(batch) or {}))}
        tmp = STATE / (REVISIONS + '.part')
        tmp.write_text(json.dumps(d, indent=1))
        tmp.replace(STATE / REVISIONS)
        return d[batch]


def save_revision(batch, entry):
    return update_revision(batch, lambda old: entry)


def open_notes(proj):
    """Comments logged on the newest Frame.io version that no newer version answers yet."""
    st = load(pathlib.Path(proj) / 'frameio.json', {}) or {}
    files = st.get('files') or []
    if not files:
        return 0
    done = set(st.get('completed') or [])
    return len([c for c in (st.get('logged') or {}).get(files[-1]['id'], []) if c not in done])


def pushed_at(proj):
    """When the ad's newest Frame.io version went up (epoch seconds; 0 when it has none or the time cannot be read)."""
    files = (load(pathlib.Path(proj) / 'frameio.json', {}) or {}).get('files') or []
    try:
        return time.mktime(time.strptime(str(files[-1].get('pushed'))[:19], '%Y-%m-%dT%H:%M:%S')) if files else 0.0
    except (ValueError, TypeError, OverflowError, AttributeError):
        return 0.0


def pressed_for(req, ad):
    """When he pressed for this video: its own press (the row button, or added to an open request) or the batch press."""
    return float((req.get('ad_pressed') or {}).get(ad) or req.get('pressed_at') or 0)


def revising(req, ad, pushed):
    """This video's part of the request is open: he sent THIS video (it is in the request's own list) after the version
    that is up went up, and no newer version is on Frame.io yet. A video he did not send is never 'revisions sent'."""
    return bool(req and req.get('state') in OPEN and ad in (req.get('ads') or []) and pressed_for(req, ad) > float(pushed or 0))


def locked(proj):
    return bool((load(pathlib.Path(proj) / 'plan.json', {}) or {}).get('locked'))


def revisable(batch, root=None):
    """The videos of a batch a "Revisions done" press can send: on Frame.io, not approved, not locked."""
    dv = deliver_mod()
    return [m for m in dv.members(batch, root or ROOT) if not dv.approved_now(m) and not locked(m)]


def pull_ads(ads, runner=None):
    """Pull the Frame.io comments of these ads. {ad: new comment count, or an error sentence}."""
    py = ROOT / '.venv' / 'bin' / 'python'
    out = {}
    for ad in ads:
        try:
            r = (runner or subprocess.run)([str(py) if py.exists() else sys.executable, str(ROOT / 'tools' / 'frameio.py'), 'pull', ad],
                                           capture_output=True, text=True, timeout=600, cwd=str(ROOT))
            got = PULLED.findall((r.stdout or '') + (r.stderr or ''))
            out[ad] = int(got[-1]) if r.returncode == 0 and got else f'could not read comments (exit {r.returncode})'
        except Exception as e:
            out[ad] = f'could not read comments ({type(e).__name__})'
    return out


def claude_mod():
    if str(C) not in sys.path:
        sys.path.insert(0, str(C))
    import claude_job
    return claude_job


def job_anchor(req):
    """The moment the current round of work on a request was asked for: the press, or his later "Start Claude on it"."""
    return max(float(req.get('pressed_at') or 0), float(req.get('restarted_at') or 0))


def in_flight(batch, req, now=None):
    """A round of work on this request has its list of videos already: a session took it ('working'), or its unattended
    job is running or starting. A video he adds now is not on that list."""
    if req.get('state') == 'working':
        return True
    try:
        cj = claude_mod()
        if cj.live(batch):
            return True
        rec = cj.record(batch) or {}
        return rec.get('kind') == 'revision' and rec.get('state') == 'starting' and (now or time.time()) - float(rec.get('asked_at') or 0) < 120
    except Exception:
        return False


def late_left(batch, req):
    """{ad: when he pressed}: videos he added while a round was already running that the round did not get to. Not one
    with no notes, one whose new version went up after his press, one he approved since, or one a later job had listed."""
    dv = deliver_mod()
    try:
        rec = claude_mod().record(batch) or {}
    except Exception:
        rec = {}
    out = {}
    for ad, t in (req.get('late') or {}).items():
        proj = ROOT / 'projects' / ad
        if ad not in (req.get('ads') or []) or not (req.get('notes') or {}).get(ad):
            continue
        if pushed_at(proj) > float(t) or dv.approved_now(proj) or locked(proj):
            continue
        if rec.get('kind') == 'revision' and ad in (rec.get('ads') or []) and float(rec.get('asked_at') or 0) >= float(t):
            continue
        out[ad] = float(t)
    return out


def start_claude(batch, entry, spawn=None):
    """Start the unattended Claude job for this batch (cloud/claude_job.py): one per batch, on his Claude login.
    Never raises: the press is already on disk, and the watcher starts the job on its next pass if this did not."""
    try:
        got = claude_mod().start('revision', batch, entry.get('ads') or [], spawn=spawn, anchor=job_anchor(entry),
                                 notes={a: n for a, n in (entry.get('notes') or {}).items() if a in (entry.get('ads') or [])})
    except Exception as e:
        got = f'failed ({type(e).__name__}: {e})'
    log(f'{batch}: Claude job {got}')
    return got


def collect_revisions(batch, runner=None, now=None, spawn=None, only=None, single=False):
    """The work behind the button (runs in a thread): pull, count, mark the batch waiting, start Claude on it.
    `only` = the videos of this press (default: the request's whole list); `single` = the row button, so a video with no
    notes on Frame.io is taken out of the request again and its row says so."""
    with PULLS:
        req = revision_requests().get(batch) or {}
        ads = list(only) if only else list(req.get('ads') or [m.name for m in deliver_mod().members(batch, ROOT)])
        pulled = pull_ads(ads, runner)
        counts = {a: open_notes(ROOT / 'projects' / a) for a in ads}
        errors = {a: v for a, v in pulled.items() if isinstance(v, str)}
        when = now or time.time()

        def change(old):
            out = {'pulled_at': when, 'notes': {**(old.get('notes') or {}), **counts},
                   'new': {**(old.get('new') or {}), **{a: v for a, v in pulled.items() if isinstance(v, int)}},
                   'errors': {**{a: v for a, v in (old.get('errors') or {}).items() if a not in ads}, **errors}}
            keep = list(old.get('ads') or [])
            if single and not errors and not any(counts.values()):   # the row button on a video with no notes: nothing to revise
                keep = [a for a in keep if a not in ads]
                out.update(ads=keep, empty={**(old.get('empty') or {}), **{a: when for a in ads}},
                           late={a: t for a, t in (old.get('late') or {}).items() if a not in ads},
                           ad_pressed={a: t for a, t in (old.get('ad_pressed') or {}).items() if a not in ads})
            total = sum(int(out['notes'].get(a) or 0) for a in keep)
            if old.get('state') in ('pulling', 'no-notes') or not keep:
                out['state'] = 'waiting' if total else 'no-notes'
            return out
        entry = update_revision(batch, change)
        total = sum(int((entry.get('notes') or {}).get(a) or 0) for a in entry.get('ads') or [])
        log(f"{batch}: revisions done pressed ({', '.join(ads)}) -> {sum(counts.values())} open note(s) on {len([n for n in counts.values() if n])} ad(s)"
            + (f' (errors: {errors})' if errors else ''))
        if total and entry.get('auto') and entry.get('state') == 'waiting':   # 'working': a round is running; late videos wait for its end
            start_claude(batch, entry, spawn)
    refresh_board()
    return entry


def handle_revisions(payload, start=True):
    """{batch}: the owner finished leaving notes on this Frame.io batch (every video of it that is not approved or locked).
    {ad}: on that one video only. {batch, restart: true}: "Start Claude on it" on a stalled batch."""
    if not isinstance(payload, dict) or not secrets.compare_digest(str(payload.get('token') or ''), token()):
        return 403, {'ok': False, 'error': 'This page is out of date. Reopen the board with `ctl.py dash`.'}
    dv = deliver_mod()
    ad, batch = str(payload.get('ad') or ''), str(payload.get('batch') or '')
    if ad:   # the row button: this video only
        proj = ROOT / 'projects' / ad
        if not AD.fullmatch(ad) or not (load(proj / 'frameio.json', {}) or {}).get('files'):
            return 400, {'ok': False, 'error': 'This video is not on Frame.io, so there are no notes to read.'}
        if locked(proj):
            return 400, {'ok': False, 'error': 'This video is locked (launched), so it is not revised.'}
        if dv.approved_now(proj):
            return 400, {'ok': False, 'error': 'You approved this video, so it is not sent for revisions. Press Take back on it first if it still needs a change.'}
        batch, want = dv.batch_of(proj), [ad]
    else:
        if not (dv.members(batch, ROOT) if batch else []):
            return 400, {'ok': False, 'error': 'Nothing of this batch is on Frame.io.'}
        want = [m.name for m in revisable(batch)]
    now = time.time()
    try:
        auto = bool(claude_mod().enabled())
    except Exception:
        auto = False
    old = revision_requests().get(batch) or {}
    again = bool(payload.get('restart')) and not ad and old.get('state') in OPEN
    left = 0 if ad or again else len(dv.members(batch, ROOT)) - len(want)   # approved (or locked) videos the batch press leaves alone
    if again:   # "Start Claude on it": the videos of the request, never one he approved since
        want = [a for a in old.get('ads') or [] if a in want]
    if not want:
        return 400, {'ok': False, 'error': 'Every video of this batch on Frame.io is approved, so there is nothing to revise. '
                                           'Press Take back on a video first if it still needs a change.'}
    running = in_flight(batch, {**old, 'state': 'waiting'}, now)   # an unattended job of this batch is alive right now
    busy = False
    if again:   # the same request (his press time stands), a new round of work on all of its videos
        save_revision(batch, {'ads': want, 'restarted_at': now, 'state': 'pulling', 'auto': auto, 'error': None,
                              **({} if running else {'late': {}})})
        only, what = None, 'restarted_at'
    elif old.get('state') in OPEN and any(revising(old, a, pushed_at(ROOT / 'projects' / a)) for a in old.get('ads') or []):
        # the request is still open: add to it, never reset the videos already in it. `late` = a job or a session already
        # has its list of videos; a restart ("Start Claude on it", the watcher) lists every video and clears it
        busy = running or old.get('state') == 'working'

        def add(cur):
            return {'ads': list(cur.get('ads') or []) + [a for a in want if a not in (cur.get('ads') or [])],
                    'ad_pressed': {**(cur.get('ad_pressed') or {}), **{a: now for a in want}},
                    'late': {**(cur.get('late') or {}), **({a: now for a in want} if busy else {})},
                    'empty': {a: t for a, t in (cur.get('empty') or {}).items() if a not in want}, 'error': None}
        update_revision(batch, add)
        only, what = want, 'added_at'
    else:   # a new request. A job still finishing the round before it does not know these videos: they are its next round
        busy = running
        save_revision(batch, {'batch': batch, 'ads': want, 'pressed_at': now, 'state': 'pulling', 'picked_up_at': None, 'error': None,
                              'auto': auto, 'restarted_at': None, 'ad_pressed': {}, 'late': {a: now for a in want} if busy else {},
                              'empty': {}, 'notes': {}, 'new': {}, 'errors': {}})
        only, what = None, 'pressed_at'
    with open(STATE / 'revision-requests.log.jsonl', 'a') as lg:
        lg.write(json.dumps({'batch': batch, what: now, 'ads': want, **({'row': ad} if ad else {})}) + '\n')
    if start and not TEST_AD.match(want[0]):
        threading.Thread(target=collect_revisions, args=(batch,), kwargs={'only': only, 'single': bool(ad)}, daemon=True).start()
    refresh_board()
    where = 'this video' if ad else 'this batch'
    skipped = f" {left} approved video{'s are' if left != 1 else ' is'} left alone." if left else ''
    if running:   # only said while a job really is alive; otherwise the row and the batch header say who has it
        return 200, {'ok': True, 'message': f'Got it. Claude is in the middle of this batch; it starts on {where} right after, with no need to press again.{skipped}'}
    if what == 'added_at':
        return 200, {'ok': True, 'message': f'Got it. Your Frame.io notes on {where} are added to the revisions already open for this batch.{skipped}'}
    if not auto:
        return 200, {'ok': True, 'message': f'Got it. Your Frame.io notes on {where} are being read; the next Claude session starts on them.{skipped}'}
    return 200, {'ok': True, 'message': f'Got it. Claude is reading your Frame.io notes on {where} and starts on them by itself.{skipped}'}


def mark_revisions(batch, state, now=None):
    """A session took the batch ('working') or finished it ('done'). Videos he added while that round was running are
    not lost with 'done': they become the next round (state 'waiting', their own press time, a fresh count of tries),
    which the watcher starts a Claude job on and `ctl.py reviews` lists again."""
    if batch not in revision_requests():
        raise ValueError(f"No Revisions done request for '{batch}'.")
    when = now or time.time()

    def change(old):
        left = late_left(batch, old) if state == 'done' else {}
        if left:
            return {'state': 'waiting', 'ads': sorted(left), 'pressed_at': max(left.values()), 'ad_pressed': left, 'late': {},
                    'restarted_at': None, 'notes': {a: (old.get('notes') or {}).get(a) for a in sorted(left)}, 'round_done_at': when}
        return {'state': state, f'{state}_at': when, **({'late': {}} if state == 'done' else {})}
    entry = update_revision(batch, change)
    if state == 'done' and entry.get('state') == 'waiting':
        log(f"{batch}: round done; next round on {', '.join(entry['ads'])} (sent while Claude was working)")
    return entry


# ---- the small local server --------------------------------------------------------------------------------------

def log(line):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, 'a') as f:
            f.write(time.strftime('[%m-%d %H:%M:%S] ') + line.rstrip() + '\n')
    except OSError:
        pass


def run_follow_up(ad, cmd, runner=None):
    """Start the controller command and write how it ended into the decision file (the board reads it)."""
    proj = ROOT / 'projects' / ad
    log(f'{ad}: starting ctl.py ' + ' '.join(cmd))
    try:
        p = (runner or subprocess.run)([sys.executable, str(C / 'ctl.py'), *cmd], capture_output=True, text=True, timeout=3600, cwd=str(C))
        code, tail = p.returncode, ((p.stdout or '') + (p.stderr or ''))[-1500:]
    except Exception as e:
        code, tail = -1, f'{type(e).__name__}: {e}'
    log(f'{ad}: ctl.py {cmd[1]} ended with exit {code}\n{tail}')
    d = read(proj)
    if d and d.get('follow_up'):
        d['follow_up'].update(exit=code, ended_at=time.time(), tail=tail[-600:])
        write(proj, d)
    refresh_board()


def refresh_board():
    try:
        if str(C) not in sys.path:
            sys.path.insert(0, str(C))
        import dash
        dash.write(thumbs=False)
    except Exception as e:
        log(f'board not refreshed: {type(e).__name__}: {e}')


def learn(ad):
    """His frame notes are revisions: log them the same way `ad.py <ad> notes` does."""
    py = ROOT / '.venv' / 'bin' / 'python'
    try:
        p = subprocess.run([str(py) if py.exists() else sys.executable, '-I', str(ROOT / 'tools' / 'feedback.py'), 'ingest',
                            str(ROOT / 'projects' / ad), str(ROOT / 'projects' / ad / 'FRAME_REVIEW.txt')], capture_output=True, text=True, timeout=900)
        log(f'{ad}: notes logged (exit {p.returncode}) {(p.stdout or p.stderr)[-300:]}')
    except Exception as e:
        log(f'{ad}: notes NOT logged: {type(e).__name__}: {e}')


def handle(payload, start=True):
    """One decision from the browser -> (http code, reply). Split from the HTTP class so tests call it directly."""
    if not isinstance(payload, dict) or not secrets.compare_digest(str(payload.get('token') or ''), token()):
        return 403, {'ok': False, 'error': 'This page is out of date. Reopen the board with `ctl.py dash`.'}
    ad = str(payload.get('ad') or '')
    try:
        d = save(ad, payload)
    except ValueError as e:
        return 400, {'ok': False, 'error': str(e)}
    cmd = follow_up(ad, d)
    if cmd:
        d['follow_up'] = {'cmd': 'ctl.py ' + ' '.join(cmd), 'started_at': time.time()}
        write(ROOT / 'projects' / ad, d)
    log(f"{ad}: {d['verdict']} from the {d['source']} ({len(d['beats'])} beats, redo {d['redo']})" + (f' -> {cmd[1]}' if cmd else ' -> waits for a session'))
    if start:
        def after():
            if d['verdict'] == 'changes' and not TEST_AD.match(ad):   # a test ad's notes are not the owner's taste
                learn(ad)
            if cmd:
                run_follow_up(ad, cmd)
        threading.Thread(target=after, daemon=True).start()
    refresh_board()
    if d['verdict'] == 'approved':
        say = 'Approved. The clips are starting in the cloud now.' if cmd else 'Approved and saved. Claude sees it and builds the clips next.'
    else:
        k = len(d['redo'])
        what = f"{k} frame{'s' if k != 1 else ''} to redo" if k else 'Your notes'
        say = f'{what}: sent. The new frames are being made in the cloud now.' if cmd else f'{what}: saved. Claude sees it and you get new frames to check.'
    return 200, {'ok': True, 'verdict': d['verdict'], 'auto': bool(cmd), 'message': say}


def handle_usage(payload):
    """The usage page's own refresh (cloud/usage.py): a live kie balance read, and a rebuild when its numbers are old."""
    if str(C) not in sys.path:
        sys.path.insert(0, str(C))
    import usage
    return usage.handle(payload)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'AdBoard/1'

    def reply(self, code, obj=None):
        body = json.dumps(obj).encode() if obj is not None else b''
        self.send_response(code)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.reply(204)

    def do_GET(self):
        if self.path.split('?')[0] == '/ping':
            return self.reply(200, {'ok': True, 'app': 'ad-board', 'pid': os.getpid(), 'version': self.server.version})
        self.reply(404, {'ok': False})

    def do_POST(self):
        route = {'/frames': handle, '/options': handle_picks, '/approve': handle_approve, '/sheet': handle_sheet, '/revisions': handle_revisions,
                 '/usage': handle_usage}.get(self.path.split('?')[0])
        if not route:
            return self.reply(404, {'ok': False})
        try:
            size = int(self.headers.get('Content-Length') or 0)
            if not 0 < size <= 300_000:
                raise ValueError
            payload = json.loads(self.rfile.read(size))
        except (ValueError, OSError):
            return self.reply(400, {'ok': False, 'error': 'The page sent something unreadable. Reload it and try again.'})
        try:
            code, obj = route(payload)
        except Exception as e:   # never leave the page hanging
            log(f'error: {type(e).__name__}: {e}')
            code, obj = 500, {'ok': False, 'error': f'Could not save ({type(e).__name__}).'}
        self.reply(code, obj)

    def log_message(self, *a):
        pass


def code_version():
    """Changes whenever this file, the board or the hand-off code changes, so ensure() restarts the helper."""
    return str(max(int((C / n).stat().st_mtime) for n in ('frame_review.py', 'dash.py', 'deliver.py', 'usage.py', 'claude_job.py') if (C / n).exists()))


def serve(port=PORT):
    srv = http.server.ThreadingHTTPServer((HOST, port), Handler)
    srv.version = code_version()
    token()
    log(f'listening on {HOST}:{port} (pid {os.getpid()})')
    srv.serve_forever()


def ping(port=PORT):
    try:
        with urllib.request.urlopen(f'http://{HOST}:{port}/ping', timeout=0.7) as r:
            d = json.loads(r.read())
            return d if d.get('app') == 'ad-board' else None
    except Exception:
        return None


def ensure(port=PORT):
    """Make sure the helper is up and runs the code that is on disk now. 'running' | 'started' | 'failed'."""
    up = ping(port)
    if up and up.get('version') == code_version():
        return 'running'
    if up:   # older code: stop it and start the current one
        try:
            os.kill(int(up['pid']), signal.SIGTERM)
            time.sleep(0.4)
        except (OSError, ValueError, KeyError):
            pass
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a') as out:
        subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve()), 'serve'], stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                         start_new_session=True, cwd=str(C))
    for _ in range(25):
        time.sleep(0.12)
        if ping(port):
            return 'started'
    return 'failed'


if __name__ == '__main__':
    if sys.argv[1:2] == ['serve']:
        serve()
    else:
        print(ensure())
