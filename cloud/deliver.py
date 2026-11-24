"""Approved on the board -> Google Drive -> off Frame.io -> tracked until the owner has put it in the media buyer sheet.

Pressing Approve on what is on Frame.io uploads it to Google Drive and gives the owner the link, then a tracker with a
button he presses once it is in the media buyer's Google Sheet.

  board "Approve" (Ready for review row, two presses) -> cloud/frame_review.py writes projects/<ad>/APPROVED.json
  -> when EVERY ad of that Frame.io batch is approved (approval is per batch: owner rule, all hooks), this file runs:
       1. pull the last Frame.io comments; a note left after he pressed Approve stops everything
       2. Drive (the Google Drive account linked in Composio; "composio_drive_account" in config.json picks one): a folder named after the batch, each
          MASTER.mp4 as <ad>.mp4, md5 checked against the Mac file, folder shared "anyone with the link can view"
       3. delete the batch from Frame.io (tools/frameio.py clean: it pulls comments first; nothing is lost)
       4. Slack DM to the owner with the link; the board's "Sent to Drive" tab shows it with an "In the sheet" box
  Records: cloud/controller/deliveries.json (one entry per batch). Log: cloud/.scratch/deliver.log.

Run by hand: .modal-env/bin/python cloud/deliver.py "<batch>" [--dry-run]   |   --renamed "<batch>" after the rename
Not done here (on purpose): naming. The owner fills the naming sheet row himself; a session renames the Drive files to
his Ad Name afterwards. The sheet link paste is off unless config.json says
"deliver_sheet_link": true (not built yet).
"""
import fcntl
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import time

C = pathlib.Path(__file__).resolve().parent
if str(C) not in sys.path:
    sys.path.insert(0, str(C))
import names  # noqa: E402

ROOT = C.parent
STATE = C / 'controller'
RECORD = STATE / 'deliveries.json'
LOG = C / '.scratch' / 'deliver.log'
ACCOUNT = str(names.config().get('composio_drive_account') or '')   # empty: Composio's default Google Drive account
COMPOSIO = shutil.which('composio') or str(pathlib.Path.home() / '.local/bin/composio')
SLACK_POST = ROOT / 'bin' / 'slack-post'
MAC_PY = str(ROOT / '.venv' / 'bin' / 'python')


def load(path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return default


def log(line):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a') as f:
        f.write(time.strftime('[%m-%d %H:%M:%S] ') + line.rstrip() + '\n')
    print(line, flush=True)


def records():
    return load(RECORD, {}) or {}


def save_record(batch, entry):
    """Merge one batch's entry into deliveries.json under a lock (the helper and a session may both write)."""
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / 'deliveries.lock', 'w') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        d = records()
        d[batch] = {**d.get(batch, {}), **entry}
        tmp = RECORD.with_suffix('.part')
        tmp.write_text(json.dumps(d, indent=1))
        tmp.replace(RECORD)
        return d[batch]


def batch_of(proj, st=None):
    """The Frame.io batch an ad belongs to; an ad pushed on its own is a batch of one under its own name."""
    st = st if st is not None else (load(pathlib.Path(proj) / 'frameio.json', {}) or {})
    return st.get('batch') or pathlib.Path(proj).name


def members(batch, root=None):
    """Ads of this Frame.io batch that are on Frame.io now (their newest upload is what he approves)."""
    out = []
    for f in sorted(((root or ROOT) / 'projects').glob('*/frameio.json')):
        st = load(f, {}) or {}
        if st.get('files') and batch_of(f.parent, st) == batch:
            out.append(f.parent)
    return out


def approval(proj):
    return load(pathlib.Path(proj) / 'APPROVED.json')


def approved_now(proj):
    """APPROVED.json still stands: it names the file that is on Frame.io now, and no newer render exists."""
    a, st = approval(proj), load(pathlib.Path(proj) / 'frameio.json', {}) or {}
    files = st.get('files') or []
    return bool(a and files and a.get('file_id') == files[-1].get('id'))


def batch_state(batch, root=None):
    """(members, approved members) for the board and the helper."""
    ms = members(batch, root)
    return ms, [m for m in ms if approved_now(m)]


def md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def composio(slug, data, file=None, timeout=900):
    work = C / '.scratch' / 'deliver'
    work.mkdir(parents=True, exist_ok=True)
    req = work / f'{slug}-{time.time_ns()}.json'
    req.write_text(json.dumps(data))
    cmd = [COMPOSIO, 'execute', slug] + (['--account', ACCOUNT] if ACCOUNT else []) + ['-d', '@' + str(req)] + (['--file', str(file)] if file else [])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    req.unlink(missing_ok=True)
    try:
        out = json.loads(p.stdout)
        if out.get('storedInFile') and out.get('outputFilePath'):
            out = json.loads(pathlib.Path(out['outputFilePath']).read_text())
    except ValueError:
        raise RuntimeError(f'{slug}: no readable answer (exit {p.returncode}) {p.stderr[-300:]}')
    if p.returncode or not out.get('successful'):
        raise RuntimeError(f"{slug}: {str(out.get('error') or 'failed')[:300]}")
    return out.get('data') or {}


def drive_listing(folder_id):
    data = composio('GOOGLEDRIVE_LIST_FILES', {'q': f"'{folder_id}' in parents and trashed = false", 'pageSize': 200,
                                               'fields': 'files(id,name,md5Checksum,size,webViewLink)'})
    return data.get('files', [])


def new_comments(proj, a):
    """Frame.io notes on the approved file that were not there when he pressed Approve."""
    st = load(pathlib.Path(proj) / 'frameio.json', {}) or {}
    files = st.get('files') or []
    if not files:
        return []
    now = set((st.get('logged') or {}).get(files[-1]['id'], []))
    return sorted(now - set(a.get('notes_at_approval') or []))


def notify(text):
    """Slack DM to the owner through bin/slack-post (it adds the @-mention), like the controller's notes."""
    user = str(names.config(STATE).get('slack_user_id') or '').strip()
    if not user or not SLACK_POST.exists():
        log('Slack note not sent: no slack_user_id configured')
        return False
    try:
        ok = subprocess.run([sys.executable, str(SLACK_POST), user, '-'], input=text, text=True, capture_output=True, timeout=120).returncode == 0
    except Exception as e:
        ok = False
        log(f'Slack note not sent: {type(e).__name__}: {e}')
    if not ok:   # the controller's queue posts it on its next pass
        q = STATE / 'slack-unsent.jsonl'
        with open(q, 'a') as f:
            f.write(json.dumps({'at': int(time.time()), 'text': text}) + '\n')
    return ok


def deliver(batch, dry=False, runner=None, drive=None):
    """The whole hand-off for one batch. Returns the delivery entry. Raises RuntimeError with a plain reason."""
    run = runner or subprocess.run
    ms, ok = batch_state(batch)
    prior = records().get(batch) or {}
    if prior.get('state') == 'delivered' and set(prior.get('ads') or []) >= {m.name for m in ms}:
        return prior  # already done (after the Frame.io clean the batch has no members left)
    if not ms:
        raise RuntimeError(f"No ads of '{batch}' are on Frame.io.")
    waiting = [m.name for m in ms if m not in ok]
    if waiting:
        raise RuntimeError(f"Not every ad in '{batch}' is approved yet: {', '.join(waiting)}.")
    save_record(batch, {'batch': batch, 'ads': [m.name for m in ms], 'state': 'uploading', 'started_at': time.time(), 'error': None})
    try:
        # 1. last comments: a note left after Approve means he is not done
        for m in ms:
            p = run([MAC_PY, str(ROOT / 'tools' / 'frameio.py'), 'pull', m.name], cwd=str(ROOT), capture_output=True, text=True, timeout=600)
            if p.returncode:
                raise RuntimeError(f'Could not read the last Frame.io comments for {m.name}: {(p.stdout + p.stderr)[-200:]}')
            late = new_comments(m, approval(m))
            if late:
                raise RuntimeError(f'{m.name} got {len(late)} new Frame.io note(s) after you approved it, so nothing was uploaded. '
                                   'Approve it again once the notes are done.')
        files = []
        for m in ms:
            src = m / 'MASTER.mp4'
            if not src.exists():
                raise RuntimeError(f'{m.name} has no MASTER.mp4 on this Mac.')
            st = load(m / 'frameio.json', {}) or {}
            pushed = time.mktime(time.strptime(st['files'][-1]['pushed'], '%Y-%m-%dT%H:%M:%S'))
            if src.stat().st_mtime > pushed + 120:
                raise RuntimeError(f'{m.name} was re-rendered after the version you approved went to Frame.io. Nothing was uploaded.')
            files.append((m.name, src, md5(src)))
        if dry:
            log(f"[dry run] {batch}: would upload {', '.join(n for n, _, _ in files)} to Drive ({ACCOUNT or 'default account'}), share by link, clean Frame.io")
            return save_record(batch, {'state': 'dry-run'})
        # 2. Drive
        d = drive or {}
        folder = prior.get('folder_id')
        if not folder:
            folder = (d.get('create_folder') or (lambda name: composio('GOOGLEDRIVE_CREATE_FOLDER', {'name': name})))(batch)
            folder = folder.get('id') if isinstance(folder, dict) else folder
            if not folder:
                raise RuntimeError('Drive did not return a folder id.')
            save_record(batch, {'folder_id': folder})
        listing = d.get('list') or drive_listing
        there = {f['name']: f for f in listing(folder)}
        for name, src, digest in files:
            fname = f'{name}.mp4'
            if fname in there and there[fname].get('md5Checksum') == digest:
                continue
            log(f'{batch}: uploading {fname} ({src.stat().st_size / 1048576:.0f} MB)')
            (d.get('upload') or (lambda path, fn, fid: composio('GOOGLEDRIVE_RESUMABLE_UPLOAD', {
                'metadata': {'name': fn, 'mimeType': 'video/mp4'}, 'folder_to_upload_to': fid, 'chunkSize': 5242880}, file=path, timeout=1800)))(src, fname, folder)
        there = {f['name']: f for f in listing(folder)}
        bad = [n for n, _, dg in files if there.get(f'{n}.mp4', {}).get('md5Checksum') != dg]
        if bad:
            raise RuntimeError(f"Drive copy does not match the Mac file for {', '.join(bad)}. Frame.io was left as it is.")
        (d.get('share') or (lambda fid: composio('GOOGLEDRIVE_ADD_FILE_SHARING_PREFERENCE', {'file_id': fid, 'role': 'reader', 'type': 'anyone'})))(folder)
        url = f'https://drive.google.com/drive/folders/{folder}'
        save_record(batch, {'url': url, 'files': [{'ad': n, 'name': f'{n}.mp4', 'id': there[f'{n}.mp4'].get('id'), 'md5': dg} for n, _, dg in files]})
        # 3. off Frame.io (pulls comments once more first)
        p = run([MAC_PY, str(ROOT / 'tools' / 'frameio.py'), 'clean', ms[0].name], cwd=str(ROOT), capture_output=True, text=True, timeout=600)
        cleaned = p.returncode == 0
        if not cleaned:
            log(f'{batch}: Frame.io clean failed: {(p.stdout + p.stderr)[-300:]}')
        entry = save_record(batch, {'state': 'delivered', 'delivered_at': time.time(), 'frameio_cleaned': cleaned, 'in_sheet': False})
        log(f'{batch}: delivered -> {url}' + ('' if cleaned else ' (still on Frame.io: clean failed)'))
        log(f"Approved batch *{batch}* is on Google Drive ({len(files)} video{'s' if len(files) != 1 else ''}): {url}\n"
               "Name the row in the naming sheet, then tick \"In the sheet\" on the ad board.")
        return entry
    except Exception as e:
        save_record(batch, {'state': 'failed', 'error': str(e)[:400], 'failed_at': time.time()})
        log(f'{batch}: STOPPED: {e}')
        raise


def set_in_sheet(batch, on, now=None):
    if batch not in records():
        raise ValueError('Unknown batch.')
    return save_record(batch, {'in_sheet': bool(on), 'in_sheet_at': (now or time.time()) if on else None})


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        sys.exit(__doc__)
    if '--renamed' in sys.argv:   # a session renamed the Drive folder + files to his Ad Name
        for b in args:
            print(b, save_record(b, {'renamed': True, 'renamed_at': time.time()}).get('renamed'))
        sys.exit(0)
    try:
        e = deliver(args[0], dry='--dry-run' in sys.argv)
        print(json.dumps({k: e.get(k) for k in ('state', 'url', 'frameio_cleaned')}))
    except RuntimeError as err:
        sys.exit(f'STOPPED: {err}')
