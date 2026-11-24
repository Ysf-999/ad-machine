"""Offline approval gates. Only staged copies under cloud/.scratch are writable.

No tool execution, auth, notifications, sourcing, or remote storage construction.
Part of the queue prototype (not used by cloud/ctl.py).
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import html
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import time
from urllib.parse import unquote, urlsplit
import uuid

SCRATCH = Path(__file__).absolute().parent / '.scratch'
STATE_KEY = 'cloud_approval'
CHECKS = ('qc', 'masterqc', 'caption_sync', 'av_check', 'preflight')


class ApprovalError(ValueError):
    """Fail-closed refusal; callers must not schedule the gated stage."""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _clean(path):
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ApprovalError('Parent traversal refused')
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ApprovalError('Symlink refused')
    return path


def _relative(name):
    if (not isinstance(name, str) or not name or '\\' in name or
            any(ord(c) < 32 for c in name) or
            any(p in ('', '.', '..') for p in name.split('/')) or
            any(p.startswith('.') for p in name.split('/'))):
        raise ApprovalError('Expected a safe relative file path; hidden files refused')
    return name


def _file(root, name, *, private=True):
    path = _clean(root / _relative(name))
    if not path.is_relative_to(root) or not path.is_file():
        raise ApprovalError('Missing or unsafe file: ' + name)
    if private and path.stat().st_nlink != 1:
        raise ApprovalError('Hardlinked staged files refused')
    return path


def _read(path):
    try:
        value = json.loads(path.read_text())
    except (ValueError, OSError) as exc:
        raise ApprovalError('Invalid JSON file: ' + path.name) from exc
    if not isinstance(value, dict):
        raise ApprovalError('Expected a JSON object')
    return value


def _beats(plan):
    beats = plan.get('beats')
    if (not isinstance(beats, list) or not beats or
            any(not isinstance(b, dict) or type(b.get('n')) is not int or b['n'] < 1 for b in beats) or
            len({b['n'] for b in beats}) != len(beats)):
        raise ApprovalError('Plan requires unique positive integer beats')
    return {b['n']: b for b in beats}


def _scratch_path(path):
    path = _clean(path)
    scratch = _clean(SCRATCH)
    if not path.is_relative_to(scratch) or path == scratch:
        raise ApprovalError('Writes require a path below cloud/.scratch')
    return path


def _load(project):
    project = _scratch_path(project)
    plan = _read(_file(project, 'plan.json'))
    state = plan.get(STATE_KEY)
    if not isinstance(state, dict) or state.get('version') != 1 or not state.get('id'):
        raise ApprovalError('Not an approval-staged project; use stage_project first')
    source = _clean(state['source'])
    if plan.get('locked') or _read(_file(source, 'plan.json', private=False)).get('locked'):
        raise ApprovalError('LOCKED source or staged project; no force override')
    _beats(plan)
    return project, plan


def _atomic(path, data):
    path = _scratch_path(path)
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ApprovalError('Unsafe output file')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.approval-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


@contextmanager
def _locked(project):
    project, _ = _load(project)
    lock = _clean(project / '.approval.lock')
    if lock.exists() and (not lock.is_file() or lock.stat().st_nlink != 1):
        raise ApprovalError('Unsafe lock file')
    with lock.open('a+b') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield _load(project)


def _save(project, plan):
    _load(project)  # recheck both lock flags immediately before replacement
    _atomic(project / 'plan.json', _json(plan) + b'\n')


def stage_project(source, files, *, intake=None, original_source=None):
    """Copy an explicit file manifest. Source, jobs and existing assets are never edited."""
    from hygiene import require_space, clone_file
    require_space()
    source = _clean(source)
    original = _read(_file(source, 'plan.json', private=False))
    identity_source = _clean(original_source) if original_source is not None else source
    identity_plan = _read(_file(identity_source, 'plan.json', private=False))
    if identity_plan.get('locked') or original.get('ad') != identity_plan.get('ad'):
        raise ApprovalError('LOCKED or mismatched original source')
    if original.get('locked'):
        raise ApprovalError('LOCKED source')
    _beats(original)
    files = list(files)
    if 'plan.json' not in files or 'REVIEW.html' not in files or len(set(files)) != len(files):
        raise ApprovalError('Declare plan.json and existing REVIEW.html exactly once')
    sources = {name: _file(source, name, private=False) for name in files}
    intake = {} if intake is None else intake
    if (not isinstance(intake, dict) or set(intake) - {'brief', 'reference', 'script', 'visuals'} or
            any(not isinstance(v, (str, list)) or
                isinstance(v, list) and any(not isinstance(x, str) for x in v) for v in intake.values())):
        raise ApprovalError('Intake supports optional brief/reference/script/visuals text or lists')
    _clean(SCRATCH).mkdir(exist_ok=True)
    project = Path(tempfile.mkdtemp(prefix='approval-', dir=SCRATCH))
    try:
        for name, path in sources.items():
            dest = project / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            clone_file(path, dest)
        plan = _read(project / 'plan.json')
        if plan != original or _read(source / 'plan.json') != original:
            raise ApprovalError('Source plan changed during staging')
        if original_source is not None and 'approved' in plan: plan['approved'] = False
        plan['approved_beats'] = []  # inherited approval is not approval of this staged review
        plan[STATE_KEY] = {'version': 1, 'id': uuid.uuid4().hex, 'source': str(identity_source),
                           'files': sorted(files), 'intake': {'sourcing': 'automatic', 'overrides': intake},
                           'decisions': {'frames': {}, 'final': {}}, 'pending_redo': {},
                           'notes': [], 'applied': [], 'checks': {}, 'final_confirmation': None}
        _atomic(project / 'plan.json', _json(plan) + b'\n')
        _review_files(project)
        return project
    except BaseException:
        shutil.rmtree(project)
        raise


def _assets(project, n, kind, *, required=True):
    directory, stem, ext = ('FRAMES', 'scene', '.png') if kind == 'frame' else ('CLIPS', 'clip', '.mp4')
    root = _clean(project / directory)
    result = {}
    for ending in ('', '_end') if kind == 'frame' else ('',):
        pattern = re.compile(rf'{stem}_{n:02d}{ending}(?:_v(\d+))?{re.escape(ext)}')
        matches = [(int(m.group(1) or 1), f) for f in root.glob('*')
                   if (m := pattern.fullmatch(f.name))]
        if matches:
            path = max(matches, key=lambda item: (item[0], item[1].name))[1]
            rel = str(path.relative_to(project))
            f = _file(project, rel)
            if not f.stat().st_size:
                raise ApprovalError('Empty media: ' + rel)
            result[rel] = _digest(f)
        elif not ending and required:
            raise ApprovalError(f'Missing {kind} for beat {n}')
    return result


def _base(project, plan):
    state = plan[STATE_KEY]
    common = {}
    for name in state['files']:
        top = name.split('/')[0]
        if (top in {'plan.json', 'jobs.jsonl', 'REVIEW.html', 'FRAMES', 'CLIPS', 'QC', 'EDIT_KIT', 'PREFLIGHT.md'}
                or top.startswith('MASTER')):
            continue
        common[name] = _digest(_file(project, name))
    return {'plan': {k: v for k, v in plan.items() if k not in {STATE_KEY, 'approved_beats', 'beats'}},
            'inputs': common, 'intake': state['intake']}


def _beat_hash(project, plan, n, phase):
    data = {'base': _base(project, plan), 'beat': _beats(plan)[n],
            'frames': _assets(project, n, 'frame')}
    if phase == 'final':
        data['clips'] = _assets(project, n, 'clip')
    # Clip-only notes must not invalidate the start-frame approval.
    if phase == 'frames':
        data['beat'] = {k: v for k, v in data['beat'].items() if k != 'clip_note'}
    return _hash(data)


def _render_hash(project, plan):
    files = {}
    for folder in ('FRAMES', 'CLIPS', 'VO', 'EDIT_KIT'):
        root = _clean(project / folder)
        for path in sorted(root.rglob('*')):
            if path.is_dir() and not path.is_symlink():
                continue
            rel = str(path.relative_to(project))
            files[rel] = _digest(_file(project, rel))
    files['MASTER.mp4'] = _digest(_file(project, 'MASTER.mp4'))
    return _hash({'base': _base(project, plan), 'beats': plan['beats'], 'files': files})


def render_hash(project):
    """Capture before running QC; pass this exact value to record_check afterwards."""
    project, plan = _load(project)
    return _render_hash(project, plan)


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {'src', 'href', 'poster'} and value:
                self.links.append(value)
            if key in {'srcset'} or tag in {'base', 'iframe', 'object', 'embed'}:
                raise ApprovalError('Unsupported review resource')


def _review_files(project):
    files = {'REVIEW.html': _file(project, 'REVIEW.html')}
    queue = ['REVIEW.html']
    while queue:
        name = queue.pop()
        parser = _Links()
        parser.feed(files[name].read_text())
        for value in parser.links:
            url = urlsplit(value)
            if url.scheme or url.netloc or value.startswith('/') or '\\' in value:
                raise ApprovalError('Review requires local relative URLs')
            if not url.path:
                continue
            rel = str(Path(name).parent / unquote(url.path))
            path = _file(project, rel)
            if path.suffix.lower() not in {'.html', '.png', '.jpg', '.jpeg', '.webp', '.mp4', '.mp3', '.wav', '.json', '.md', '.txt'}:
                raise ApprovalError('Unsupported review asset type')
            if rel not in files:
                files[rel] = path
                if path.suffix.lower() == '.html':
                    queue.append(rel)
    return files


def _snapshot(project, plan, phase):
    if phase not in ('frames', 'final'):
        raise ApprovalError('Phase must be frames or final')
    review = _review_files(project)
    data = {'phase': phase, 'beats': {str(n): _beat_hash(project, plan, n, phase) for n in _beats(plan)},
            'review': {name: _digest(path) for name, path in review.items()
                       if phase == 'final' or path.suffix.lower() not in {'.mp4', '.mp3', '.wav'}}}
    if phase == 'final':
        data.update(render=_render_hash(project, plan), checks=plan[STATE_KEY]['checks'])
    return {'phase': phase, 'input_hash': _hash(data), 'workspace_id': plan[STATE_KEY]['id']}


def snapshot(project, phase='frames'):
    project, plan = _load(project)
    return _snapshot(project, plan, phase)


def _valid_frames(project, plan):
    records = plan[STATE_KEY]['decisions']['frames']
    return all(records.get(str(n)) == _beat_hash(project, plan, n, 'frames') for n in _beats(plan))


def preflight_fingerprint(path):
    """Exact tools/preflight.py identity; SHA-256 receipts provide stronger binding too."""
    h = hashlib.sha1()
    n = Path(path).stat().st_size
    with Path(path).open('rb') as stream:
        h.update(stream.read(1 << 20))
        stream.seek(max(0, n - (1 << 20)))
        h.update(stream.read(1 << 20))
    return f'{n}-{h.hexdigest()[:16]}'


def _check_report(project, plan, name, report):
    text = _file(project, report).read_text()
    if re.search(r'\b(?:SKIP(?:PED)?|UNAVAILABLE|MANUAL|NOT[ _-]CHECKED)\b', text, re.I):
        raise ApprovalError('Skipped/unchecked QC cannot pass')
    valid = False
    if name == 'qc':
        try:
            rows = json.loads(text)
            items = {r['item']: r['verdict'] for r in rows}
            expected = {Path(f).name for n in _beats(plan) for kind in ('frame', 'clip')
                        for f in _assets(project, n, kind)}
            valid = bool(expected) and all(items.get(f) == 'PASS' for f in expected)
        except (TypeError, KeyError, ValueError):
            valid = False
    elif name == 'masterqc':
        valid = bool(re.search(r'^\s*VERDICT:\s*SHIP\s*$', text, re.M)) and not re.search(r'VERDICT:\s*FIX', text)
    elif name == 'caption_sync':
        valid = 'CAPTION SYNC PASS' in text and not re.search(r'\bFAIL\b', text)
    elif name == 'av_check':
        valid = bool(re.search(r'PASS: (?:sound and picture in sync|all checks)', text)) and not re.search(r'\bFAIL\b', text)
    elif name == 'preflight':
        # Match Frame.io's file identity/checklist gate, with no override or skip bypass.
        valid = (re.search(r'^master: MASTER\.mp4\s*$', text, re.M) is not None and
                 re.search(r'^fingerprint: ' + re.escape(preflight_fingerprint(project / 'MASTER.mp4')) + r'\s*$', text, re.M) is not None and
                 not re.search(r'^- \[ \]|^- FAIL', text, re.M) and
                 '- PASS format ' in text and '- PASS av_check' in text and
                 'CAPTION SYNC PASS' in text and bool(re.search(r'^- \[(?:x|n/a)\]', text, re.M)))
    if not valid:
        raise ApprovalError('Missing or unsuccessful ' + name + ' evidence')


def record_check(project, name, report, *, expected_input_hash, returncode):
    """Accept evidence from a trusted local worker; never executes a QC/provider tool."""
    if name not in CHECKS or type(returncode) is not int or returncode != 0:
        raise ApprovalError('A known check with successful exit is required')
    if report != 'PREFLIGHT.md' and not report.startswith('QC/'):
        raise ApprovalError('Evidence must be in QC/ or PREFLIGHT.md')
    with _locked(project) as (project, plan):
        current = _render_hash(project, plan)
        if expected_input_hash != current:
            raise ApprovalError('Stale QC input hash')
        _check_report(project, plan, name, report)
        plan[STATE_KEY]['checks'][name] = {'input_hash': current, 'report': report,
                                         'sha256': _digest(_file(project, report))}
        _save(project, plan)


def _automatic_preflight(project, text):
    """Validate existing automatic section only; never alters manual requirements."""
    if not re.search(r'^master: MASTER\.mp4\s*$', text, re.M):
        raise ApprovalError('Preflight master missing')
    identity = preflight_fingerprint(project / 'MASTER.mp4')
    if not re.search(r'^fingerprint: ' + re.escape(identity) + r'\s*$', text, re.M):
        raise ApprovalError('Preflight belongs to another file')
    if '## Automatic checks' not in text:
        raise ApprovalError('Automatic preflight section missing')
    section = text.split('## Automatic checks', 1)[1].split('## ', 1)[0]
    if re.search(r'^- FAIL\b|\bSKIP(?:PED)?\b|NOT[ _-]CHECKED', section, re.M | re.I):
        raise ApprovalError('Automatic preflight failed or unchecked')
    for label in ['format 1080x1920', 'T13 ', 'T09 ', 'T24 ', 'T23 ', 'T06 ', 'T19 ', 'av_check', 'T17 CAPTION SYNC PASS']:
        if not re.search(r'^- PASS ' + re.escape(label), section, re.M):
            raise ApprovalError('Missing automatic preflight gate: ' + label)


def record_automated_review(project, reports, *, master_sha256, returncodes):
    """Trusted worker evidence ingestion for review parking, NEVER final approval.

    This does not populate/replace the full preflight/QC checks required by
    _require(). In particular unanswered manual boxes remain a final blocker.
    """
    expected = {'caption_sync', 'av_check', 'preflight'}
    if set(reports) != expected or set(returncodes) != expected:
        raise ApprovalError('All three independent gate receipts required')
    if any(type(v) is not int or v != 0 for v in returncodes.values()):
        raise ApprovalError('Independent gate process failed')
    with _locked(project) as (project, plan):
        if _digest(_file(project, 'MASTER.mp4')) != master_sha256:
            raise ApprovalError('Output master SHA mismatch')
        receipt = {'version': 1, 'master_sha256': master_sha256,
                   'input_hash': _render_hash(project, plan), 'reports': {}}
        for name, rel in reports.items():
            if (name == 'preflight' and rel != 'PREFLIGHT.md') or (name != 'preflight' and not rel.startswith('QC/')):
                raise ApprovalError('Invalid gate report location')
            file = _file(project, rel)
            if name == 'preflight': _automatic_preflight(project, file.read_text())
            else: _check_report(project, plan, name, rel)
            receipt['reports'][name] = {'report': rel, 'sha256': _digest(file), 'returncode': 0}
        plan[STATE_KEY]['automated_review'] = receipt
        _save(project, plan)


def automated_review_status(project):
    """Revalidate exact bytes/reports for AWAIT final review, not Approved."""
    try:
        project, plan = _load(project)
        receipt = plan[STATE_KEY].get('automated_review')
        if not receipt or receipt['master_sha256'] != _digest(_file(project, 'MASTER.mp4')) or receipt['input_hash'] != _render_hash(project, plan):
            raise ApprovalError('Missing/stale automated evidence')
        if set(receipt['reports']) != {'caption_sync', 'av_check', 'preflight'}:
            raise ApprovalError('Missing gate evidence')
        for name, row in receipt['reports'].items():
            path = _file(project, row['report'])
            if row['returncode'] != 0 or row['sha256'] != _digest(path):
                raise ApprovalError('Changed/failed gate report')
            if name == 'preflight': _automatic_preflight(project, path.read_text())
            else: _check_report(project, plan, name, row['report'])
        return {'state': 'awaiting_final_review', 'master_sha256': receipt['master_sha256'],
                'approved': False, 'deliverable': False,
                'manual_boxes_unanswered': _file(project, receipt['reports']['preflight']['report']).read_text().count('- [ ]')}
    except (ApprovalError, OSError, KeyError, ValueError) as exc:
        return {'state': 'blocked', 'reason': str(exc), 'approved': False, 'deliverable': False}


def _require(project, plan, stage):
    if stage not in {'clips', 'final', 'hooks'}:
        raise ApprovalError('Unknown approval gate')
    if not _valid_frames(project, plan):
        raise ApprovalError('All current start frames require explicit approval before clips')
    if stage == 'clips':
        return
    state = plan[STATE_KEY]
    if state['pending_redo']:
        raise ApprovalError('Pending revisions block final review')
    render = _render_hash(project, plan)
    for name in CHECKS:
        check = state['checks'].get(name)
        if not check or check['input_hash'] != render or _digest(_file(project, check['report'])) != check['sha256']:
            raise ApprovalError('Missing/stale QC prerequisite: ' + name)
        _check_report(project, plan, name, check['report'])
    if stage == 'hooks' and state['final_confirmation'] != _snapshot(project, plan, 'final')['input_hash']:
        raise ApprovalError('Base final requires explicit approval before hooks')


def require_stage(project, stage):
    project, plan = _load(project)
    _require(project, plan, stage)


def _target(plan, action, phase, beat, note, kind):
    if action not in {'approve', 'revise'} or phase not in {'frames', 'final'}:
        raise ApprovalError('Unknown action or phase')
    if (not isinstance(note, str) or len(note) > 4000 or
            any(ord(c) < 32 for c in note) or '\u2028' in note or '\u2029' in note):
        raise ApprovalError('Note must be one line, at most 4000 characters')
    if beat != 'all' and (type(beat) is not int or beat not in _beats(plan)):
        raise ApprovalError('Unknown beat')
    if kind not in {'frame', 'clip'} or phase == 'frames' and kind != 'frame':
        raise ApprovalError('Invalid revision kind for phase')
    if action == 'revise' and (beat == 'all' or not note.strip()):
        raise ApprovalError('A revision needs exactly one beat and a note')
    if action == 'revise' and _beats(plan)[beat].get('lib'):
        raise ApprovalError('Library beat cannot be redone by ad.py')


def _key(key):
    if not isinstance(key, bytes) or len(key) < 32:
        raise ApprovalError('Provide a signing key of at least 32 bytes')
    return key


def sign_decision(project, action, phase, beat, note='', *, key, kind=None, expires_in=3600):
    """Return signed JSON; this does not apply the decision."""
    project, plan = _load(project)
    kind = kind or ('frame' if phase == 'frames' else 'clip')
    _target(plan, action, phase, beat, note, kind)
    if type(expires_in) is not int or expires_in > 86400:
        raise ApprovalError('Decision lifetime must not exceed one day')
    if phase == 'final':
        _require(project, plan, 'final')
    now = int(time.time())
    payload = dict(_snapshot(project, plan, phase), version=1, id=uuid.uuid4().hex,
                   action=action, beat=beat, note=note, kind=kind, issued=now, expires=now + expires_in)
    return {'payload': payload, 'signature': hmac.new(_key(key), _json(payload), hashlib.sha256).hexdigest()}


def _sync_approved(project, plan):
    state = plan[STATE_KEY]
    plan['approved_beats'] = [n for n in sorted(_beats(plan)) if str(n) not in state['pending_redo'] and
                             state['decisions']['frames'].get(str(n)) == _beat_hash(project, plan, n, 'frames')]


def apply_decision(project, decision, *, key):
    if not isinstance(decision, dict) or set(decision) != {'payload', 'signature'}:
        raise ApprovalError('Malformed signed decision')
    payload, signature = decision['payload'], decision['signature']
    if not isinstance(payload, dict) or not isinstance(signature, str) or not hmac.compare_digest(
            signature, hmac.new(_key(key), _json(payload), hashlib.sha256).hexdigest()):
        raise ApprovalError('Invalid decision signature')
    fields = {'phase', 'input_hash', 'workspace_id', 'version', 'id', 'action', 'beat', 'note', 'kind', 'issued', 'expires'}
    if (set(payload) != fields or payload['version'] != 1 or
            type(payload['issued']) is not int or type(payload['expires']) is not int or
            not payload['issued'] <= time.time() < payload['expires'] or
            payload['expires'] - payload['issued'] > 86400):
        raise ApprovalError('Malformed or expired decision')
    with _locked(project) as (project, plan):
        state = plan[STATE_KEY]
        action, phase, beat, note, kind = (payload[k] for k in ('action', 'phase', 'beat', 'note', 'kind'))
        _target(plan, action, phase, beat, note, kind)
        if payload['workspace_id'] != state['id'] or payload['id'] in state['applied']:
            raise ApprovalError('Wrong workspace or replayed decision')
        if payload['input_hash'] != _snapshot(project, plan, phase)['input_hash']:
            raise ApprovalError('Stale decision input hash')
        if phase == 'final':
            _require(project, plan, 'final')
        if action == 'approve':
            targets = list(_beats(plan)) if beat == 'all' else [beat]
            if any(str(n) in state['pending_redo'] and
                   (phase == 'final' or state['pending_redo'][str(n)]['kind'] == 'frame') for n in targets):
                raise ApprovalError('Complete affected redo before approving it')
            for n in targets:
                state['decisions'][phase][str(n)] = _beat_hash(project, plan, n, phase)
            if phase == 'final' and beat == 'all':
                state['final_confirmation'] = payload['input_hash']
        else:
            n = str(beat)
            _beats(plan)[beat]['frame_note' if kind == 'frame' else 'clip_note'] = note
            for affected_phase in (('frames', 'final') if kind == 'frame' else ('final',)):
                state['decisions'][affected_phase].pop(n, None)
            state['final_confirmation'] = None
            state['pending_redo'][n] = {'kind': kind, 'note': note, 'before': _assets(project, beat, kind),
                                         'argv': ['ad.py', '.', 'redo', n, kind, note]}
            if kind == 'frame':
                state['pending_redo'][n]['then_clip'] = _assets(project, beat, 'clip', required=False)
        state['notes'].append(f'REVIEW {project.name}\nbeat {beat}: ' +
                              ('approve' if action == 'approve' else 'redo-' + kind) +
                              (' — ' + note if note else ''))
        state['applied'].append(payload['id'])
        _sync_approved(project, plan)
        _save(project, plan)
    return status(project)


def complete_redo(project, beat):
    """Worker acknowledgement only after the affected latest asset actually changes."""
    with _locked(project) as (project, plan):
        pending = plan[STATE_KEY]['pending_redo'].get(str(beat))
        if not pending or sorted(_assets(project, beat, pending['kind']).values()) == sorted(pending['before'].values()):
            raise ApprovalError('No changed asset for this pending beat')
        if pending['kind'] == 'frame':
            plan[STATE_KEY]['pending_redo'][str(beat)] = {
                'kind': 'clip', 'note': pending['note'], 'before': pending['then_clip'],
                'argv': ['ad.py', '.', 'redo', str(beat), 'clip', pending['note']]}
        else:
            del plan[STATE_KEY]['pending_redo'][str(beat)]
        _sync_approved(project, plan)
        _save(project, plan)


def status(project):
    project, plan = _load(project)
    result = {'frames': 'awaiting_approval', 'final': 'blocked', 'approved': False}
    try:
        if _valid_frames(project, plan):
            result['frames'] = 'done'
        _require(project, plan, 'final')
        result['final'] = 'awaiting_approval'
        if plan[STATE_KEY]['final_confirmation'] == _snapshot(project, plan, 'final')['input_hash']:
            result.update(final='done', approved=True)
    except (ApprovalError, OSError) as exc:
        result['reason'] = str(exc)
    return result


def batch_status(base, hooks, *, expected_hooks=3):
    hooks = list(hooks)
    projects = [_clean(base), *(_clean(p) for p in hooks)]
    if (type(expected_hooks) is not int or expected_hooks < 1 or len(set(projects)) != len(projects) or
            len({p.name for p in projects}) != len(projects)):
        raise ApprovalError('Declare distinct base/hooks and positive expected hook count')
    members = {}
    for project in projects:
        try:
            members[project.name] = status(project)
        except (ApprovalError, OSError) as exc:
            members[project.name] = {'approved': False, 'reason': str(exc)}
    approved = len(hooks) == expected_hooks and all(s['approved'] for s in members.values())
    return {'approved': approved, 'status': 'Approved' if approved else 'Awaiting approval', 'members': members}


def _bundle(files, *, storage=None):
    from hygiene import require_space
    require_space(write_bytes=2*sum(len(v) for v in files.values())+65536)
    _clean(SCRATCH).mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='review-bundle-', dir=SCRATCH) as td:
        archive = Path(td) / 'review.tar'
        with tarfile.open(archive, 'w', format=tarfile.USTAR_FORMAT) as tf:
            for name, data in sorted(files.items()):
                _relative(name)
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o644
                tf.addfile(info, io.BytesIO(data))
        digest = _digest(archive)
        destination = _scratch_path(SCRATCH / 'review-objects' / 'sha256' / digest[:2] / (digest + '.tar'))
        if destination.exists():
            if _digest(destination) != digest:
                raise ApprovalError('Corrupt local content-addressed bundle')
        else:
            _atomic(destination, archive.read_bytes())
        result = {'sha256': digest, 'size': destination.stat().st_size, 'path': str(destination)}
        if storage is not None:
            # Existing LocalStorage contract, also usable by a local injected fake.
            # No credentials/SDKs or external backends are constructed here.
            if not hasattr(storage, 'root') or not callable(getattr(storage, 'put', None)):
                raise ApprovalError('Storage requires local root and put(path, expected_sha256=...)')
            _scratch_path(storage.root)
            ref = storage.put(destination, expected_sha256=digest)
            actual = ref if isinstance(ref, dict) else {'sha256': ref.sha256, 'size': ref.size}
            if actual.get('sha256') != digest or actual.get('size') != result['size']:
                raise ApprovalError('Storage returned mismatched content identity')
        return result


def publish_review(project, *, storage=None):
    with _locked(project) as (project, plan):
        from hygiene import require_space
        review_files=_review_files(project)
        require_space(write_bytes=2*sum(p.stat().st_size for p in review_files.values())+65536)
        files = {name: path.read_bytes() for name, path in review_files.items()}
        # QC readiness is exposed as metadata, never fabricated by publishing a page.
        files['approval-status.json'] = _json(status(project))
        return _bundle(files, storage=storage)


def publish_batch(base, hooks, *, expected_hooks=3, storage=None):
    hooks = list(hooks)
    state = batch_status(base, hooks, expected_hooks=expected_hooks)
    files = {}
    links = []
    for project in [base, *hooks]:
        with _locked(project) as (project, _):
            prefix = 'ads/' + project.name + '/'
            for name, path in _review_files(project).items():
                files[prefix + name] = path.read_bytes()
            links.append('<li><a href="' + prefix + 'REVIEW.html">' + html.escape(project.name) + '</a></li>')
    files['index.html'] = ('<!doctype html><meta charset="utf-8"><title>Batch review</title><h1>' +
                           state['status'] + '</h1><ul>' + ''.join(links) + '</ul>').encode()
    files['approval-status.json'] = _json(state)
    return _bundle(files, storage=storage)


def main(argv=None):
    """Delegatable CLI: return 0 on success, 2 on fail-closed refusal."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for action in ('approve', 'revise'):
        command = sub.add_parser(action)
        command.add_argument('project')
        command.add_argument('beat')
        command.add_argument('note', nargs='?', default='')
        command.add_argument('--phase', choices=('frames', 'final'), required=True)
        command.add_argument('--kind', choices=('frame', 'clip'))
        command.add_argument('--out', required=True)
    for name in ('apply', 'gate', 'status', 'snapshot', 'redo-complete', 'publish'):
        command = sub.add_parser(name)
        command.add_argument('project')
        if name in {'apply', 'gate', 'redo-complete'}:
            command.add_argument('value')
        if name == 'snapshot':
            command.add_argument('--phase', choices=('frames', 'final'), default='frames')
    args = parser.parse_args(argv)
    try:
        key = os.environ.get('CLOUD_APPROVAL_KEY', '').encode()
        if args.command in {'approve', 'revise'}:
            beat = 'all' if args.beat == 'all' else int(args.beat)
            decision = sign_decision(args.project, args.command, args.phase, beat, args.note, key=key, kind=args.kind)
            output = _scratch_path(args.out)
            if output.exists():
                raise ApprovalError('Decision output already exists; use a fresh filename')
            _atomic(output, _json(decision) + b'\n')
            result = {'decision_file': str(output)}
        elif args.command == 'apply':
            result = apply_decision(args.project, _read(_clean(args.value)), key=key)
        elif args.command == 'gate':
            require_stage(args.project, args.value)
            result = {'allowed': True, 'stage': args.value}
        elif args.command == 'redo-complete':
            complete_redo(args.project, int(args.value))
            result = status(args.project)
        elif args.command == 'snapshot':
            result = snapshot(args.project, args.phase)
        elif args.command == 'publish':
            result = publish_review(args.project)
        else:
            result = status(args.project)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ApprovalError, OSError, ValueError, KeyError, TypeError) as exc:
        print('Approval refused: ' + str(exc), file=__import__('sys').stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
