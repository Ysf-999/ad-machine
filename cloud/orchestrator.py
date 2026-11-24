"""Offline-testable durable orchestration; actual paid tool integration is disabled.

Use ``from cloud.orchestrator import Queue``. No provider SDKs are imported.
Adapters are injected and trusted; plan/jobs remain project truth. A SQLite
intent plus fsynced jobs.jsonl is required before polling an external job.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import re
import random
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path


class QueueError(RuntimeError): pass
class GateError(QueueError): pass
class LockedError(GateError): pass
class LeaseError(QueueError): pass
class AuthorizationError(QueueError): pass
class BudgetError(AuthorizationError): pass
class IdempotencyError(QueueError): pass
class SubmissionAmbiguous(QueueError): pass

# before, after, post-stage approval. No caller option can remove these gates.
_POLICIES = {
    'frames': (('plan_review',), (), 'frames_approved'),
    'clips': (('frames_approved',), (), None),
    'stitch': (('frames_approved',), ('caption_sync',), 'final_approved'),
    'render': ((), ('caption_sync',), 'final_approved'),
    'captions': ((), ('caption_sync',), 'final_approved'),
    'deliver': (('final_approved', 'all_hooks_approved', 'caption_sync', 'preflight'), (), None),
    'upload': (('final_approved', 'all_hooks_approved', 'caption_sync', 'preflight'), (), None),
}
for _stage in ('mock', 'status', 'plan_review', 'voice', 'voice-pick', 'vo',
               'realign', 'qc', 'review', 'music', 'masterqc', 'rules',
               'transcribe', 'pack', 'plan', 'broll', 'storyboard', 'verify', 'fcpxml', 'preflight'):
    _POLICIES[_stage] = ((), (), None)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def inputs_hash(inputs):
    """Hash JSON input descriptors; caller must include every input file hash."""
    return hashlib.sha256(_json(inputs).encode()).hexdigest()


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('revision must be a lowercase SHA-256 digest')
    return value


def _amount(value):
    try:
        if isinstance(value, (bool, float)): raise ValueError('use exact credit bounds')
        amount = Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValueError('invalid credit bound') from None
    if not amount.is_finite() or amount < 0: raise ValueError('invalid credit bound')
    return amount


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(f'{name} must be nonempty text without control characters')
    return value


def _plan(path):
    path = Path(path)
    if path.is_symlink(): raise GateError('symlink plan refused')
    value = json.loads(path.read_text())
    if not isinstance(value, dict): raise GateError('plan must be an object')
    if value.get('locked'): raise LockedError('project is locked')
    return inputs_hash(value)


class Queue:
    def __init__(self, db_path, provider_limits=None, *, clock=time.time,
                 backoff_base=1.0, backoff_max=300.0, workspace_root=None, jitter=None):
        if backoff_base < 0 or backoff_max < 0: raise ValueError('negative backoff')
        self.path = Path(db_path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.workspace_root = Path(workspace_root or Path(__file__).parent / '.scratch').resolve()
        self.clock = clock; self.backoff_base = backoff_base; self.backoff_max = backoff_max; self.jitter = jitter or random.random
        with closing(self._connect()) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, go INTEGER NOT NULL, cap TEXT, reserved TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS providers (
                    name TEXT PRIMARY KEY, slots INTEGER NOT NULL CHECK(slots > 0));
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    ad_id TEXT NOT NULL, stage TEXT NOT NULL, input_hash TEXT NOT NULL,
                    revision TEXT NOT NULL, inputs TEXT NOT NULL, spec TEXT NOT NULL,
                    plan_path TEXT NOT NULL, plan_hash TEXT NOT NULL, provider TEXT NOT NULL,
                    external INTEGER NOT NULL, known_cost TEXT, required_gates TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN
                      ('queued','running','awaiting_approval','failed','done','cancelled')),
                    attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL,
                    available_at REAL NOT NULL, lease_until REAL, lease_token TEXT, worker TEXT,
                    submission_started INTEGER NOT NULL DEFAULT 0,
                    provider_job_id TEXT, ambiguous INTEGER NOT NULL DEFAULT 0,
                    result TEXT, error TEXT, created_at REAL NOT NULL,
                    UNIQUE(ad_id,stage,input_hash));
                CREATE TABLE IF NOT EXISTS gates (
                    ad_id TEXT NOT NULL, revision TEXT NOT NULL, name TEXT NOT NULL,
                    passed INTEGER NOT NULL, evidence TEXT NOT NULL,
                    PRIMARY KEY(ad_id,revision,name));
                CREATE TABLE IF NOT EXISTS journal (
                    event_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, record TEXT NOT NULL,
                    flushed INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS jobs_claim ON jobs(state,available_at,provider);
            ''')
        with self._tx() as db:
            columns={r[1] for r in db.execute('PRAGMA table_info(jobs)')}
            db.execute('CREATE TABLE IF NOT EXISTS failures (job_id TEXT, attempt INTEGER, at REAL, reason TEXT, quarantined INTEGER)')
            if 'quarantined' not in columns:db.execute('ALTER TABLE jobs ADD COLUMN quarantined INTEGER NOT NULL DEFAULT 0')
            if 'remote_open' not in columns:
                db.execute('ALTER TABLE jobs ADD COLUMN remote_open INTEGER NOT NULL DEFAULT 0')
                db.execute("UPDATE jobs SET remote_open=1 WHERE submission_started=1 AND state NOT IN ('done')")
            configured = db.execute('SELECT count(*) FROM providers').fetchone()[0]
            limits = provider_limits if provider_limits is not None else (
                {} if configured else {'ffmpeg': 1, 'kie': 1, 'elevenlabs': 1})
            for name, slots in limits.items():
                _text(name, 'provider')
                if type(slots) is not int or slots < 1: raise ValueError('provider slots must be positive integers')
                prior = db.execute('SELECT slots FROM providers WHERE name=?', (name,)).fetchone()
                if prior and prior[0] != slots: raise ValueError('provider limit differs from durable configuration')
                db.execute('INSERT OR IGNORE INTO providers VALUES (?,?)', (name, slots))

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        db.execute('PRAGMA foreign_keys=ON')
        return db

    @contextmanager
    def _tx(self):
        db = self._connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback(); raise
        finally: db.close()

    @staticmethod
    def _decode(row):
        if row is None: return None
        result = dict(row)
        for key in ('inputs', 'result', 'required_gates'):
            if result.get(key) is not None: result[key] = json.loads(result[key])
        return result

    def create_run(self, *, go=False, credit_cap=None):
        cap = str(_amount(credit_cap)) if credit_cap is not None else None
        run_id = uuid.uuid4().hex
        with self._tx() as db:
            db.execute('INSERT INTO runs VALUES (?,?,?,?)', (run_id, int(go is True), cap, '0'))
        return run_id

    def run_status(self, run_id):
        db = self._connect()
        try:
            row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
            if row is None: raise KeyError(run_id)
            return dict(row)
        finally: db.close()

    def get(self, job_id):
        db = self._connect()
        try:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row is None: raise KeyError(job_id)
            return self._decode(row)
        finally: db.close()

    def jobs(self, *, run_id=None):
        db = self._connect()
        try:
            rows = db.execute('SELECT * FROM jobs' + (' WHERE run_id=?' if run_id else '') +
                              ' ORDER BY created_at,rowid', (run_id,) if run_id else ())
            return [self._decode(row) for row in rows]
        finally: db.close()

    def enqueue(self, run_id, ad_id, stage, inputs, *, plan_path, provider='ffmpeg',
                revision=None, known_cost=None, required_gates=(), max_attempts=3):
        _text(ad_id, 'ad_id'); _text(provider, 'provider')
        if stage not in _POLICIES: raise GateError('stage has no audited gate policy; composite/all stages refused')
        if not isinstance(inputs, dict): raise ValueError('inputs must be a JSON mapping')
        if type(max_attempts) is not int or max_attempts < 1: raise ValueError('max_attempts must be positive')
        path = str(self._workspace_plan(plan_path)); plan_hash = _plan(path)
        fingerprint = inputs_hash({'inputs': inputs, 'plan_hash': plan_hash})
        revision = _digest(revision) if revision is not None else fingerprint
        cost = str(_amount(known_cost)) if known_cost is not None else None
        before = sorted(set(_POLICIES[stage][0]) | {_text(g, 'gate') for g in required_gates})
        external = provider not in ('ffmpeg', 'local', 'local-subprocess', 'mock') or stage in ('upload', 'deliver')
        spec = _json({'plan_path': path, 'provider': provider, 'revision': revision,
                      'known_cost': cost, 'required_gates': before, 'max_attempts': max_attempts})
        with self._tx() as db:
            run = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
            if run is None: raise KeyError(run_id)
            if not db.execute('SELECT 1 FROM providers WHERE name=?', (provider,)).fetchone():
                raise ValueError('provider concurrency must be configured')
            old = db.execute('SELECT * FROM jobs WHERE ad_id=? AND stage=? AND input_hash=?',
                             (ad_id, stage, fingerprint)).fetchone()
            if old:
                if old['spec'] != spec: raise IdempotencyError('unchanged inputs have conflicting execution settings')
                return self._decode(old)
            if external and run['go'] and (run['cap'] is None or cost is None):
                raise BudgetError('known per-run cap and per-stage upper bound required; unknown is not zero')
            job_id = uuid.uuid4().hex
            db.execute('''INSERT INTO jobs
                (id,run_id,ad_id,stage,input_hash,revision,inputs,spec,plan_path,plan_hash,provider,
                 external,known_cost,required_gates,state,max_attempts,available_at,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (job_id, run_id, ad_id, stage, fingerprint, revision, _json(inputs), spec, path,
                 plan_hash, provider, int(external), cost, _json(before), 'queued', max_attempts,
                 self.clock(), self.clock()))
            return self._decode(db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())

    def _workspace_plan(self, plan_path):
        path = Path(plan_path).absolute()
        if not path.resolve().is_relative_to(self.workspace_root):
            raise GateError('plan must be a staged copy inside workspace_root')
        for part in (path, *path.parents):
            if part == self.workspace_root: break
            if part.is_symlink(): raise GateError('symlink workspace path refused')
        return path

    def _check_plan(self, job):
        self._workspace_plan(job['plan_path'])
        try: current = _plan(job['plan_path'])
        except (OSError, ValueError) as exc: raise GateError('plan missing or invalid') from exc
        if current != job['plan_hash']: raise GateError('plan changed; enqueue a new input snapshot')

    @staticmethod
    def _check_gates(db, job, names):
        for name in names:
            row = db.execute('SELECT passed FROM gates WHERE ad_id=? AND revision=? AND name=?',
                             (job['ad_id'], job['revision'], name)).fetchone()
            if row is None or not row['passed']: raise GateError('required gate not passed: ' + name)

    def _owned(self, db, job_id, token):
        job = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if (job is None or job['state'] != 'running' or job['lease_token'] != token or
                job['lease_until'] <= self.clock()): raise LeaseError('lease missing, stale, or expired')
        self._check_plan(job)
        self._check_gates(db, job, json.loads(job['required_gates']))
        return job

    def _delay(self, attempts):
        value=float(self.jitter())
        if not 0<=value<=1:raise ValueError('Invalid jitter')
        return min(self.backoff_max, self.backoff_base * 2 ** min(max(attempts - 1, 0), 30)) * (.5+.5*value)

    def _failure(self, db, job, error, retryable=True, ambiguous=False):
        retry = retryable and not ambiguous and job['attempts'] < job['max_attempts']
        poison=bool(retryable and not ambiguous and not retry)
        db.execute('INSERT INTO failures VALUES (?,?,?,?,?)',(job['id'],job['attempts'],self.clock(),error,int(poison)))
        db.execute('UPDATE jobs SET quarantined=? WHERE id=?',(int(poison),job['id']))
        db.execute('''UPDATE jobs SET state=?,error=?,ambiguous=?,available_at=?,
                      lease_until=NULL,lease_token=NULL,worker=NULL WHERE id=?''',
                   ('queued' if retry else 'failed', error, int(ambiguous),
                    self.clock() + self._delay(job['attempts']), job['id']))

    def _recover(self, db):
        expired = db.execute("SELECT * FROM jobs WHERE state='running' AND lease_until<=?", (self.clock(),)).fetchall()
        for job in expired:
            ambiguous = bool(job['submission_started'] and not job['provider_job_id'])
            self._failure(db, job, 'submission ambiguous: reconcile manually' if ambiguous else 'lease expired',
                          ambiguous=ambiguous)
        return len(expired)

    def recover_expired(self):
        with self._tx() as db: return self._recover(db)

    def claim(self, worker, *, run_id=None, lease_seconds=60):
        _text(worker, 'worker')
        if lease_seconds <= 0: raise ValueError('lease_seconds must be positive')
        with self._tx() as db:
            self._recover(db)
            candidates = db.execute('''SELECT j.* FROM jobs j JOIN runs r ON r.id=j.run_id
                WHERE j.state='queued' AND j.available_at<=? AND r.go=1''' +
                (' AND j.run_id=?' if run_id else '') + ' ORDER BY j.created_at,j.rowid',
                (self.clock(), run_id) if run_id else (self.clock(),)).fetchall()
            for job in candidates:
                try: self._check_plan(job)
                except GateError as exc:
                    self._failure(db, job, str(exc), retryable=False); continue
                try: self._check_gates(db, job, json.loads(job['required_gates']))
                except GateError: continue
                if job['external']:
                    run = db.execute('SELECT * FROM runs WHERE id=?', (job['run_id'],)).fetchone()
                    if run['cap'] is None or job['known_cost'] is None: continue
                limit = db.execute('SELECT slots FROM providers WHERE name=?', (job['provider'],)).fetchone()[0]
                active = db.execute("SELECT count(*) FROM jobs WHERE provider=? AND id!=? AND (state='running' OR remote_open=1)", (job['provider'],job['id'])).fetchone()[0]
                if active >= limit: continue
                token = uuid.uuid4().hex
                db.execute('''UPDATE jobs SET state='running',attempts=attempts+1,lease_token=?,
                    lease_until=?,worker=?,error=NULL WHERE id=?''',
                    (token, self.clock() + lease_seconds, worker, job['id']))
                return self._decode(db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone())
        return None

    def heartbeat(self, job_id, token, *, lease_seconds=60):
        if lease_seconds <= 0: raise ValueError('lease_seconds must be positive')
        with self._tx() as db:
            self._owned(db, job_id, token)
            db.execute('UPDATE jobs SET lease_until=? WHERE id=?', (self.clock() + lease_seconds, job_id))

    def record_gate(self, ad_id, revision, name, *, passed, evidence):
        _text(ad_id, 'ad_id'); _digest(revision); _text(name, 'gate'); _text(evidence, 'evidence')
        if type(passed) is not bool: raise ValueError('passed must be boolean')
        if name in ('frames_approved', 'final_approved'): raise GateError('approval requires approve on completed review')
        with self._tx() as db:
            db.execute('INSERT OR REPLACE INTO gates VALUES (?,?,?,?,?)',
                       (ad_id, revision, name, int(passed), evidence))

    def inherit_frames(self, job_id, source_ids):
        """Bind actual approved frame jobs to a dependent immutable mock snapshot.

        Restricted to the explicit mock graph namespace; cannot attest real media.
        """
        with self._tx() as db:
            target=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            self._check_plan(target)
            ti=json.loads(target['inputs'])
            if ti.get('mock') is not True or not source_ids:raise GateError('Mock graph frame sources required')
            tg=ti['graph']; beats=[]
            for sid in source_ids:
                src=db.execute('SELECT * FROM jobs WHERE id=?',(sid,)).fetchone()
                if not src or src['stage']!='frames' or src['state']!='done':raise GateError('Frame source not approved')
                self._check_plan(src);self._check_gates(db,src,['frames_approved'])
                si=json.loads(src['inputs']);sg=si.get('graph',{})
                if si.get('mock') is not True or any(sg.get(k)!=tg.get(k) for k in ['workflow','ad']):raise GateError('Frame approval belongs to another ad/workflow')
                beats.append(sg['node'].split(':')[-1])
            if target['stage']=='clips' and tg['node'].split(':')[-1] not in beats:raise GateError('Wrong frame beat')
            db.execute('INSERT OR REPLACE INTO gates VALUES (?,?,?,?,?)',(target['ad_id'],target['revision'],'frames_approved',1,'approved mock source jobs:'+_json(source_ids)))

    def complete(self, job_id, token, *, result=None):
        result = {} if result is None else dict(result)
        if result.get('status') == 'failed': raise GateError('failed runner result cannot complete')
        if result.get('deliverable') is True: raise GateError('queue does not certify deliverability')
        result['deliverable'] = False
        with self._tx() as db:
            job = self._owned(db, job_id, token)
            self._check_gates(db, job, _POLICIES[job['stage']][1])
            if job['external'] and not job['provider_job_id']:
                raise GateError('external jobs must persist provider id before completing')
            state = 'awaiting_approval' if _POLICIES[job['stage']][2] else 'done'
            db.execute('''UPDATE jobs SET state=?,result=?,lease_token=NULL,lease_until=NULL,
                          worker=NULL,remote_open=0 WHERE id=?''', (state, _json(result), job_id))
        return self.get(job_id)

    def approve(self, job_id, *, owner):
        _text(owner, 'owner')
        with self._tx() as db:
            job = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if job is None: raise KeyError(job_id)
            self._check_plan(job)
            if job['state'] != 'awaiting_approval': raise GateError('job is not awaiting approval')
            gate = _POLICIES[job['stage']][2]
            self._check_gates(db, job, _POLICIES[job['stage']][1])
            db.execute('INSERT OR REPLACE INTO gates VALUES (?,?,?,?,?)',
                       (job['ad_id'], job['revision'], gate, 1, owner))
            db.execute("UPDATE jobs SET state='done' WHERE id=?", (job_id,))
        return self.get(job_id)

    def fail(self, job_id, token, *, error, retryable=True, ambiguous=False):
        # Store a controlled diagnostic, never raw provider payloads or secrets.
        _text(error, 'error')
        with self._tx() as db:
            job = self._owned(db, job_id, token)
            ambiguous = ambiguous or bool(job['submission_started'] and not job['provider_job_id'])
            self._failure(db, job, error, retryable, ambiguous)
        return self.get(job_id)

    def cancel(self, job_id):
        with self._tx() as db:
            job = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if job is None: raise KeyError(job_id)
            if job['state'] in ('done', 'failed', 'cancelled'): return self._decode(job)
            # Cancellation fences local workers; it cannot cancel a remote charge.
            db.execute("UPDATE jobs SET state='cancelled',lease_until=NULL,lease_token=NULL,worker=NULL WHERE id=?", (job_id,))
        return self.get(job_id)

    def prepare_submission(self, job_id, token):
        with self._tx() as db:
            run = db.execute('SELECT r.* FROM runs r JOIN jobs j ON j.run_id=r.id WHERE j.id=?', (job_id,)).fetchone()
            if run is None or not run['go']: raise AuthorizationError('explicit go required')
            job = self._owned(db, job_id, token)
            if not job['external']: raise AuthorizationError('submission protocol is only for external adapters')
            if job['submission_started'] or job['provider_job_id']:
                raise SubmissionAmbiguous('submission already attempted; resume by id or reconcile')
            if run['cap'] is None or job['known_cost'] is None: raise BudgetError('unknown credit bound')
            reserved = _amount(run['reserved']) + _amount(job['known_cost'])
            if reserved > _amount(run['cap']): raise BudgetError('per-run credit cap exceeded')
            db.execute('UPDATE runs SET reserved=? WHERE id=?', (str(reserved), run['id']))
            limit=db.execute('SELECT slots FROM providers WHERE name=?',(job['provider'],)).fetchone()[0]
            active=db.execute('SELECT count(*) FROM jobs WHERE provider=? AND id!=? AND remote_open=1',(job['provider'],job_id)).fetchone()[0]
            if active>=limit: raise AuthorizationError('remote provider slots exhausted')
            db.execute('UPDATE jobs SET submission_started=1,remote_open=1 WHERE id=?', (job_id,))
        return self.get(job_id)

    def _save_id(self, db, job, provider_job_id, *, evidence=None):
        _text(provider_job_id, 'provider_job_id')
        if job['provider_job_id'] and job['provider_job_id'] != provider_job_id:
            raise IdempotencyError('provider id is immutable')
        db.execute('UPDATE jobs SET provider_job_id=? WHERE id=?', (provider_job_id, job['id']))
        record = {'cloud_event_id': 'provider:' + job['id'], 'key': 'cloud:' + job['id'],
                  'taskId': provider_job_id, 'state': 'submitted', 'provider': job['provider'],
                  'input_hash': job['input_hash'], 'ad_id': job['ad_id'], 'stage': job['stage']}
        if evidence: record['reconciled_by'] = evidence
        db.execute('INSERT OR IGNORE INTO journal(event_id,job_id,record) VALUES (?,?,?)',
                   (record['cloud_event_id'], job['id'], _json(record)))

    def record_provider_job(self, job_id, token, provider_job_id):
        with self._tx() as db:
            job = self._owned(db, job_id, token)
            if not job['submission_started']: raise GateError('submission intent required')
            self._save_id(db, job, provider_job_id)
        self.flush_journal(job_id)
        return self.get(job_id)

    def flush_journal(self, job_id):
        # DB transaction serializes queue writers; flock also covers separate
        # compatible processes appending to the same project journal.
        with self._tx() as db:
            job = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if job is None: raise KeyError(job_id)
            self._check_plan(job)
            rows = db.execute('SELECT * FROM journal WHERE job_id=? AND flushed=0', (job_id,)).fetchall()
            if not rows: return
            path = Path(job['plan_path']).parent / 'jobs.jsonl'
            if path.is_symlink(): raise GateError('symlink journal refused')
            with path.open('a+b') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                stream.seek(0); raw = stream.read()
                # Never append to truncated/invalid existing state.
                if raw and not raw.endswith(b'\n'): raise GateError('truncated jobs.jsonl requires reconciliation')
                seen = {json.loads(line).get('cloud_event_id') for line in raw.splitlines() if line}
                for row in rows:
                    if row['event_id'] not in seen:
                        stream.write(row['record'].encode() + b'\n'); seen.add(row['event_id'])
                stream.flush()
                import os
                os.fsync(stream.fileno())
                fd = os.open(path.parent, os.O_RDONLY)
                try: os.fsync(fd)
                finally: os.close(fd)
                db.execute('UPDATE journal SET flushed=1 WHERE job_id=?', (job_id,))

    def poll_ready(self, job_id, token):
        self.flush_journal(job_id)
        with self._tx() as db:
            job = self._owned(db, job_id, token)
            if not job['provider_job_id']: raise SubmissionAmbiguous('no durable provider id')
            return job['provider_job_id']

    def reconcile(self, job_id, provider_job_id, *, owner):
        _text(owner, 'owner')
        with self._tx() as db:
            job = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if job is None: raise KeyError(job_id)
            self._check_plan(job)
            if job['state'] != 'failed' or not job['ambiguous']:
                raise GateError('only an ambiguous failed submission can be reconciled')
            self._save_id(db, job, provider_job_id, evidence=owner)
            db.execute("UPDATE jobs SET state='queued',ambiguous=0,error=NULL,available_at=? WHERE id=?", (self.clock(), job_id))
        self.flush_journal(job_id)
        return self.get(job_id)

    def provider_terminal(self, job_id, token):
        """Trusted adapter confirms terminal status; cancellation alone never frees a remote slot."""
        with self._tx() as db:
            job=self._owned(db,job_id,token)
            if not job['provider_job_id']:raise SubmissionAmbiguous('terminal status needs durable id')
            db.execute('UPDATE jobs SET remote_open=0 WHERE id=?',(job_id,))

    def run_once(self, providers, *, worker='worker', run_id=None, lease_seconds=60):
        """Injected mock adapter helper, never a wrapper for kie.run or paid ad.py.

        Free adapter: run(job)->runner result. External mock: submit(job)->id,
        poll(job,id)->{status: done|pending|failed, result: {...}}. The caller
        renews leases for long work; no background thread or network is started.
        """
        job = self.claim(worker, run_id=run_id, lease_seconds=lease_seconds)
        if job is None: return None
        job_id, token = job['id'], job['lease_token']
        try:
            adapter = providers[job['provider']]
            if not job['external']:
                from reliability import renewing
                with renewing(self,job,lease_seconds=lease_seconds):result = adapter.run(job)
                if result.get('status') == 'failed':
                    return self.fail(job_id, token, error='local runner failed', retryable=False)
                return self.complete(job_id, token, result=result)
            if not job['provider_job_id']:
                self.prepare_submission(job_id, token)
                try:
                    from reliability import renewing
                    with renewing(self,job,lease_seconds=lease_seconds):provider_id = adapter.submit(job)
                except Exception:
                    return self.fail(job_id, token, error='submission ambiguous: reconcile manually', ambiguous=True)
                self.record_provider_job(job_id, token, provider_id)
            provider_id = self.poll_ready(job_id, token)
            from reliability import renewing
            with renewing(self,job,lease_seconds=lease_seconds):reply = adapter.poll(self.get(job_id), provider_id)
            if reply['status'] == 'done': return self.complete(job_id, token, result=reply.get('result'))
            if reply['status'] == 'failed':
                self.provider_terminal(job_id,token)
                return self.fail(job_id, token, error='provider terminal failure', retryable=False)
            if reply['status'] != 'pending': raise GateError('unknown provider status')
            return self.fail(job_id, token, error='provider pending', retryable=True)
        except LeaseError:
            raise
        except Exception as exc:
            # Only controlled exception type names are logged; API messages may
            # contain tokens or response payloads. Known IDs survive all retries.
            return self.fail(job_id, token, error='adapter error: ' + type(exc).__name__, retryable=True)
