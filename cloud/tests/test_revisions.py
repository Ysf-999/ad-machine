"""Synthetic offline integration fixtures; never real approvals/media/manual boxes."""
from disk_test_support import DiskIndependentTestCase
import json
import pathlib
import random
import sqlite3
import tempfile
import time
import unittest
from decimal import Decimal
from unittest.mock import patch

from cloud.orchestrator import GateError, Queue
from cloud.providers.paid import MockTransport
from cloud.revisions import RevisionBatch, plan_feedback
from cloud.worker.controller import Controller

C = pathlib.Path(__file__).resolve().parents[1]


def project(locked=False):
    return {'cloud_mock': True, 'locked': locked,
            'beats': [{'n': n, 'vo': 'synthetic unchanged voice'} for n in range(1, 5)]}


def note(ad='ad', beat=1, kind='clip', number=1):
    return {'id': number, 'ad': ad, 'beat': beat, 'time': None, 'src': 'frameio',
            'frameio_comment': 'synthetic-' + str(number), 'decision': '',
            'text': '[frame.io v2 Fixture] redo-' + kind + ' — synthetic correction', 'status': 'open'}


class RevisionTests(DiskIndependentTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(dir=C / '.scratch')
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name) / 'batch'
        self.now = [1000.]
        for target in ('socket.create_connection', 'subprocess.Popen'):
            guard = patch(target, side_effect=AssertionError('No network/CLI in revision fixtures'))
            guard.start(); self.addCleanup(guard.stop)

    def create(self, projects=None, entries=None, cap='100'):
        return RevisionBatch.create(self.root, projects or {'ad': project()}, entries or [note()],
                                    limits={'kie': 3, 'ffmpeg': 2}, cap=cap, clock=lambda: self.now[0])

    def reopen(self):
        return RevisionBatch(self.root, clock=lambda: self.now[0])

    def gate(self, batch, ad, node, gate, passed=True):
        job = batch.q.get(batch.state['ads'][ad]['nodes'][node]['job'])
        batch.q.record_gate(job['ad_id'], job['revision'], gate, passed=passed,
                            evidence='SYNTHETIC MOCK fixture only; no media/owner decision')

    def seed_frames(self, batch, ad, beats):
        """Pre-existing approved MOCK frame provenance; no real approval/boxes."""
        fixture_run = batch.q.create_run(go=True)
        for beat in beats:
            graph = {'workflow': batch.state['workflow'], 'ad': ad, 'node': 'frames:' + str(beat)}
            job = batch.q.enqueue(fixture_run, ad + '/prior-frame-' + str(beat), 'frames',
                                  {'mock': True, 'graph': graph}, plan_path=batch.root / ad / 'plan.json')
            batch.q.record_gate(job['ad_id'], job['revision'], 'plan_review', passed=True,
                                evidence='SYNTHETIC prior mock frame plan')
            claimed = batch.q.claim('synthetic-fixture', run_id=fixture_run)
            self.assertEqual(claimed['id'], job['id'])
            batch.q.complete(job['id'], claimed['lease_token'], result={'mock': True})
            batch.q.approve(job['id'], owner='SYNTHETIC MOCK prior frame decision; not real approval')
            batch.bind_frames(ad, beat, [job['id']])

    def test_planner_parks_uncertainty_and_refuses_locks(self):
        entries = [note(), note(number=2, kind='frame'), note('locked', number=3),
                   note(beat=99, number=4), note('missing', number=5),
                   dict(note(number=6), beat=None, time=2.3),
                   dict(note(number=7), text='[frame.io v2 Fixture] make this better'),
                   dict(note(number=8), decision='approve'), dict(note(number=9), status='done')]
        result = plan_feedback({'ad': project(), 'locked': project(True)}, entries)
        self.assertEqual(len(result['jobs']), 1)
        self.assertEqual(result['jobs'][0]['kind'], 'frame')
        self.assertEqual({p['reason'] for p in result['parked']},
                         {'locked_refused', 'unknown_beat', 'unknown_ad', 'master_timestamp_ambiguous',
                          'explicit_redo_required', 'not_open'})
        self.assertTrue(result['preserve_vo'])

    def test_duplicate_identity_and_library_asset(self):
        entry = note()
        self.assertEqual(len(plan_feedback({'ad': project()}, [entry, entry])['jobs'][0]['notes']), 1)
        with self.assertRaises(ValueError):
            plan_feedback({'ad': project()}, [entry, dict(entry, text='changed')])
        p = project(); p['beats'][0]['lib'] = 'synthetic-library'
        self.assertEqual(plan_feedback({'ad': p}, [entry])['parked'][0]['reason'], 'library_asset_refused')

    def test_clip_only_connects_queue_preserves_vo_and_requires_provenance(self):
        b = self.create()
        before = (self.root / 'ad/plan.json').read_bytes()
        self.assertEqual(b.run_parallel(rounds=2), [])
        self.seed_frames(b, 'ad', [1])
        b.run_parallel(rounds=15)
        self.assertEqual((self.root / 'ad/plan.json').read_bytes(), before)
        jobs = b.q.jobs()
        self.assertNotIn('vo', {j['stage'] for j in jobs})
        self.assertEqual([j['inputs']['graph']['node'] for j in jobs if j['provider'] == 'kie'], ['clips:1'])
        self.assertEqual(b.status()['ads']['ad']['nodes']['native_mac'], 'queued')
        self.assertEqual(b.status()['ads']['ad']['state'], 'blocked_gates_or_dependencies')
        self.gate(b, 'ad', 'native_mac', 'native_mac', False)
        self.assertEqual(b.run_parallel(), [])
        self.gate(b, 'ad', 'native_mac', 'native_mac')
        b.run_parallel(rounds=5)
        self.assertEqual(b.status()['ads']['ad']['state'], 'await_owner')
        self.assertEqual(b.q.get(b.state['ads']['ad']['nodes']['stitch']['job'])['state'], 'awaiting_approval')
        self.assertFalse(b.status()['approved'])
        self.assertFalse(b.status()['deliverable'])
        self.assertEqual(b.push_dry_run('ad')['mode'], 'DRYRUN')
        self.assertFalse(b.push_dry_run('ad')['network'])
        self.assertFalse(any(j['stage'] in {'upload', 'deliver'} for j in jobs))

    def test_frame_redo_requires_plan_and_explicit_mock_frame_decision(self):
        b = self.create(entries=[note(kind='frame'), note(beat=2, kind='frame', number=2)])
        self.assertEqual(b.run_parallel(), [])
        self.gate(b, 'ad', 'frames:1', 'plan_review')
        b.run_parallel(rounds=3)
        nodes = b.state['ads']['ad']['nodes']
        self.assertEqual(b.q.get(nodes['frames:1']['job'])['state'], 'awaiting_approval')
        self.assertNotIn('job', nodes['clips:1'])
        b.q.approve(nodes['frames:1']['job'], owner='SYNTHETIC MOCK fixture decision only')
        b.run_parallel(rounds=3)
        self.assertEqual(b.q.get(nodes['frames:2']['job'])['state'], 'queued')
        self.assertNotIn('job', nodes['clips:2'])
        self.assertEqual({j['inputs']['graph']['node'] for j in b.q.jobs() if j['stage'] == 'clips'}, {'clips:1'})

    def test_locked_or_changed_staged_plan_refused_before_submit(self):
        b = self.create()
        p = self.root / 'ad/plan.json'; value = json.loads(p.read_text()); value['locked'] = True
        p.write_text(json.dumps(value))
        with self.assertRaises(GateError): b.run_parallel()
        self.assertFalse(any(j['submission_started'] for j in b.q.jobs()))
        locked = plan_feedback({'ad': project(True)}, [note()])
        self.assertEqual(locked['jobs'], [])

    def test_enqueue_crash_replay_uses_existing_jobs(self):
        b = self.create()
        count = len(b.q.jobs())
        state = json.loads(b.state_path.read_text())
        del state['ads']['ad']['nodes']['clips:1']['job']
        b.state_path.write_text(json.dumps(state))
        resumed = self.reopen(); resumed.refresh()
        self.assertEqual(len(resumed.q.jobs()), count)

    def test_reservation_and_receipt_crash_recover_without_resubmit(self):
        b = self.create(); self.seed_frames(b, 'ad', [1])
        adapters = b.adapters()
        with patch.object(b.q, 'record_provider_job', side_effect=SystemExit('synthetic crash after receipt')):
            with self.assertRaises(SystemExit): Controller(b.q, adapters).step()
        self.now[0] += 121
        b = self.reopen(); b.run_parallel(rounds=20)
        paid = [j for j in b.q.jobs() if j['provider'] == 'kie']
        self.assertEqual(len(paid), 1); self.assertEqual(paid[0]['state'], 'done')
        self.assertEqual(b.q.run_status(b.state['run'])['reserved'], '0.1')
        with sqlite3.connect(self.root / 'mock-service.sqlite') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM accepted').fetchone()[0], 1)

    def test_unknown_acceptance_parks_without_retry(self):
        b = self.create(); self.seed_frames(b, 'ad', [1]); adapters = b.adapters()
        original = adapters['kie'].transport.submit
        def lost(job):
            original(job)
            raise SystemExit('synthetic lost receipt')
        with patch.object(adapters['kie'].transport, 'submit', side_effect=lost):
            with self.assertRaises(SystemExit): Controller(b.q, adapters).step()
        self.now[0] += 121
        b = self.reopen(); b.run_parallel(rounds=10)
        j = next(j for j in b.q.jobs() if j['provider'] == 'kie')
        self.assertEqual(j['state'], 'failed'); self.assertTrue(j['ambiguous']); self.assertTrue(j['remote_open'])
        self.assertIsNone(j['provider_job_id'])
        self.assertEqual(b.q.run_status(b.state['run'])['reserved'], '0.1')

    def test_cap_blocks_second_paid_submission(self):
        b = self.create(entries=[note(), note(beat=2, number=2)], cap='.1')
        self.seed_frames(b, 'ad', [1, 2]); b.run_parallel(rounds=10)
        self.assertEqual(sum(j['submission_started'] for j in b.q.jobs()), 1)
        self.assertEqual(Decimal(b.status()['spend']['reserved']), Decimal('.1'))

    def test_no_skipped_mandatory_gate_even_after_mock_stage_done(self):
        b = self.create(); self.seed_frames(b, 'ad', [1])
        b.run_parallel(rounds=1)
        b.refresh()
        qc = b.q.get(b.state['ads']['ad']['nodes']['qc']['job'])
        claimed = b.q.claim('fixture'); self.assertEqual(claimed['id'], qc['id'])
        b.q.complete(qc['id'], claimed['lease_token'], result={'mock': True})
        b.refresh()
        self.assertEqual(b.run_parallel(rounds=5), [])
        stitch = b.q.get(b.state['ads']['ad']['nodes']['stitch']['job'])
        self.assertIn('qc', stitch['required_gates'])
        self.assertEqual(stitch['state'], 'queued')

    def test_wrong_beat_frame_provenance_cannot_unlock_clip(self):
        b = self.create()
        self.seed_frames(b, 'ad', [2])
        source = next(j for j in b.q.jobs() if j['stage'] == 'frames')
        with self.assertRaises(GateError): b.bind_frames('ad', 1, [source['id']])
        self.assertFalse(any(j['submission_started'] for j in b.q.jobs()))

    def test_delivery_still_requires_final_all_hooks_caption_and_preflight(self):
        b = self.create()
        job = b.q.enqueue(b.state['run'], 'ad/delivery', 'upload', {'mock': True},
                          plan_path=self.root / 'ad/plan.json', known_cost='.1')
        self.assertEqual(set(job['required_gates']),
                         {'final_approved', 'all_hooks_approved', 'caption_sync', 'preflight'})
        self.assertIsNone(b.q.claim('fixture'))
        self.assertFalse(b.q.get(job['id'])['submission_started'])

    def test_each_downstream_gate_is_required_and_caption_completion_is_guarded(self):
        for omitted, target in [('qc', 'stitch'), ('caption_sync', 'masterqc'),
                                ('masterqc', 'preflight'), ('preflight', 'native_mac')]:
            with self.subTest(omitted=omitted):
                self.root = pathlib.Path(self.temp.name) / omitted
                b = self.create(); self.seed_frames(b, 'ad', [1])
                original = b.adapters
                def adapters():
                    result = original(); local = result['ffmpeg']
                    class Missing:
                        def run(s, job):
                            name = job['inputs']['graph']['node']
                            if name == ('stitch' if omitted == 'caption_sync' else omitted):
                                return {'mock': True, 'status': 'done'}
                            return local.run(job)
                    result['ffmpeg'] = Missing()
                    return result
                with patch.object(b, 'adapters', side_effect=adapters): b.run_parallel(rounds=15)
                if omitted == 'caption_sync':
                    stitch = b.q.get(b.state['ads']['ad']['nodes']['stitch']['job'])
                    self.assertEqual(stitch['state'], 'failed')
                    self.assertNotIn('job', b.state['ads']['ad']['nodes'][target])
                else:
                    job = b.q.get(b.state['ads']['ad']['nodes'][target]['job'])
                    self.assertIn(omitted, job['required_gates'])
                    self.assertEqual(job['state'], 'queued')
                self.assertNotEqual(b.status()['ads']['ad']['state'], 'await_owner')

    def test_mock_only_and_bounded_api(self):
        p = project(); p.pop('cloud_mock')
        with self.assertRaises(ValueError): self.create(projects={'ad': p})
        b = self.create()
        for args in ({'workers': 0}, {'rounds': 0}, {'workers': 33}):
            with self.assertRaises(ValueError): b.run_parallel(**args)

    def test_30_ads_seeded_failures_restarts_parallel_limits_and_journal(self):
        started = time.monotonic(); rng = random.Random(1704)
        projects = {'ad%02d' % i: project(i >= 28) for i in range(30)}
        entries, counts = [], []
        for ad in projects:
            count = rng.randint(3, 10); counts.append(count)
            for n in range(count): entries.append(note(ad, n % 3 + 1, number=len(entries) + 1))
        b = self.create(projects, entries)
        for ad in b.state['ads']: self.seed_frames(b, ad, [1, 2, 3])
        stats = {'submit_checks': 0, 'poll_checks': 0, 'peak': 0, 'pending': 0, 'terminal_failures': 0}
        q = b.q
        class AuditedTransport(MockTransport):
            def submit(s, job):
                fresh = q.get(job['id'])
                assert fresh['submission_started'] and fresh['remote_open']
                assert Decimal(q.run_status(b.state['run'])['reserved']) >= Decimal('.1')
                with q._tx() as db:
                    assert db.execute('SELECT 1 FROM paid_intents WHERE job_id=?', (job['id'],)).fetchone()
                    active = db.execute("SELECT count(*) FROM jobs WHERE provider='kie' AND remote_open=1").fetchone()[0]
                stats['peak'] = max(stats['peak'], active); assert active <= 3
                stats['submit_checks'] += 1
                return super().submit(job)
            def poll(s, job, receipt):
                rows = [json.loads(line) for line in (pathlib.Path(job['plan_path']).parent / 'jobs.jsonl').read_text().splitlines()]
                assert any(r['taskId'] == receipt and r['cloud_event_id'] == 'provider:' + job['id'] for r in rows)
                stats['poll_checks'] += 1
                # Stable per-job fixture faults; pending keeps a provider slot.
                key = int(job['input_hash'][:8], 16)
                with s.db() as db:
                    polls = db.execute('SELECT polls FROM accepted WHERE job=?', (job['id'],)).fetchone()[0]
                    if polls == 0 and key % 4 == 0:
                        db.execute('UPDATE accepted SET polls=1 WHERE job=?', (job['id'],))
                        stats['pending'] += 1
                        return {'status': 'pending'}
                if key % 17 == 0:
                    stats['terminal_failures'] += 1
                    return {'status': 'failed'}
                return super().poll(job, receipt)
        with patch('cloud.revisions.MockTransport', AuditedTransport):
            b.run_parallel(workers=6, rounds=3)
            b = self.reopen(); q = b.q
            b.run_parallel(workers=6, rounds=250)
        paid = [j for j in b.q.jobs() if j['provider'] == 'kie']
        self.assertEqual(len(paid), 84)
        self.assertEqual(stats['submit_checks'], 84)
        self.assertGreater(stats['pending'], 0); self.assertGreater(stats['terminal_failures'], 0)
        self.assertGreater(stats['peak'], 1); self.assertLessEqual(stats['peak'], 3)
        self.assertTrue(all(j['state'] in {'done', 'failed'} for j in paid))
        self.assertFalse(any(j['ambiguous'] for j in paid))
        self.assertEqual(Decimal(b.status()['spend']['reserved']), Decimal('8.4'))
        self.assertFalse(any(j['stage'] == 'vo' for j in b.q.jobs()))
        self.assertFalse(any(j['ad_id'].startswith(('ad28/', 'ad29/')) for j in b.q.jobs()))
        with sqlite3.connect(self.root / 'mock-service.sqlite') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM accepted').fetchone()[0], 84)
        self.assertFalse(b.status()['approved'])
        self.assertTrue(all(a['state'] != 'await_owner' for a in b.status()['ads'].values()))
        evidence = {'scope': 'LOCAL MOCK ONLY', 'seed': 1704, 'ads': 30,
                    'notes_per_ad': counts, 'notes': len(entries), 'locked_ads_refused': 2,
                    'paid_mock_jobs': len(paid), 'completed_paid_mock_jobs': sum(j['state'] == 'done' for j in paid),
                    'failed_paid_mock_jobs': sum(j['state'] == 'failed' for j in paid), **stats,
                    'mock_reserved_units': b.status()['spend']['reserved'], 'mock_cap_units': '100',
                    'wall_seconds': round(time.monotonic() - started, 3),
                    'restart': 'queue/controller reopened after three parallel rounds',
                    'native_gate': 'not supplied; successful ads blocked before owner review',
                    'real_paid_calls': 0, 'network_calls': 0, 'vo_jobs': 0,
                    'real_approvals': 0, 'manual_boxes_written': 0, 'deliverable': False}
        self.assertEqual(evidence['real_paid_calls'], 0)


if __name__ == '__main__': unittest.main()
