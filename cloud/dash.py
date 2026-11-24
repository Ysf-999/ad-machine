"""The ad board: one local page that shows the ads that need attention (cloud/.scratch/dashboard/index.html).

  .modal-env/bin/python cloud/ctl.py dash                 # refresh it and open it in the browser
  .modal-env/bin/python cloud/ctl.py dash --hide "<ad or batch>"   # take something off the board
  .modal-env/bin/python cloud/ctl.py dash --unhide "<ad or batch>" | --hidden

Four tabs (only work in progress and work waiting for the owner, nothing approved, no notes section):
  In progress                 running in the cloud, stopped by a check, or with Frame.io notes still to apply
  Frames to approve           AI ads whose starting frames wait for his OK: opens the frame review page (REVIEW.html)
  Getting ready for Frame.io  finished, final checks still open or not uploaded yet
  Ready for review            on Frame.io, with the link and an Approve button (and "Approve all" per batch);
                              "Revisions done" on the batch header, and a quiet one on each video that is not approved
  Sent to Drive               approved batches on Google Drive, with the link and an "In the media buyer sheet" tick
Approving the last video of a batch starts cloud/deliver.py (Drive upload, link, Frame.io clean, Slack). A batch he ticked
stays (dimmed) for 3 days; a locked ad is not shown at all.
The small "Usage" button at the top right (with the kie balance) opens the usage page, cloud/usage.py: cost per batch,
revision rounds, make time. It is rebuilt next to the board on every write.

It is a VIEW of files that already exist: the run registry (cloud/controller/runs.json), the live step state the
controller just read from the cloud, and each project's own records (plan.json, PREFLIGHT.md, frameio.json, MASTER.mp4,
REVIEW.html, FRAMES/, APPROVED.json, controller/deliveries.json). The page itself only shows; its buttons talk to the
helper (cloud/frame_review.py), and the pipeline never waits for it.
The watcher rewrites the page on every look (every 45 s while runs are open); `status`, `submit` and `collect` do too.
"""
import datetime
import html
import json
import pathlib
import re
import subprocess
import time

import claude_job
import deliver
import frame_review

C = pathlib.Path(__file__).resolve().parent
ROOT = C.parent
STATE = C / 'controller'
OUT = C / '.scratch' / 'dashboard'
FRAME_REVIEW = frame_review.FRAME_RECIPES
BASE = f'http://{frame_review.HOST}:{frame_review.PORT}'
TERMINAL = {'done', 'failed', 'blocked', 'crashed'}
TEST_AD = re.compile(r'^(zz-|cloud-test)')
STEP_WORDS = {'shotcheck': 'Shot check', 'rawrender': 'Render', 'padtail': 'Audio pad', 'plan_review': 'Plan review', 'vo': 'Voice',
              'frames': 'Starting frames', 'clips': 'Clips', 'redo': 'Redos', 'qc': 'QC', 'stitch': 'Assemble', 'masterqc': 'Final QC',
              'check': 'Check', 'rawverify': 'Verify', 'preflight': 'Final checks'}
TABS = [('progress', 'In progress', 'Being made or fixed', 'Nothing is being made right now.'),
        ('frames', 'To approve', 'Frames and clip picks', 'Nothing is waiting for your OK.'),
        ('prep', 'Getting ready', 'Claude uploads next', 'Nothing is waiting to be uploaded.'),
        ('review', 'Ready for review', 'On Frame.io for you', 'Nothing is waiting for your review.'),
        ('sent', 'Sent to Drive', 'Tick once in the sheet', 'Nothing has gone to Drive yet.')]
TAB_NOTES = {'sent': 'Put each link in the media buyer sheet and name the row there, then tick its box here.'}
SHEET_S = 30 * 86400       # a delivery he ticked as "in the media buyer sheet" stays this long, inside the closed "In the sheet" dropdown
RECENT_S = 14 * 86400      # an ad on Frame.io or with a frame review older than this drops off the board
PREP_S = 7 * 86400         # a finished, never-uploaded render older than this is treated as abandoned
MINE = 'Claude fixes this and sends it again. Nothing for you to do.'
SCENE = re.compile(r'scene_(\d+)(?:_v(\d+))?\.png$')


def load(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except Exception:
        return default


def step_label(stages):
    return ' + '.join(STEP_WORDS.get(s, s) for s in stages if s != 'padtail') or 'Step'


def stamp(text):
    """'2026-11-22T03:29:32' -> epoch seconds (local time); None when it cannot be read."""
    try:
        return datetime.datetime.strptime(str(text)[:19], '%Y-%m-%dT%H:%M:%S').timestamp()
    except Exception:
        return None


def ago(t, now):
    if not t:
        return ''
    d = max(0, now - t)
    if d < 90:
        return 'just now'
    if d < 3600:
        return f'{d / 60:.0f} min ago'
    if d < 86400:
        return f'{d / 3600:.0f} h ago'
    return f'{d / 86400:.0f} d ago'


def pretty(ad, plan):
    title = (plan or {}).get('title') or (plan or {}).get('name')
    if isinstance(title, str) and 2 < len(title) < 70:
        return title
    if '---' in ad:   # "<batch>-option-a---green-sofa" -> "Option A · Green sofa"
        head, tail = ad.split('---', 1)
        tail = tail.replace('-', ' ').strip()
        opt = re.search(r'option-([a-z0-9]+)$', head)
        if tail:
            return (f'Option {opt.group(1).upper()} · ' if opt else '') + tail[:1].upper() + tail[1:]
    words = re.sub(r' +', ' ', re.sub(r'-h(\d+)$', ' · Hook \\1', ad).replace('-', ' '))
    return words[:1].upper() + words[1:]


def hidden():
    """What the owner asked to take off the board: {'ads': [...], 'batches': [...]} in controller/board-hidden.json."""
    data = load(STATE / 'board-hidden.json', {}) or {}
    return {'ads': list(data.get('ads') or []), 'batches': list(data.get('batches') or [])}


def hide(names, on=True):
    """Add names to (or remove them from) the hidden list. A name that is a known batch hides the batch, else the ad."""
    data = hidden()
    batches = {r.get('batch') for r in (load(STATE / 'runs.json', {}) or {}).values()}
    projects = ROOT / 'projects'
    if projects.is_dir():
        batches |= {(load(f, {}) or {}).get('batch') for f in projects.glob('*/frameio.json')}
    for name in names:
        key = 'batches' if name in batches and not (projects / name).is_dir() else 'ads'
        if on and name not in data[key]:
            data[key].append(name)
        if not on:
            data['ads'] = [x for x in data['ads'] if x != name]
            data['batches'] = [x for x in data['batches'] if x != name]
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / 'board-hidden.json').write_text(json.dumps(data, indent=1) + '\n')
    return data


def preflight_facts(proj, master_mtime):
    """(state, text) from PREFLIGHT.md: 'none' | 'old' | 'fail' | 'boxes' | 'ready'."""
    f = proj / 'PREFLIGHT.md'
    if not f.exists():
        return 'none', 'final checks not run yet'
    if master_mtime and f.stat().st_mtime + 2 < master_mtime:
        return 'old', 'final checks are for an older render'
    t = f.read_text(errors='replace')
    fails = [ln[2:].strip() for ln in t.splitlines() if ln.startswith('- FAIL') and 'override:' not in ln]
    boxes = len(re.findall(r'^- \[ \]', t, re.M))
    if fails:
        return 'fail', fails[0][:160]
    if boxes:
        return 'boxes', f'{boxes} taste checks still to answer'
    return 'ready', 'all checks answered'


def frameio_facts(proj, project_id):
    st = load(proj / 'frameio.json', {}) or {}
    files = st.get('files') or []
    out = {'batch': st.get('batch'), 'cleaned': stamp(st.get('cleaned')), 'on': bool(files)}
    if files:
        last = files[-1]
        done = set(st.get('completed') or [])
        logged = list((st.get('logged') or {}).get(last.get('id'), []))
        out.update(v=last.get('v'), pushed=stamp(last.get('pushed')), src=last.get('src'),
                   link=f"https://next.frame.io/project/{project_id}/view/{last.get('id')}" if project_id and last.get('id') else None,
                   open_notes=len([c for c in logged if c not in done]))
    return out


def frame_files(proj):
    """The newest version of every starting frame, in scene order."""
    best = {}
    folder = proj / 'FRAMES'
    if folder.is_dir():
        for f in folder.glob('scene_*.png'):
            m = SCENE.fullmatch(f.name)
            if m and (int(m.group(1)) not in best or int(m.group(2) or 1) > best[int(m.group(1))][0]):
                best[int(m.group(1))] = (int(m.group(2) or 1), f)
    return [best[n][1] for n in sorted(best)]


def revision_active(req, fio, ad):
    """He sent THIS video for revisions (it is in the request's own list) after this version went up, and the new one is
    not up yet. A video of the batch he did not send, or one he approved, is never shown as "Revisions sent"."""
    return frame_review.revising(req, ad, fio.get('pushed'))


def span(seconds):
    """'40 min' / '4 h' / '2 d': how long nothing has moved."""
    s = max(0, seconds)
    return f'{s / 60:.0f} min' if s < 5400 else f'{s / 3600:.0f} h' if s < 172800 else f'{s / 86400:.0f} d'


def work_on(key, ads, anchor, now, cache=None):
    """What is true about the Claude work on this batch (cloud/claude_job.py): a live unattended job, a session that
    is active on it, a job that needs the owner, or nobody at all. One look per batch per page build."""
    cache = cache if cache is not None else {}
    if key not in cache:
        try:
            cache[key] = claude_job.work(key, list(ads), anchor, now)
        except Exception:   # the board is a view: when this cannot be read it says what it said before
            cache[key] = {'job': None, 'live': False, 'last': now, 'idle': 0.0, 'what': '', 'blocked': None, 'stalled': False, 'ended': None}
    return cache[key]


def restarts(req, w):
    """True when the watcher will start Claude on this batch again by itself (so "stalled" is only for a few minutes)."""
    c = claude_job.cfg()
    tries = int((w.get('job') or {}).get('tries') or 0) if (w.get('job') or {}).get('anchor') == frame_review.job_anchor(req) else 0
    return bool(c.get('claude_auto') and req.get('auto') and tries < int(c['claude_job_tries']))


def card_for(ad, runs, live, now, project_id, recs=None, reqs=None, jobs=None):
    """One ad -> its card (a dict), or None when it does not belong on the board (approved, old, nothing to show)."""
    proj = ROOT / 'projects' / ad
    plan = load(proj / 'plan.json', {}) or {}
    master = proj / 'MASTER.mp4'
    mm = master.stat().st_mtime if master.exists() else None
    fio = frameio_facts(proj, project_id) if proj.exists() else {'on': False}
    last = max(runs, key=lambda r: r['submitted']) if runs else None
    state = (live.get(last['run']) if last and not last.get('collected') else None) or {}
    recipe = last['recipe'] if last else None
    card = {'ad': ad, 'title': pretty(ad, plan), 'batch': (last or {}).get('batch') or fio.get('batch') or '',
            'kind': 'Real footage' if plan.get('shots') or recipe == 'raw' else 'AI ad', 'steps': [], 'frames': [],
            'action': None, 'video': master.as_uri() if mm else None, 'test': bool(TEST_AD.match(ad)), 'src': fio.get('src')}
    base = re.sub(r'-h\d+$', '', ad)
    if not card['batch'] and base != ad:   # a hook with no record of its own sits with its batch
        card['batch'] = (load(ROOT / 'projects' / base / 'frameio.json', {}) or {}).get('batch') or ''
    card['when'] = max([t for t in (mm, fio.get('pushed'), fio.get('cleaned'), (last or {}).get('collected_at'), (last or {}).get('submitted')) if t] or [0])

    def put(tab, status, detail, tone='idle', action=None):
        card.update(tab=tab, status=status, detail=detail, tone=tone, action=action or card['action'])
        return card

    # 0. clip / hook options waiting for his pick (tools/option_picker.py); never Frame.io
    opts = frame_review.options_of(proj) if proj.exists() else None
    if opts and now - float(opts.get('made_at') or 0) <= RECENT_S:
        picked = frame_review.picks_of(proj)
        names = ', '.join(x['name'] for x in opts['slots'])
        count = sum(len(x['options']) for x in opts['slots'])
        if not picked:
            card.update(kind='Clip picks', when=float(opts.get('made_at') or now), picks=opts['slots'])
            return put('frames', 'Waiting for you', f"{count} options for: {names}. Pick one for each.", 'you', ('Pick clips', (proj / 'OPTIONS.html').as_uri()))
        if not picked.get('handled_at') and not (master.exists() and mm > picked['sent_at']):
            card.update(kind='Clip picks', when=picked['sent_at'])
            return put('progress', 'Pick sent', f"You picked {ago(picked['sent_at'], now)}. Claude puts it in the ad next.", 'wait')
    # 1. a run is open in the cloud
    if last and not last.get('collected'):
        card['when'] = last['submitted']   # "sent 7 min ago", not the age of the previous version's video
        done = state.get('steps') or []
        for i, pair in enumerate(state.get('plan') or []):
            row = done[i] if i < len(done) else None
            cur = state.get('current') if i == len(done) else None
            card['steps'].append({'label': step_label(pair[1]), 'state': ('skipped' if row and row.get('skipped') else 'failed' if row and (row.get('failed') or row.get('error'))
                                                                       else 'done' if row else 'now' if cur else 'todo'),
                                  'seconds': (row or {}).get('seconds') or (now - cur['since'] if cur else None)})
        s = state.get('state') or 'queued'
        lost = ' The Mac cannot reach the cloud right now; the run keeps going on its own.' if state.get('unreachable') else ''
        if s in TERMINAL:
            word = {'done': 'Finished in the cloud', 'blocked': 'Stopped by the shot check', 'failed': 'Stopped with an error', 'crashed': 'Stopped with an error'}[s]
            if s != 'done':
                return put('progress', 'Collecting', f'{word}. The report is being brought back to the Mac.', 'wait')
            return put('progress', 'Collecting', f'{word}. Downloading and running the final checks on the Mac.', 'live')
        cur = state.get('current')
        if cur:
            return put('progress', 'Running', lost.strip() if card['steps'] else f"{step_label(cur['stages'])}, {max(0, now - cur['since']) / 60:.0f} min so far.{lost}", 'live')
        if not state:
            return put('progress', 'In the cloud', f"Sent to the cloud {ago(last['submitted'], now)}.", 'live')
        note = str(state.get('note') or 'Waiting for a cloud worker').rstrip('.')
        return put('progress', 'Queued', note[:1].upper() + note[1:] + '.' + lost, 'live')

    newest_run = last and (last.get('collected_at') or last['submitted']) >= max(fio.get('pushed') or 0, fio.get('cleaned') or 0)
    # 2. approved or launched: not on the board
    if plan.get('locked'):
        return None
    if fio.get('cleaned') and not fio.get('on') and not (newest_run and last.get('collected_at', 0) > fio['cleaned'] + 60):
        return None
    # 3. the newest thing that happened is a cloud run that needs a decision
    if newest_run and last.get('final_state') in ('failed', 'crashed', 'blocked'):
        if now - card['when'] > RECENT_S:
            return None
        why = {'blocked': 'The shot check stopped it before rendering: a planned clip does not fit its line.',
               'failed': 'A step failed in the cloud.', 'crashed': 'A cloud worker stopped unexpectedly.'}[last['final_state']]
        return put('progress', 'Claude to fix', f'{why} {MINE}', 'wait')
    page = proj / 'REVIEW.html'
    if newest_run and last.get('final_state') == 'done' and recipe in FRAME_REVIEW:
        card['frames'] = frame_files(proj)
        sent = frame_review.current(proj, card['frames'])
        if sent:
            return decided(card, sent, now, put)
        card['auto'] = True   # approving starts the clip run by itself
        return put('frames', 'Waiting for you', f"{len(card['frames'])} starting frames, made {ago(card['when'], now)}. Nothing is animated until you approve them.",
                   'you', ('Review frames', page.as_uri()) if page.exists() else None)
    if newest_run and last.get('final_state') == 'done' and recipe == 'inserts':
        return put('progress', 'Inserts ready', 'AI b-roll inserts are made; they still have to be placed in the edit.', 'idle')
    # 4. an AI ad made on the Mac that stopped at its starting frames (frames exist, no clip and no video yet)
    if not mm and page.exists() and not any((proj / 'CLIPS').glob('clip_*.mp4')):
        frames = frame_files(proj)
        made = max([f.stat().st_mtime for f in frames] + [0])
        if frames and now - made <= RECENT_S:
            card['frames'], card['when'] = frames, made
            sent = frame_review.current(proj, frames)
            if sent:
                return decided(card, sent, now, put)
            return put('frames', 'Waiting for you', f'{len(frames)} starting frames, made {ago(made, now)}. Nothing is animated until you approve them.',
                       'you', ('Review frames', page.as_uri()))
    # 4b. the same kind of ad after his OK: clips exist, no finished video yet (nothing else would show it)
    if not mm and not fio.get('on') and page.exists():
        sent = frame_review.read(proj)
        if sent and sent.get('verdict') == 'approved' and now - float(sent.get('sent_at') or 0) <= PREP_S:
            card['when'] = sent['sent_at']
            return put('progress', 'Building', f"You approved the starting frames {ago(sent['sent_at'], now)}. The clips and the edit are being made.", 'wait')
    # 5. on Frame.io
    stale = bool(fio.get('on') and mm and fio.get('pushed') and mm > fio['pushed'] + 120)
    if fio.get('on'):   # "Revisions done": the videos he sent are Claude's work now. Only those: the
        key = deliver.batch_of(proj)   # request's own list, and never a video he approved
        req = (reqs if reqs is not None else frame_review.revision_requests()).get(key) or {}
        if revision_active(req, fio, ad) and not deliver.approved_now(proj):
            card['dbatch'], card['revising'] = key, True
            n = (req.get('notes') or {}).get(ad)
            notes = '' if n is None else f"{n} note{'s' if n != 1 else ''} on this video. " if n else 'No notes on this one; batch-wide changes still apply. '
            step = {'pulling': 'Reading your Frame.io notes now.', 'waiting': 'Claude starts on them next.', 'working': 'Claude is applying them.'}[req['state']]
            late = ad in (req.get('late') or {})   # sent while a round of work on this batch was already running
            if late and req['state'] != 'pulling':
                step = 'Claude starts on this video when the round it is on is finished.'
            head = f"You pressed Revisions done {ago(frame_review.pressed_for(req, ad), now)}. {notes}"
            # only say "Claude is on it" when one is (two batches sat 4 h under that line with nobody working)
            w = work_on(key, req.get('ads') or [ad], max([float(req.get(k) or 0) for k in ('pressed_at', 'pulled_at', 'restarted_at', 'working_at')]
                                                         + [float(t or 0) for t in (req.get('ad_pressed') or {}).values()]), now, jobs)
            link = ('Open in Frame.io', fio['link'])
            if w['blocked']:
                card['work'] = 'blocked'
                return put('progress', 'Needs you', f"{head}Claude stopped and needs you: {w['blocked']}", 'you', link)
            if w['live']:
                card['work'] = 'live'
                began = (w['job'] or {}).get('started_at') or (w['job'] or {}).get('asked_at')
                if late:
                    return put('progress', 'Revisions sent', f"{head}Claude is finishing the videos of this batch it already has, then starts on this one by itself.", 'wait', link)
                return put('progress', 'Revisions sent', f"{head}Claude is applying them now (started {ago(began, now)}, no session needed).", 'live', link)
            if w['stalled']:
                again = restarts(req, w)
                card['work'] = 'restarting' if again else 'stalled'
                why = f" The last run stopped early ({w['job'].get('ended_why')})." if w.get('ended') and (w['job'] or {}).get('ended_why') else ''
                tail = ' Claude is started on it again within 10 minutes.' if again else ''
                return put('progress', 'Stalled', f"{head}Stalled — no Claude working on it (nothing has moved for {span(w['idle'])}).{why}{tail}", 'bad', link)
            return put('progress', 'Revisions sent', f"{head}{step}", 'wait', link)
    if fio.get('on') and not stale:
        # his final OK (board "Approve") sends the whole batch to Google Drive (cloud/deliver.py)
        key = card['dbatch'] = deliver.batch_of(proj)
        rec = (recs if recs is not None else deliver.records()).get(key) or {}
        approved = deliver.approved_now(proj)
        if rec.get('state') == 'delivered':
            return None   # it is under Sent to Drive now
        if rec.get('state') in ('queued', 'uploading'):
            return put('progress', 'Uploading to Drive', 'You approved it. Claude is putting the batch on Google Drive; the link shows under Sent to Drive.', 'live')
        if rec.get('state') == 'failed' and approved:
            err = str(rec.get('error') or '')
            if 'new Frame.io note' not in err:
                card['retry'] = True
            elif err.startswith(f'{ad} got'):   # read the late note; if it changes nothing, approve this version again
                card['can_approve'], card['approve_label'] = True, 'Approve again'
            return put('progress', 'Drive upload stopped', str(rec.get('error') or 'The upload stopped.'), 'bad', ('Open in Frame.io', fio['link']))
        if now - (fio.get('pushed') or now) > RECENT_S and not fio.get('open_notes') and not approved:
            return None
        n = fio.get('open_notes')
        if not approved:   # the row's own "Revisions done for this video"; an approved video never has it
            card['can_revise'] = True
            if now - float((req.get('empty') or {}).get(ad) or 0) < 3600:
                card['rev_said'] = 'No notes were found on Frame.io for this video.'
        if n and not approved:   # his notes are on Frame.io; the revision is the work in progress
            return put('progress', 'Revision to do', f"{n} note{'s' if n != 1 else ''} on v{fio.get('v')} on Frame.io, not applied yet.", 'wait', ('Open in Frame.io', fio['link']))
        card['note'] = f"Version {fio.get('v')} · uploaded {ago(fio.get('pushed'), now)}"
        if approved:
            card['approved'] = True
            return put('review', 'Approved', 'Goes to Google Drive once every video in this batch is approved.', 'live', ('Open in Frame.io', fio['link']))
        card['can_approve'] = True
        return put('review', 'Ready to review', '', 'you', ('Open in Frame.io', fio['link']))
    # 6. finished, not on Frame.io (or a newer render than the one that is there)
    if not mm or (not last and not fio.get('on')) or now - card['when'] > PREP_S:
        return None
    pf, text = preflight_facts(proj, mm)
    head = f"Re-rendered after v{fio.get('v')} went to Frame.io. " if stale else ''
    if pf == 'fail' or (last and last.get('mac_gate') == 'FAIL' and pf in ('none', 'old')):
        return put('progress', 'Claude to fix', f'{head}A final check on the finished video failed ({plain_check(text)}). {MINE}', 'wait')
    if pf == 'ready':
        return put('prep', 'Uploading next', f'{head}All checks pass. It goes to Frame.io by itself within 10 minutes. Nothing for you to do.', 'idle')
    return put('prep', 'Final checks', f'{head}Claude is running the last checks; then it goes to Frame.io by itself. Nothing for you to do.', 'idle')


def honest_fix(card, now, jobs=None, reqs=None):
    """A row that says "Claude fixes this" / "Claude is running the last checks": true only while a Claude is on it.
    Status and lane stay; the last sentence says what is really happening. While the ad's batch is in somebody's hands
    (its revision is open, or a cloud run of the batch is open) the row is left as it is: the batch header says who."""
    key = claude_job.fix_key(card.get('batch') or card['ad'])
    held = claude_job.batch_busy(card.get('batch'), reqs)
    w = work_on(f"fix:{card['ad']}", [card['ad']], card.get('when') or 0, now, jobs)
    job = claude_job.record(key) or {}
    if claude_job.live(key) and card['ad'] in (job.get('ads') or []):
        card['work'] = 'live'
        card['tone'] = 'live'
        card['detail'] = card['detail'].replace(MINE, '').strip() + f" Claude is on it now (started {ago(job.get('started_at') or job.get('asked_at'), now)}, no session needed)."
    elif job.get('state') == 'blocked' and card['ad'] in (job.get('ads') or []) and float(job.get('blocked_at') or 0) >= float(card.get('when') or 0):
        card['work'] = 'blocked'
        card['status'], card['tone'] = 'Needs you', 'you'
        card['detail'] = f"Claude stopped and needs you: {job.get('blocked')}"
    elif w['stalled'] and not held:
        c = claude_job.cfg()
        again = bool(c.get('claude_auto') and c.get('claude_auto_from') is not None and float(card.get('when') or 0) >= float(c['claude_auto_from']))
        card['work'] = 'restarting' if again else 'stalled'
        card['detail'] = (card['detail'].replace(MINE, '').replace('Claude is running the last checks; then it goes to Frame.io by itself. Nothing for you to do.', 'The last checks are not answered yet.').strip()
                          + f" No Claude is working on it right now (nothing has moved for {span(w['idle'])})."
                          + (' Claude is started on it within 10 minutes.' if again else ''))
    return card


def sent_cards(recs, now, off, budget=(0,)):
    """One row per batch that went to Drive. Not ticked yet: always shown. Ticked: folded into the closed "In the sheet"
    dropdown (once it is in the sheet he does not need to track it) for SHEET_S, then off the page."""
    out = []
    for key, r in sorted(recs.items()):
        if r.get('state') != 'delivered' or key in off['batches'] or TEST_AD.match(str((r.get('ads') or [''])[0])):
            continue
        if r.get('in_sheet') and now - float(r.get('in_sheet_at') or 0) > SHEET_S:
            continue
        ads = list(r.get('ads') or [])
        n = len(r.get('files') or ads)
        when = float(r.get('delivered_at') or now)
        on = bool(r.get('in_sheet'))
        detail = '' if r.get('frameio_cleaned', True) else 'It is still on Frame.io too; Claude removes it.'
        out.append({'ad': f'sent:{key}', 'title': key, 'dbatch': key, 'batch': 'In the sheet' if on else 'Not in the sheet yet',
                    'kind': f"{n} video{'s' if n != 1 else ''}", 'steps': [], 'frames': [], 'frame_count': 0, 'frame_thumbs': [],
                    'action': ('Open in Drive', r.get('url')), 'video': None, 'test': False, 'when': when, 'ago': f'sent {ago(when, now)}',
                    'tab': 'sent', 'status': 'In the sheet' if on else 'Not in the sheet yet', 'detail': detail,
                    'tone': 'idle' if on else 'you', 'in_sheet': on, 'url': r.get('url'),
                    'thumb': thumb(ads[0], budget) if ads else None})
    return out


def plain_check(text):
    """The failed final check in a few plain words (the full line stays in the project's PREFLIGHT.md)."""
    t = str(text).upper()
    for key, word in (('CAPTION', 'caption timing'), ('LOUD', 'audio level'), ('AUDIO', 'audio'), ('SAFE', 'text too close to the edge'),
                      ('BANNED', 'a banned clip'), ('LENGTH', 'video length'), ('OFFER', 'offer wording'), ('PHRASE', 'offer wording')):
        if key in t:
            return word
    return 'see PREFLIGHT.md'


def decided(card, sent, now, put):
    """He already answered on these frames (the board button or the review page): it is work in progress again."""
    when, n, redo = sent.get('sent_at') or now, len(card['frames']), len(sent.get('redo') or [])
    card['when'], card['frames'] = when, []
    auto = sent.get('follow_up') or {}
    if auto and auto.get('exit') not in (None, 0):
        return put('progress', 'Claude to fix', f"You answered on the frames {ago(when, now)}, but the next cloud run did not start. {MINE}", 'wait')
    if sent.get('verdict') == 'approved':
        tail = 'The clip run is starting in the cloud.' if auto else 'Clips are next.'
        return put('progress', 'Frames approved', f"You approved the {n} starting frame{'s' if n != 1 else ''} {ago(when, now)}. {tail}", 'live' if auto else 'wait')
    what = f"{redo} of {n} frames to redo" if redo else 'Notes on the frames'
    return put('progress', 'Frame notes sent', f"{what}, sent {ago(when, now)}. The new frames come back to Frames to approve.", 'live' if auto else 'wait')


def run_quiet(cmd, seconds=20):
    try:
        subprocess.run(cmd, capture_output=True, timeout=seconds)
    except Exception:
        pass


def thumb(ad, budget, alt=None):
    """A small poster frame for the row, made once per render. Returns a path relative to the page, or None."""
    proj = ROOT / 'projects' / ad
    src = proj / 'MASTER.mp4'
    if not src.exists() and alt and (proj / alt).is_file() and str(alt).lower().endswith(('.mp4', '.mov')):
        src = proj / alt
    if not src.exists():
        return None
    out = OUT / 'thumbs' / f'{ad}.jpg'
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return f'thumbs/{ad}.jpg'
    if budget[0] <= 0:
        return f'thumbs/{ad}.jpg' if out.exists() else None
    budget[0] -= 1
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = next((p for p in (str(pathlib.Path.home() / '.local/bin/ffmpeg'), '/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg')
               if pathlib.Path(p).exists()), 'ffmpeg')
    # one small frame, not a video job: called directly, with a hard time limit
    run_quiet([ff, '-loglevel', 'error', '-y', '-ss', '1.5', '-i', str(src), '-frames:v', '1', '-vf', 'scale=270:-2', '-q:v', '5', str(out)])
    return f'thumbs/{ad}.jpg' if out.exists() and out.stat().st_size > 300 else None


def frame_thumbs(ad, frames, budget, limit=8):
    """Small copies of the starting frames for the 'Frames to approve' tab (made once per frame with macOS `sips`)."""
    out = []
    for f in frames[:limit]:
        small = OUT / 'thumbs' / f'{ad}__{f.stem}.jpg'
        if not (small.exists() and small.stat().st_mtime >= f.stat().st_mtime) and budget[0] > 0:
            budget[0] -= 1
            small.parent.mkdir(parents=True, exist_ok=True)
            run_quiet(['/usr/bin/sips', '-Z', '420', '-s', 'format', 'jpeg', '-s', 'formatOptions', '70', str(f), '--out', str(small)])
        if small.exists() and small.stat().st_size > 300:
            out.append(f'thumbs/{small.name}')
    return out


def fresh_review_page(ad, frames, budget):
    """Rebuild REVIEW.html when a frame is newer than the page, so the picker never shows an old frame or an old note."""
    page = ROOT / 'projects' / ad / 'REVIEW.html'
    tool = ROOT / 'tools' / 'review_page.py'
    made = max([f.stat().st_mtime for f in frames if f.exists()] + [0])
    stale = page.exists() and (page.stat().st_mtime < made or 'function send()' not in page.read_text(errors='ignore')[-6000:])
    if stale and tool.exists() and budget[0] > 0:
        budget[0] -= 1
        py = ROOT / '.venv' / 'bin' / 'python'
        run_quiet([str(py) if py.exists() else 'python3', '-I', str(tool), str(page.parent), '--no-open'])


def usage_page(scan=0.0):
    """Rebuild the usage page (cloud/usage.py) and return what the board's small button shows. It is a view next to
    a view: it never stops the board, and it only runs when both look at the same repo (tests move this one)."""
    try:
        import usage
        if (usage.ROOT, usage.STATE, usage.OUT) != (ROOT, STATE, OUT):
            return None
        code = (C / 'usage.py').stat().st_mtime
        if getattr(usage, '_code', code) != code:   # a watcher that has been running since before an edit: use the page code on disk
            import importlib
            usage = importlib.reload(usage)
        usage._code = code
        usage.write(scan=scan, max_age=300)
        return usage.pill()
    except Exception:
        return None


def gather(rows=None, now=None, thumbs=True, thumb_budget=8, usage_scan=0.0):
    now = now or time.time()
    runs = load(STATE / 'runs.json', {}) or {}
    cache = OUT / 'live.json'
    if rows is None:   # no cloud call this time: show the step detail that was read last
        saved = load(cache, {}) or {}
        live, seen = saved.get('runs', {}), saved.get('at')
    else:
        live, seen = {r['run']: st for r, st in rows}, now
        try:
            OUT.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({'at': now, 'runs': live}, default=str))
        except OSError:
            pass
    by_ad = {}
    for r in runs.values():
        by_ad.setdefault(r['ad'], []).append(r)
    ads = set(by_ad)
    projects = ROOT / 'projects'
    if projects.is_dir():
        for name in ('frameio.json', 'REVIEW.html', 'OPTIONS.json'):
            ads |= {f.parent.name for f in projects.glob(f'*/{name}')}
    project_id = (load(ROOT / 'frameio/config.json', {}) or {}).get('project_id')
    off = hidden()
    recs, reqs = deliver.records(), frame_review.revision_requests()
    cards, budget, jobs = [], [thumb_budget], {}
    for ad in sorted(ads):
        try:
            card = card_for(ad, by_ad.get(ad, []), live, now, project_id, recs, reqs, jobs)
        except Exception as e:   # one odd project must not blank the board
            card = {'ad': ad, 'title': ad, 'batch': '', 'kind': '', 'steps': [], 'frames': [], 'action': None, 'video': None, 'test': bool(TEST_AD.match(ad)),
                    'when': now, 'tab': 'progress', 'status': 'Board error', 'detail': f'This ad could not be read ({type(e).__name__}).', 'tone': 'bad', 'src': None}
        if not card or (card['test'] and card['status'] not in ('Running', 'Queued', 'Collecting', 'In the cloud')):
            continue
        if ad in off['ads'] or (card['batch'] and card['batch'] in off['batches']):
            continue
        if card['status'] in claude_job.FIX_STATUS and not card['test']:
            honest_fix(card, now, jobs, reqs)
        if card['tab'] == 'progress' and card['tone'] == 'live' and not card.get('work') and seen and now - seen > 180:
            card['detail'] = (card['detail'] + f' Step detail last read {ago(seen, now)}.').strip()
        card['ago'] = ago(card['when'], now)
        if card['tab'] in ('progress', 'prep'):   # he watches on Frame.io only; while it is being made the Mac file is the old version
            card['video'] = None
        made = budget if thumbs else [0]   # thumbs=False (a button press): no new pictures, but keep the ones already made
        card['thumb'] = thumb(ad, made, card.get('src'))
        card['frame_thumbs'] = frame_thumbs(ad, card['frames'], made) if card['frames'] else []
        card['frame_count'] = len(card['frames'])
        if card['tab'] == 'frames':
            fresh_review_page(ad, card['frames'], budget)
        cards.append(card)
    cards += sent_cards(recs, now, off, budget if thumbs else [0])
    ledger = load(STATE / f"ledger-{datetime.date.fromtimestamp(now).strftime('%Y-%m')}.json", {}) or {}
    beat = STATE / 'watch-heartbeat'
    return {'now': now, 'cards': cards, 'modal': ledger.get('estimated_total_usd'), 'cap': ledger.get('cap_usd'), 'kie': usage_page(usage_scan),
            'stopped': (STATE / 'GLOBAL_STOP.json').exists(), 'watch': beat.stat().st_mtime if beat.exists() else None,
            'hidden': len(off['ads']) + len(off['batches']), 'revisions': reqs}


# Tab icon: white play button on a red-orange rounded square (inline SVG, no file needed).
FAVICON = ('<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,'
           '%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 64 64%27%3E'
           '%3Cdefs%3E%3ClinearGradient id=%27g%27 x1=%270%27 y1=%270%27 x2=%271%27 y2=%271%27%3E'
           '%3Cstop offset=%270%27 stop-color=%27%23ff4d6d%27/%3E%3Cstop offset=%271%27 stop-color=%27%23ff8a00%27/%3E'
           '%3C/linearGradient%3E%3C/defs%3E'
           '%3Crect width=%2764%27 height=%2764%27 rx=%2716%27 fill=%27url(%23g)%27/%3E'
           '%3Cpath d=%27M25 18.5v27a2 2 0 0 0 3 1.7l21.5-13.5a2 2 0 0 0 0-3.4L28 16.8a2 2 0 0 0-3 1.7z%27 fill=%27%23fff%27/%3E'
           '%3C/svg%3E">')

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Instrument+Serif&display=swap">')

CSS = '''
:root{--paper:#f5f4ef;--surface:#fff;--ink:#16150f;--soft:#4a4840;--mute:#8a867b;--line:#e3e0d6;--hair:#eeebe3;
--live:#1c7c54;--bad:#b83227;--wait:#a86a12;--you:#16150f;--tint:#efede6;
--sans:"Instrument Sans",-apple-system,"SF Pro Text",system-ui,sans-serif;--serif:"Instrument Serif","New York",ui-serif,Georgia,serif}
@media (prefers-color-scheme:dark){:root{--paper:#0f0f0d;--surface:#181816;--ink:#f1eee6;--soft:#c2beb3;--mute:#807c72;--line:#2a2925;--hair:#21201d;
--live:#4fbf8c;--bad:#ee6a5c;--wait:#dba54a;--you:#f1eee6;--tint:#1f1e1b}}
*{box-sizing:border-box}html{background:var(--paper)}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 var(--sans);-webkit-font-smoothing:antialiased}
.wrap{max-width:1040px;margin:0 auto;padding:44px 32px 72px}
.top{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;flex-wrap:wrap}
.brand{font:400 44px/1 var(--serif);letter-spacing:-.01em;margin:0}
.meta{color:var(--mute);font-size:13px;text-align:right}.meta b{font-weight:500;color:var(--soft)}.meta .late{color:var(--bad)}
.right{display:grid;justify-items:end;gap:10px}
.usage{display:inline-flex;align-items:center;gap:8px;text-decoration:none;color:var(--soft);font-size:12.5px;font-weight:600;border:1px solid var(--line);border-radius:999px;padding:5px 12px;background:var(--surface)}
.usage:hover{border-color:var(--ink);color:var(--ink)}.usage b{font-weight:600;color:var(--ink);font-variant-numeric:tabular-nums}.usage.low{border-color:var(--wait)}.usage.low b{color:var(--wait)}
.usage:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.stop{margin-top:22px;padding:14px 18px;border:1px solid var(--bad);border-radius:10px;color:var(--bad);font-weight:500}
.tabs{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:34px}
.tab{appearance:none;font:inherit;color:inherit;text-align:left;cursor:pointer;background:transparent;border:1px solid var(--line);border-radius:14px;
padding:16px 18px 16px;display:grid;grid-template-rows:auto auto auto;align-content:start;gap:2px;transition:background .15s,border-color .15s,color .15s}
.tab:hover{border-color:var(--mute)}
.tab .n{font:500 34px/1 var(--sans);letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.tab .l{font-weight:600;font-size:15px;margin-top:12px;white-space:nowrap}
.tab .h{color:var(--mute);font-size:12.5px;line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tab[aria-selected=true]{background:var(--ink);border-color:var(--ink);color:var(--paper)}
.tab[aria-selected=true] .h{color:color-mix(in srgb,var(--paper) 62%,transparent)}
.tab.zero:not([aria-selected=true]) .n{color:var(--mute)}
.tab:focus-visible,.btn:focus-visible,.x:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.panel{margin-top:30px}.panel[hidden]{display:none}
.panel.on{animation:rise .22s ease-out}@keyframes rise{from{opacity:0;transform:translateY(4px)}}
@media (prefers-reduced-motion:reduce){.panel.on{animation:none}.dot{animation:none!important}}
.empty{border:1px dashed var(--line);border-radius:14px;padding:46px 20px;text-align:center;color:var(--mute)}
.group{margin-top:30px}.group:first-child{margin-top:0}
.group h2{font:600 12px/1 var(--sans);letter-spacing:.09em;text-transform:uppercase;color:var(--mute);margin:0 0 10px;display:flex;gap:10px;align-items:baseline}
.group h2 em{font-style:normal;font-weight:500;letter-spacing:0}
.list{background:var(--surface);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.row{display:grid;grid-template-columns:54px 1fr auto;gap:18px;align-items:center;padding:14px 18px;border-top:1px solid var(--hair);position:relative}
.row:first-child{border-top:0}
.pic{width:54px;height:96px;border-radius:7px;background:var(--tint);overflow:hidden;display:grid;place-items:center;color:var(--mute)}
.pic img{width:100%;height:100%;object-fit:cover;display:block}
.row h3{margin:0;font:600 16px/1.3 var(--sans);overflow-wrap:anywhere}
.sub{color:var(--mute);font-size:12.5px;margin-top:1px}
.detail{margin:7px 0 0;color:var(--soft);font-size:14px;max-width:62ch}
.pill{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;font-weight:600;color:var(--tone);white-space:nowrap}
.dot{width:7px;height:7px;border-radius:50%;background:var(--tone);flex:none}
.live{--tone:var(--live)}.bad{--tone:var(--bad)}.wait{--tone:var(--wait)}.you{--tone:var(--you)}.idle{--tone:var(--mute)}
.live .dot{animation:pulse 1.8s ease-in-out infinite}@keyframes pulse{50%{opacity:.25}}
.side{display:grid;justify-items:end;align-content:center;gap:9px;min-width:150px}.acts{display:flex;align-items:center;gap:14px;min-height:20px}
.btn{display:inline-block;text-decoration:none;font-weight:600;font-size:13.5px;padding:8px 14px;border-radius:9px;border:1px solid var(--ink);background:var(--ink);color:var(--paper);white-space:nowrap}
.btn:hover{opacity:.86}.btn.ghost,.btn.line{background:transparent;color:var(--ink);border-color:var(--line)}.btn.line{border-color:var(--soft)}
.btn.ghost:hover{border-color:var(--ink);opacity:1}.btn.line:hover{background:var(--ink);color:var(--paper);border-color:var(--ink);opacity:1}
.steps{list-style:none;display:flex;flex-wrap:wrap;gap:6px 0;margin:10px 0 0;padding:0;font-size:12.5px;color:var(--mute)}
.steps li{display:flex;align-items:center}.steps li+li::before{content:"";width:18px;height:1px;background:var(--line);margin:0 8px}
.steps .done{color:var(--soft)}.steps .done span::before{content:"✓ ";color:var(--live)}
.steps .now{color:var(--live);font-weight:600}.steps .failed{color:var(--bad)}
.x{appearance:none;border:0;background:none;font:inherit;font-size:12px;color:var(--mute);cursor:pointer;padding:0;opacity:0;transition:opacity .12s}
.row:hover .x,.x:focus-visible{opacity:1}.x:hover{color:var(--ink);text-decoration:underline}
button.btn{appearance:none;font-family:inherit;cursor:pointer}.btn[disabled]{opacity:.5;cursor:default}
.said{font-size:13px;color:var(--soft)}.said.bad{color:var(--bad)}.foot .x{margin-left:auto}
.row.frames{display:block;padding:18px}
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}
.foot{display:flex;align-items:center;gap:16px;margin-top:14px}
.strip{display:flex;gap:8px;margin-top:14px;overflow-x:auto;padding-bottom:2px}
.strip a{flex:none;height:200px;aspect-ratio:9/16;border-radius:8px;overflow:hidden;background:var(--tint);display:block}
.strip img{width:100%;height:100%;object-fit:cover;display:block}
.strip .more{display:grid;place-items:center;color:var(--mute);font-size:13px;text-decoration:none;border:1px dashed var(--line);background:none}
.group h2 .btn{text-transform:none;letter-spacing:0;font-size:12.5px;padding:6px 12px}.group h2 .gname{display:flex;gap:10px;align-items:baseline}.group h2 .said:first-of-type{margin-left:auto}
.fold summary h2 .gname{flex:1}
.group h2 .btn.line{background:transparent;color:var(--ink);border-color:var(--soft)}.group h2 .btn.line:hover{background:var(--ink);color:var(--paper)}.group h2 .said{text-transform:none;letter-spacing:0;font-weight:400}
.side .said{max-width:30ch;text-align:right}
.row.done .pic,.row.done h3,.row.done .sub,.row.done .detail{opacity:.5}
.note{margin:0 0 16px;color:var(--soft);font-size:14px}
.fold summary{list-style:none;cursor:pointer}.fold summary::-webkit-details-marker{display:none}
.fold summary h2{padding:10px 14px;border:1px dashed var(--line);border-radius:12px;margin:0}.fold summary:hover h2{border-color:var(--mute);color:var(--soft)}
.fold summary h2::before{content:"▸";font-size:13px;color:var(--soft);transition:transform .15s}.fold[open] summary h2::before{transform:rotate(90deg)}
.fold summary h2::after{content:"Show done";font-weight:500;letter-spacing:0;text-transform:none;color:var(--soft)}
.fold[open] summary h2::after{content:"Hide"}.fold[open] summary h2{margin-bottom:10px}.fold summary:focus-visible{outline:2px solid var(--ink);outline-offset:2px;border-radius:6px}
.tick{display:inline-flex;align-items:center;gap:8px;font-size:13.5px;font-weight:600;cursor:pointer;user-select:none;white-space:nowrap}
.tick input{width:18px;height:18px;margin:0;accent-color:var(--live);cursor:pointer}
.lnk{appearance:none;border:0;background:none;font:inherit;font-size:12.5px;color:var(--mute);cursor:pointer;padding:0;text-decoration:underline}.lnk:hover{color:var(--ink)}
.lnk.rev{color:var(--soft);text-underline-offset:2px;white-space:nowrap}.lnk[disabled]{opacity:.5;cursor:default}.lnk:focus-visible{outline:2px solid var(--ink);outline-offset:2px;border-radius:3px}
footer{margin-top:44px;color:var(--mute);font-size:12.5px;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}
footer button{appearance:none;border:0;background:none;font:inherit;color:var(--soft);cursor:pointer;padding:0;text-decoration:underline}
@media (max-width:980px){.tabs{grid-template-columns:repeat(3,1fr)}}
@media (max-width:760px){.wrap{padding:28px 16px 56px}.brand{font-size:36px}.meta{text-align:left}.right{justify-items:start}.tabs{grid-template-columns:1fr 1fr}.side .said{text-align:left}.tab .h{white-space:normal}
.row{grid-template-columns:54px 1fr;gap:10px 14px}.side{grid-column:2;display:flex;align-items:center;justify-content:space-between;min-width:0}
.x{opacity:1;display:none}.foot .x{display:inline}.strip a{height:160px}
.group h2{flex-wrap:wrap;row-gap:8px}.group h2 .gname{flex-basis:100%}.group h2 .said:first-of-type{margin-left:0}.group h2 .said:empty{display:none}
.tabs{grid-template-columns:repeat(3,1fr);gap:8px}.tab{padding:12px 12px}.tab .n{font-size:26px}.tab .l{margin-top:8px;font-size:13.5px;white-space:normal}.tab .h{display:none}
.side{flex-wrap:wrap;gap:10px}.tick{width:100%;min-height:44px}.side .said{width:100%}.side .lnk.rev{padding:10px 0}}
'''

JS = '''
const tabs=[...document.querySelectorAll('.tab')],panels=[...document.querySelectorAll('.panel')],KEY='adboard-hidden-rows';
let off=[];try{off=JSON.parse(localStorage.getItem(KEY)||'[]')}catch(e){}
function count(){
  document.querySelectorAll('.row').forEach(r=>{r.hidden=off.includes(r.dataset.ad)});
  document.querySelectorAll('.group').forEach(g=>{const n=g.querySelectorAll('.row:not([hidden])').length;g.hidden=!n;const e=g.querySelector('h2 em');if(e)e.textContent=n});
  panels.forEach(p=>{const n=p.querySelectorAll('.row:not([hidden]):not(.done)').length,all=p.querySelectorAll('.row:not([hidden])').length,t=tabs.find(t=>t.dataset.tab===p.dataset.tab);
    t.querySelector('.n').textContent=n;t.classList.toggle('zero',!n);p.querySelector('.empty').hidden=!!all});
  const here=off.filter(a=>document.querySelector('.row[data-ad="'+CSS.escape(a)+'"]')).length,box=document.getElementById('mine');
  box.hidden=!here;box.querySelector('span').textContent=here+(here===1?' ad':' ads')+' hidden by you';
}
function show(name,anim){
  tabs.forEach(t=>t.setAttribute('aria-selected',t.dataset.tab===name?'true':'false'));
  panels.forEach(p=>{p.hidden=p.dataset.tab!==name;p.classList.toggle('on',!!anim&&p.dataset.tab===name)});
  try{history.replaceState(null,'','#'+name)}catch(e){}
}
tabs.forEach(t=>t.addEventListener('click',()=>show(t.dataset.tab,true)));
document.addEventListener('click',e=>{const b=e.target.closest('.x');if(!b)return;off.push(b.dataset.ad);
  try{localStorage.setItem(KEY,JSON.stringify(off))}catch(e){}count()});
document.getElementById('unhide').addEventListener('click',()=>{off=[];try{localStorage.removeItem(KEY)}catch(e){}count()});
count();
const want=location.hash.slice(1),first=tabs.find(t=>t.dataset.tab===want)||tabs.find(t=>!t.classList.contains('zero'))||tabs[0];
show(first.dataset.tab,false);
// Every button that saves something talks to the helper on this Mac (cloud/frame_review.py). Saving buttons need two presses.
let busy=false;
async function post(path,body){const r=await fetch(BASE+path,{method:'POST',headers:{'Content-Type':'text/plain'},body:JSON.stringify(Object.assign({token:TOKEN},body))});
  const j=await r.json();if(!j.ok)throw new Error(j.error||'Not saved.');return j}
function why(err){return err instanceof TypeError?'Not saved: the board helper is not running. Run ctl.py dash once, or tell Claude.':err.message}
function spot(b){const box=b.closest('.row')||b.closest('.group');return box&&box.querySelector('.said')}
function armed(b){if(b.dataset.armed==='1'){b.dataset.armed='';return true}
  b.dataset.armed='1';b.textContent='Press again to confirm';busy=true;
  setTimeout(()=>{if(b.dataset.armed==='1'){b.dataset.armed='';b.textContent=b.dataset.label;busy=false}},6000);return false}
async function act(b,path,body,done){const said=spot(b);b.disabled=true;b.textContent='Saving…';if(said){said.className='said';said.textContent=''}
  try{const j=await post(path,body);b.textContent=done;if(said)said.textContent=j.message;busy=false;setTimeout(()=>location.reload(),2500)}
  catch(err){busy=false;b.disabled=false;b.textContent=b.dataset.label;if(said){said.className='said bad';said.textContent=why(err)}}}
document.addEventListener('click',e=>{const b=e.target.closest('button[data-do]');if(!b||b.disabled)return;const d=b.dataset;
  if(d.do==='undo'){busy=true;return act(b,'/approve',{ad:d.ad,undo:true},'Taken back')}
  if(d.do==='copy'){navigator.clipboard.writeText(d.url).then(()=>{b.textContent='Copied ✓';setTimeout(()=>b.textContent=d.label,1800)},()=>{prompt('Copy the link:',d.url)});return}
  if(!armed(b))return;
  if(d.do==='frames')return act(b,'/frames',{ad:d.ad,source:'board',approve_all:true},'Approved ✓');
  if(d.do==='approve')return act(b,'/approve',d.ads?{ads:d.ads.split(',')}:{ad:d.ad},'Approved ✓');
  if(d.do==='retry')return act(b,'/approve',{batch:d.batch,retry:true},'Started ✓');
  if(d.do==='revisions')return act(b,'/revisions',d.ad?{ad:d.ad}:d.restart?{batch:d.batch,restart:true}:{batch:d.batch},d.restart?'Started ✓':'Sent ✓')});
document.addEventListener('change',async e=>{const c=e.target.closest('input.sheet');if(!c)return;const said=spot(c);busy=true;c.disabled=true;
  try{const j=await post('/sheet',{batch:c.dataset.batch,on:c.checked});if(said){said.className='said';said.textContent=j.message}setTimeout(()=>location.reload(),1500)}
  catch(err){c.checked=!c.checked;c.disabled=false;busy=false;if(said){said.className='said bad';said.textContent=why(err)}}});
// quiet reload so the board stays current; the open tab is kept in the address
setInterval(()=>{if(!document.hidden&&!busy)location.reload()},REFRESH*1000);
'''


def e(x):
    return html.escape(str(x if x is not None else ''), quote=True)


def steps_html(steps):
    if not steps:
        return ''
    items = []
    for s in steps:
        mins = f" · {s['seconds'] / 60:.0f} min" if s['state'] == 'now' and s.get('seconds') and s['seconds'] >= 60 else ''
        items.append(f'<li class="{e(s["state"])}"><span>{e(s["label"])}{e(mins)}</span></li>')
    return f'<ol class="steps">{"".join(items)}</ol>'


FILM = ('<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true">'
        '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M10.5 9.5v5l4-2.5z" fill="currentColor" stroke="none"/></svg>')


def row_html(c):
    sub = ' · '.join(x for x in (c.get('kind'), c.get('note') or c.get('ago')) if x)
    pill = f'<span class="pill"><i class="dot"></i>{e(c["status"])}</span>'
    hide_btn = f'<button class="x" data-ad="{e(c["ad"])}" title="Take this ad off your board (this browser only)">Hide</button>'
    detail = f'<p class="detail">{e(c["detail"])}</p>' if c.get('detail') else ''
    text = f'<h3>{e(c["title"])}</h3><div class="sub">{e(sub)}</div>{detail}'
    if c['tab'] == 'frames' and c.get('picks') is not None:
        href = e(c['action'][1]) if c.get('action') else ''
        go = f'<a class="btn" href="{href}" target="_blank" rel="noopener">Pick clips</a>' if href else ''
        return (f'<article class="row frames {e(c["tone"])}" data-ad="{e(c["ad"])}"><div class="head"><div>{text}</div>{pill}</div>'
                f'<div class="foot">{go}{hide_btn}</div></article>')
    if c['tab'] == 'frames':
        href = e(c['action'][1]) if c.get('action') else ''
        shots = ''.join(f'<a href="{href}" target="_blank" rel="noopener"><img src="{e(t)}" alt="Starting frame {i + 1}" loading="lazy"></a>'
                        for i, t in enumerate(c.get('frame_thumbs') or []))
        extra = c.get('frame_count', 0) - len(c.get('frame_thumbs') or [])
        if shots and extra > 0:
            shots += f'<a class="more" href="{href}" target="_blank" rel="noopener">+{extra} more</a>'
        strip = f'<div class="strip">{shots}</div>' if shots else ''
        label = 'Approve and start clips' if c.get('auto') else 'Approve frames'
        ok = f'<button class="btn ok" data-do="frames" data-ad="{e(c["ad"])}" data-n="{c.get("frame_count", 0)}" data-label="{label}">{label}</button>' if c.get('frame_count') else ''
        go = f'<a class="btn line" href="{href}" target="_blank" rel="noopener">Leave notes</a>' if href else ''
        return (f'<article class="row frames {e(c["tone"])}" data-ad="{e(c["ad"])}"><div class="head"><div>{text}</div>{pill}</div>'
                f'{strip}<div class="foot">{ok}{go}<span class="said" role="status"></span>{hide_btn}</div></article>')
    if c['tab'] == 'sent':
        url = e(c.get('url') or '')
        box = (f'<label class="tick"><input type="checkbox" class="sheet" data-batch="{e(c["dbatch"])}"{" checked" if c.get("in_sheet") else ""}>'
               'In the media buyer sheet</label>')
        acts = (f'<button class="btn ghost" data-do="copy" data-url="{url}" data-label="Copy link">Copy link</button>'
                f'<a class="btn line" href="{url}" target="_blank" rel="noopener">Open in Drive <span aria-hidden="true">↗</span></a>') if url else ''
        pic = f'<img src="{e(c["thumb"])}" alt="" loading="lazy">' if c.get('thumb') else FILM
        return (f'<article class="row {e(c["tone"])}{" done" if c.get("in_sheet") else ""}" data-ad="{e(c["ad"])}"><span class="pic">{pic}</span>'
                f'<div>{text}</div><div class="side"><div class="acts">{acts}</div>{box}<span class="said" role="status"></span></div></article>')
    acts = ''
    if c.get('can_approve'):
        word = e(c.get('approve_label') or 'Approve')
        acts += f'<button class="btn" data-do="approve" data-ad="{e(c["ad"])}" data-label="{word}">{word}</button>'
    if c.get('retry'):
        acts += f'<button class="btn" data-do="retry" data-batch="{e(c.get("dbatch"))}" data-label="Try again">Try again</button>'
    if c.get('approved'):
        acts = f'<button class="lnk" data-do="undo" data-ad="{e(c["ad"])}" data-label="Take back">Take back</button>'
    if c.get('action') and c['action'][1]:
        acts += f'<a class="btn line" href="{e(c["action"][1])}" target="_blank" rel="noopener">{e(c["action"][0])} <span aria-hidden="true">↗</span></a>'
    elif c.get('video'):
        acts = f'<a class="btn ghost" href="{e(c["video"])}" target="_blank" rel="noopener">Play finished video</a>'
    rev = ''
    if c.get('can_revise'):   # quiet text link under the buttons: second to "Open in Frame.io", and only this one video
        rev = (f'<button class="lnk rev" data-do="revisions" data-ad="{e(c["ad"])}" data-label="Revisions done for this video" '
               'title="Press when you have finished leaving your notes on Frame.io for this one video: Claude starts on it. '
               'The other videos of the batch are left alone.">Revisions done for this video</button>')
    say = (f'<span class="said" role="status">{e(c.get("rev_said") or "")}</span>'
           if c.get('can_approve') or c.get('retry') or c.get('approved') or c.get('can_revise') else '')
    side = f'<div class="side">{"" if c["tab"] == "review" and not c.get("approved") else pill}<div class="acts">{hide_btn}{acts}</div>{rev}{say}</div>'
    pic = f'<img src="{e(c["thumb"])}" alt="" loading="lazy">' if c.get('thumb') else FILM
    link = f'<a class="pic" href="{e(c["video"])}" target="_blank" rel="noopener" title="Play the finished video">{pic}</a>' if c.get('video') else f'<span class="pic">{pic}</span>'
    done = ' done' if c.get('approved') else ''   # approved: stays listed, dimmed, not counted as waiting for review
    return (f'<article class="row {e(c["tone"])}{done}" data-ad="{e(c["ad"])}">{link}<div>{text}{steps_html(c.get("steps"))}</div>{side}</article>')


def revisions_btn(items, reqs, now):
    """'Revisions done' on a Frame.io batch: one press when he has finished leaving notes on all its videos. It sends the
    videos that are not approved (the helper filters); a batch with nothing left to send has no button. One video only:
    the row's own link (row_html)."""
    keys = {c.get('dbatch') for c in items if c.get('dbatch')}
    if len(keys) != 1 or not any(c.get('tab') in ('review', 'progress') for c in items):
        return ''
    key = keys.pop()
    if any(c.get('revising') for c in items):
        states = {c.get('work') for c in items if c.get('revising')}
        start = (f'<button class="btn line rev" data-do="revisions" data-restart="1" data-batch="{e(key)}" data-label="Start Claude on it" '
                 'title="Starts Claude on this batch now, with no session open">Start Claude on it</button>') if claude_job.enabled() else ''
        if 'blocked' in states:
            return f'<span class="said bad" role="status">Claude needs you · see below</span>{start}'
        if 'stalled' in states:   # nobody is on it and nothing restarts it: say so, and give him the way to start it
            return f'<span class="said bad" role="status">Stalled — no Claude working on it</span>{start}'
        if 'restarting' in states:
            return '<span class="said" role="status">Stalled — Claude is started on it again within 10 minutes</span>'
        return '<span class="said">Revisions sent · Claude is on it</span>'
    if not any(c.get('can_revise') for c in items):   # every video here is approved (or its upload is under way): nothing to send
        return ''
    req = reqs.get(key) or {}
    said = ('No notes were found on Frame.io last time.' if req.get('state') == 'no-notes' and not req.get('empty')
            and now - float(req.get('pressed_at') or 0) < 3600 else '')
    return (f'<span class="said" role="status">{e(said)}</span><button class="btn line rev" data-do="revisions" data-batch="{e(key)}" '
            'data-label="Revisions done" title="Press when you have finished leaving your notes on Frame.io for every video in this batch: '
            'Claude starts on them. Videos you approved are left alone. For one video only, use the link on its row.">Revisions done</button>')


def approve_all(items):
    """'Approve all N' on a Ready for review batch with two or more videos still to approve (approval is per batch)."""
    todo = [c for c in items if c.get('can_approve') and c.get('tab') == 'review']
    keys = {c.get('dbatch') for c in todo}
    if len(todo) < 2 or len(keys) != 1:
        return ''
    label = f'Approve all {len(todo)}'
    return (f'<span class="said" role="status"></span><button class="btn" data-do="approve" data-ads="{e(",".join(c["ad"] for c in todo))}" '
            f'data-label="{label}">{label}</button>')


def render(data, refresh=30):
    now = data['now']
    by_tab = {key: [] for key, *_ in TABS}
    for c in data['cards']:
        by_tab[c['tab']].append(c)
    order = {'live': 0, 'bad': 1, 'wait': 2, 'idle': 4}
    tabs, panels = [], []
    for key, name, hint, none in TABS:
        cards = by_tab[key]
        groups = {}
        for c in sorted(cards, key=lambda c: (order.get(c['tone'], 3), -c['when'], c['ad'])):
            groups.setdefault(c['batch'] or 'Other ads', []).append(c)
        def group_html(batch, items):
            rows = ''.join(row_html(c) for c in sorted(items, key=lambda c: (-c['when'], c['ad']) if key == 'sent' else c['ad']))
            if key == 'sent' and batch == 'In the sheet':   # done: folded away, opened only when he wants to look
                return (f'<details class="group fold"><summary><h2><span class="gname">{e(batch)} <em>{len(items)}</em></span></h2></summary>'
                        f'<div class="list">{rows}</div></details>')
            return (f'<section class="group"><h2><span class="gname">{e(batch)} <em>{len(items)}</em></span>{revisions_btn(items, data.get("revisions") or {}, now)}'
                    f'{approve_all(items)}</h2><div class="list">{rows}</div></section>')
        if key == 'sent':   # the open list first, the folded one last
            groups = dict(sorted(groups.items(), key=lambda kv: kv[0] == 'In the sheet'))
        body = ''.join(group_html(batch, items) for batch, items in groups.items())
        tabs.append(f'<button class="tab{"" if [c for c in cards if not c.get("in_sheet") and not c.get("approved")] else " zero"}" role="tab" data-tab="{key}" aria-selected="false" aria-controls="p-{key}">'
                    f'<span class="n">{len([c for c in cards if not c.get("in_sheet") and not c.get("approved")])}</span><span class="l">{e(name)}</span><span class="h">{e(hint)}</span></button>')
        note = f'<p class="note">{e(TAB_NOTES[key])}</p>' if key in TAB_NOTES and cards else ''
        panels.append(f'<section class="panel" id="p-{key}" role="tabpanel" data-tab="{key}" hidden>{note}{body}'
                      f'<div class="empty"{" hidden" if cards else ""}>{e(none)}</div></section>')
    modal, cap = float(data.get('modal') or 0), float(data.get('cap') or 0)
    late = bool(data.get('watch') and now - data['watch'] > 1500)
    watch = f"auto-collector checked {ago(data['watch'], now)}" if data.get('watch') else 'auto-collector has not run yet'
    clock = datetime.datetime.fromtimestamp(now).strftime('%-I:%M %p')
    spend = f' · cloud spend <b>${modal:.2f}</b> of ${cap:.0f} this month' if cap else ''
    meta = f'Updated <b>{e(clock)}</b>{spend}<br><span class="{"late" if late else ""}">{e(watch)}</span>'
    stop = '<div class="stop">The cloud is stopped: a paid step crashed or the monthly limit was reached. No new cloud work starts until it is lifted.</div>' if data.get('stopped') else ''
    by_claude = f"{data['hidden']} hidden from the board at your request" if data.get('hidden') else ''
    kie = data.get('kie') or {}
    left = f"<b>{kie['credits']:,.0f}</b> credits" if kie.get('credits') is not None else ''
    usage = (f'<a class="usage{" low" if kie.get("low") else ""}" href="usage.html" title="What each batch costs, revision rounds and make time'
             f'{". The kie balance is running low" if kie.get("low") else ""}">Usage{" · " + left if left else ""} <span aria-hidden="true">›</span></a>'
             if data.get('kie') is not None else '')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Ad Board</title>{FAVICON}{FONTS}<style>{CSS}</style></head><body><div class="wrap">'
            f'<header class="top"><h1 class="brand">Ad Board</h1><div class="right">{usage}<div class="meta">{meta}</div></div></header>{stop}'
            f'<nav class="tabs" role="tablist" aria-label="Stages">{"".join(tabs)}</nav>{"".join(panels)}'
            f'<footer><span>Approved batches go to Sent to Drive.{e(" " + by_claude + "." if by_claude else "")}</span>'
            f'<span id="mine" hidden><span></span> · <button id="unhide">Show them</button></span></footer>'
            f'</div><script>const REFRESH={int(refresh)},BASE={json.dumps(BASE)},TOKEN={json.dumps(frame_review.token())};{JS}</script></body></html>')


def write(rows=None, thumbs=True, thumb_budget=8, usage_scan=0.0):
    """Rebuild the page. `rows` = [(run, state)] from the controller's status call (None: no live step detail).
    `usage_scan` = seconds the usage page may spend reading new Claude transcript lines (0: none)."""
    OUT.mkdir(parents=True, exist_ok=True)
    data = gather(rows, thumbs=thumbs, thumb_budget=thumb_budget, usage_scan=usage_scan)
    tmp = OUT / 'index.html.part'
    tmp.write_text(render(data))
    tmp.replace(OUT / 'index.html')
    return OUT / 'index.html'


if __name__ == '__main__':
    print(write())
