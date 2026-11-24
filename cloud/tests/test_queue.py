"""SQLite crash/concurrency tests. Provider values/costs below are fictional test units."""
from disk_test_support import DiskIndependentTestCase

import json
import random
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from cloud import orchestrator as queue


class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now


class QueueTests(DiskIndependentTestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / '.scratch'
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.plan = self.root / 'plan.json'; self.plan.write_text('{}')
        self.clock = Clock()
        self.db = self.root / 'queue.sqlite'
        self.q = queue.Queue(self.db, provider_limits={'ffmpeg': 2, 'kie': 2, 'elevenlabs': 1},
                             clock=self.clock, backoff_base=2)
        self.run = self.q.create_run(go=True, credit_cap='20')

    def add(self, *, stage='mock', provider='ffmpeg', inputs=None, **kwargs):
        return self.q.enqueue(self.run, 'ad', stage, inputs or {'manifest': 'test'},
                              plan_path=self.plan, provider=provider, **kwargs)

    def test_workspace_restriction_prevents_source_journal_writes(self):
        allowed = self.root / 'allowed'; allowed.mkdir()
        q = queue.Queue(self.root / 'restricted.sqlite', workspace_root=allowed)
        run = q.create_run(go=True, credit_cap='1')
        with self.assertRaises(queue.GateError):
            q.enqueue(run, 'source', 'mock', {}, plan_path=self.plan,
                      provider='kie', known_cost='1')
        link = allowed / 'link'; link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(queue.GateError):
            q.enqueue(run, 'symlink', 'mock', {}, plan_path=link / 'plan.json',
                      provider='kie', known_cost='1')
        self.assertFalse((self.root / 'jobs.jsonl').exists())

    def test_unknown_and_cloud_providers_require_known_cap(self):
        for provider in ('modal', 'cloudrun', 'unrecognized-provider'):
            q = queue.Queue(self.root / (provider + '.sqlite'), provider_limits={provider: 1})
            run = q.create_run(go=True)
            with self.assertRaises(queue.BudgetError):
                q.enqueue(run, 'cloud', 'mock', {}, plan_path=self.plan,
                          provider=provider, known_cost='1')
            run = q.create_run(go=True, credit_cap='1')
            with self.assertRaises(queue.BudgetError):
                q.enqueue(run, 'cloud', 'mock', {}, plan_path=self.plan, provider=provider)

    def test_dry_run_never_claims_or_calls_provider(self):
        run = self.q.create_run()
        job = self.q.enqueue(run, 'dry', 'mock', {}, plan_path=self.plan, provider='ffmpeg')
        self.assertIsNone(self.q.claim('worker', run_id=run))
        self.assertEqual(self.q.get(job['id'])['state'], 'queued')
        with self.assertRaises(queue.AuthorizationError):
            self.q.prepare_submission(job['id'], 'made-up-token')

    def test_strict_unchanged_input_idempotency(self):
        first = self.add()
        self.assertEqual(self.add()['id'], first['id'])
        with self.assertRaises(queue.IdempotencyError): self.add(max_attempts=9)
        job = self.q.claim('w'); self.q.complete(job['id'], job['lease_token'], result={'deliverable': False})
        self.assertEqual(self.add()['state'], 'done')
        new_run = self.q.create_run(go=True)
        same = self.q.enqueue(new_run, 'ad', 'mock', {'manifest': 'test'}, plan_path=self.plan, provider='ffmpeg')
        self.assertEqual(same['id'], first['id'])
        self.assertNotEqual(self.add(inputs={'manifest': 'changed'})['id'], first['id'])
        self.plan.write_text('{"new": true}')
        self.assertNotEqual(self.add()['id'], first['id'])

    def test_terminal_failure_and_cancellation_cannot_be_resubmitted(self):
        job = self.add(); job = self.q.claim('w')
        self.q.fail(job['id'], job['lease_token'], error='permanent', retryable=False)
        self.assertEqual(self.add()['state'], 'failed')
        other = self.add(inputs={'different': True}); self.q.cancel(other['id'])
        self.assertEqual(self.add(inputs={'different': True})['state'], 'cancelled')
        self.assertIsNone(self.q.claim('w'))

    def test_atomic_claim_limit_across_connections(self):
        for n in range(20): self.add(inputs={'n': n})
        def claim(n):
            q = queue.Queue(self.db, clock=self.clock)
            return q.claim(str(n))
        with ThreadPoolExecutor(max_workers=20) as pool:
            claims = [v for v in pool.map(claim, range(20)) if v]
        self.assertEqual(len(claims), 2)
        self.assertEqual(len({j['id'] for j in claims}), 2)
        voice = self.add(provider='elevenlabs', inputs={'voice': 1}, known_cost='1')
        self.assertEqual(self.q.claim('voice')['id'], voice['id'])

    def test_restart_leases_backoff_and_stale_worker_fencing(self):
        job = self.add(max_attempts=2); lease = self.q.claim('old', lease_seconds=5)
        self.q.heartbeat(job['id'], lease['lease_token'], lease_seconds=10)
        self.clock.now += 9; self.assertEqual(self.q.recover_expired(), 0)
        self.clock.now += 2
        q = queue.Queue(self.db, clock=self.clock, backoff_base=2)
        self.assertEqual(q.recover_expired(), 1)
        self.assertIsNone(q.claim('new'))
        with self.assertRaises(queue.LeaseError): q.complete(job['id'], lease['lease_token'])
        self.clock.now += 2; new = q.claim('new', lease_seconds=1)
        self.assertNotEqual(new['lease_token'], lease['lease_token'])
        self.clock.now += 2; q.recover_expired()
        self.assertEqual(q.get(job['id'])['state'], 'failed')

    def test_retry_backoff_and_bound(self):
        job = self.add(max_attempts=2); lease = self.q.claim('w')
        self.q.fail(job['id'], lease['lease_token'], error='temporary', retryable=True)
        self.assertIsNone(self.q.claim('w'))
        self.clock.now += 2; lease = self.q.claim('w')
        self.q.fail(job['id'], lease['lease_token'], error='again', retryable=True)
        self.assertEqual(self.q.get(job['id'])['state'], 'failed')

    def test_locked_and_changed_plans_fail_closed(self):
        self.plan.write_text('{"locked":true}')
        with self.assertRaises(queue.LockedError): self.add()
        self.plan.write_text('{}'); job = self.add()
        self.plan.write_text('{"locked":true}')
        self.assertIsNone(self.q.claim('w'))
        self.assertEqual(self.q.get(job['id'])['state'], 'failed')
        self.assertEqual(json.loads(self.plan.read_text()), {'locked': True})
        self.plan.write_text('{}'); job = self.add(inputs={'n':2}); lease = self.q.claim('w')
        self.plan.write_text('{"different":true}')
        with self.assertRaises(queue.GateError): self.q.complete(job['id'], lease['lease_token'])

    def test_frames_approval_is_required_and_bound_to_revision(self):
        revision = 'a' * 64
        frames = self.add(stage='frames', revision=revision)
        self.assertIsNone(self.q.claim('w'))
        self.q.record_gate('ad', revision, 'plan_review', passed=True, evidence='mock reviewer')
        lease = self.q.claim('w'); self.q.complete(lease['id'], lease['lease_token'])
        self.assertEqual(self.q.get(frames['id'])['state'], 'awaiting_approval')
        clips = self.add(stage='clips', revision=revision)
        self.assertIsNone(self.q.claim('w'))
        with self.assertRaises(queue.GateError):
            self.q.record_gate('ad', revision, 'frames_approved', passed=True, evidence='bypass')
        self.q.approve(frames['id'], owner='owner mock')
        self.assertEqual(self.q.claim('w')['id'], clips['id'])
        self.add(stage='clips', revision='b' * 64, inputs={'revision': 'new'})
        self.assertIsNone(self.q.claim('w'))

    def test_assembly_and_delivery_gates_cannot_be_disabled(self):
        revision = 'a' * 64
        job = self.add(stage='render', revision=revision)
        lease = self.q.claim('w')
        with self.assertRaises(queue.GateError): self.q.complete(job['id'], lease['lease_token'])
        self.q.record_gate('ad', revision, 'caption_sync', passed=True, evidence='mock PASS')
        self.q.complete(job['id'], lease['lease_token'], result={'deliverable':False})
        self.assertEqual(self.q.get(job['id'])['state'], 'awaiting_approval')
        delivery = self.add(stage='deliver', revision=revision, known_cost='0')
        self.assertIsNone(self.q.claim('w'))
        self.q.approve(job['id'], owner='owner mock')
        self.q.record_gate('ad', revision, 'preflight', passed=True, evidence='mock PASS')
        self.assertIsNone(self.q.claim('w'))
        self.q.record_gate('ad', revision, 'all_hooks_approved', passed=True, evidence='mock explicit owner confirmation')
        self.assertEqual(self.q.claim('w')['id'], delivery['id'])
        with self.assertRaises(queue.GateError): self.add(stage='all')

    def test_cap_unknown_cost_and_atomic_reservations(self):
        for cap, cost in ((None,'1'), ('1',None)):
            run = self.q.create_run(go=True, credit_cap=cap)
            with self.assertRaises(queue.BudgetError):
                self.q.enqueue(run, 'paid', 'mock', {}, plan_path=self.plan, provider='kie', known_cost=cost)
        run = self.q.create_run(go=True, credit_cap='1')
        for n in range(2):
            self.q.enqueue(run, f'paid-{n}', 'mock', {}, plan_path=self.plan, provider='kie', known_cost='1')
        leases = [self.q.claim('w', run_id=run) for _ in range(2)]
        self.q.prepare_submission(leases[0]['id'], leases[0]['lease_token'])
        with self.assertRaises(queue.BudgetError):
            self.q.prepare_submission(leases[1]['id'], leases[1]['lease_token'])
        self.assertEqual(self.q.run_status(run)['reserved'], '1')

    def test_paid_id_persisted_before_poll_and_restart(self):
        job = self.add(provider='kie', known_cost='1'); lease = self.q.claim('w', lease_seconds=2)
        self.q.prepare_submission(job['id'], lease['lease_token'])
        self.q.record_provider_job(job['id'], lease['lease_token'], 'remote-123')
        rows = [json.loads(x) for x in (self.root / 'jobs.jsonl').read_text().splitlines()]
        self.assertEqual(rows[-1]['taskId'], 'remote-123')
        self.assertEqual(rows[-1]['key'], 'cloud:' + job['id'])
        self.clock.now += 3; self.q.recover_expired(); self.clock.now += 2
        q = queue.Queue(self.db, clock=self.clock)
        lease = q.claim('new')
        self.assertEqual(q.poll_ready(job['id'], lease['lease_token']), 'remote-123')
        with self.assertRaises(queue.SubmissionAmbiguous):
            q.prepare_submission(job['id'], lease['lease_token'])
        self.assertEqual(q.run_status(self.run)['reserved'], '1')

    def test_submission_crash_without_id_never_auto_resubmits(self):
        job = self.add(provider='kie', known_cost='1'); lease = self.q.claim('w', lease_seconds=1)
        self.q.prepare_submission(job['id'], lease['lease_token'])
        self.clock.now += 2; self.q.recover_expired()
        self.assertEqual(self.q.get(job['id'])['state'], 'failed')
        self.assertTrue(self.q.get(job['id'])['ambiguous'])
        self.assertIsNone(self.q.claim('w'))
        self.assertEqual(self.add(provider='kie', known_cost='1')['id'], job['id'])
        self.q.reconcile(job['id'], 'found-by-owner', owner='explicit owner mock')
        lease = self.q.claim('reconcile')
        self.assertEqual(self.q.poll_ready(job['id'], lease['lease_token']), 'found-by-owner')

    def test_journal_failure_prevents_poll_and_can_replay(self):
        job = self.add(provider='kie', known_cost='1'); lease = self.q.claim('w')
        self.q.prepare_submission(job['id'], lease['lease_token'])
        with patch.object(self.q, 'flush_journal', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.q.record_provider_job(job['id'], lease['lease_token'], 'remote')
            with self.assertRaises(OSError): self.q.poll_ready(job['id'], lease['lease_token'])
        self.assertEqual(self.q.get(job['id'])['provider_job_id'], 'remote')
        self.q.flush_journal(job['id']); self.q.flush_journal(job['id'])
        self.assertEqual(len((self.root / 'jobs.jsonl').read_text().splitlines()), 1)

    def test_stale_worker_cannot_record_id_or_poll(self):
        job = self.add(provider='kie', known_cost='1'); lease = self.q.claim('w', lease_seconds=1)
        self.q.prepare_submission(job['id'], lease['lease_token'])
        self.clock.now += 2
        with self.assertRaises(queue.LeaseError): self.q.record_provider_job(job['id'], lease['lease_token'], 'late')
        with self.assertRaises(queue.LeaseError): self.q.poll_ready(job['id'], lease['lease_token'])

    def test_twenty_parallel_ads_seeded_poll_failures_submit_once(self):
        q = queue.Queue(self.root / 'parallel.sqlite', provider_limits={'kie': 4},
                        backoff_base=0.001, backoff_max=0.01)
        run = q.create_run(go=True, credit_cap='20')
        jobs = [q.enqueue(run, f'ad-{n}', 'mock', {'n':n}, plan_path=self.plan,
                          provider='kie', known_cost='1', max_attempts=5) for n in range(20)]
        rng = random.Random(5415)
        failures = {j['id']: rng.randrange(3) for j in jobs}
        self.assertGreater(sum(failures.values()), 0)
        class MockProvider:
            def __init__(self):
                self.lock = threading.Lock(); self.submits = {}; self.active = 0; self.peak = 0; self.overlap = threading.Event()
            def submit(self, job):
                with self.lock:
                    self.submits[job['id']] = self.submits.get(job['id'], 0) + 1
                return 'remote-' + job['id']
            def poll(self, job, provider_id):
                with self.lock:
                    self.active += 1; self.peak = max(self.active, self.peak)
                    if self.active >= 2: self.overlap.set()
                try:
                    # Hold the first poll until another worker enters: prove
                    # overlap without relying on a 2ms scheduling accident.
                    if not self.overlap.wait(timeout=3): raise AssertionError('Parallel poll never entered')
                    records = [json.loads(x) for x in (self_outer.root/'jobs.jsonl').read_text().splitlines()]
                    assert any(x.get('taskId') == provider_id for x in records)
                    with self.lock:
                        if failures[job['id']]:
                            failures[job['id']] -= 1
                            raise RuntimeError('seeded temporary polling error')
                    return {'status':'done', 'result':{'deliverable':False}}
                finally:
                    with self.lock: self.active -= 1
        self_outer = self; provider = MockProvider()
        def worker(n):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if all(q.get(j['id'])['state'] == 'done' for j in jobs): return
                if q.run_once({'kie': provider}, worker=f'w{n}', run_id=run) is None:
                    time.sleep(0.002)
            raise AssertionError('queue did not drain')
        with ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(worker, range(20)))
        self.assertEqual(len(provider.submits), 20)
        self.assertEqual(set(provider.submits.values()), {1})
        self.assertGreater(provider.peak, 1)
        self.assertLessEqual(provider.peak, 4)
        self.assertEqual(q.run_status(run)['reserved'], '20')


if __name__ == '__main__': unittest.main()
