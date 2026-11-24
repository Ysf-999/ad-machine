"""Offline contract tests. All fixtures and output live in cloud/.scratch."""
from disk_test_support import DiskIndependentTestCase

import copy
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from cloud import approval as a


KEY = b'offline-test-signing-key-32-bytes!!'


class ApprovalTests(DiskIndependentTestCase):
    def setUp(self):
        # Owner-authorized synthetic positive checklists live only in memory.
        self.synthetic_checklists = {}
        read_text = Path.read_text
        fixture_map = self.synthetic_checklists
        def fixture_read(path, *args, **kwargs):
            return fixture_map[path] if path in fixture_map else read_text(path, *args, **kwargs)
        patcher = patch.object(Path, 'read_text', fixture_read)
        patcher.start(); self.addCleanup(patcher.stop)
        digest = a._digest
        def fixture_digest(path):
            value = fixture_map.get(path)
            return hashlib.sha256(value.encode()).hexdigest() if value is not None else digest(path)
        digest_patcher = patch.object(a, '_digest', fixture_digest)
        digest_patcher.start(); self.addCleanup(digest_patcher.stop)
        a.SCRATCH.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='approval-test-', dir=a.SCRATCH)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.write(self.source, 'plan.json', json.dumps({'ad': 'test', 'beats': [
            {'n': 1, 'visual': 'first', 'vo': 'one'},
            {'n': 2, 'visual': 'second', 'vo': 'two'}], 'approved_beats': [1, 2]}))
        self.write(self.source, 'jobs.jsonl', '{"existing":"job"}\n')
        self.write(self.source, 'FRAMES/scene_01.png', b'frame one')
        self.write(self.source, 'FRAMES/scene_02.png', b'frame two')
        self.write(self.source, 'CLIPS/clip_01.mp4', b'clip one')
        self.write(self.source, 'CLIPS/clip_02.mp4', b'clip two')
        self.write(self.source, 'VO/alignment.json', '{}')
        self.write(self.source, 'MASTER.mp4', b'fake master, not decoded')
        self.write(self.source, 'REVIEW.html', '<!doctype html><a href="MASTER.mp4">Master</a>'
                   '<img src="FRAMES/scene_01.png"><img src="FRAMES/scene_02.png">'
                   '<video src="CLIPS/clip_01.mp4"></video><video src="CLIPS/clip_02.mp4"></video>')
        self.original = self.tree(self.source)
        self.project = a.stage_project(self.source, self.files(self.source))
        self.addCleanup(__import__('shutil').rmtree, self.project)

    @staticmethod
    def write(root, name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else value.encode())

    @staticmethod
    def files(root):
        return sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file())

    def tree(self, root):
        return {f: (root / f).read_bytes() for f in self.files(root)}

    def plan(self, project=None):
        return json.loads(((project or self.project) / 'plan.json').read_text())

    def decision(self, action='approve', phase='frames', beat='all', note='', project=None, **kw):
        return a.sign_decision(project or self.project, action, phase, beat, note, key=KEY, **kw)

    def apply(self, action='approve', phase='frames', beat='all', note='', project=None, **kw):
        project = project or self.project
        decision = self.decision(action, phase, beat, note, project=project, **kw)
        return a.apply_decision(project, decision, key=KEY)

    def checks(self, project=None):
        project = project or self.project
        reports = {
            'qc': ('QC/qc_report.json', json.dumps([
                {'item': name, 'verdict': 'PASS'} for name in
                ('scene_01.png', 'scene_02.png', 'clip_01.mp4', 'clip_02.mp4')])),
            'masterqc': ('QC/master_qc.md', 'VERDICT: SHIP\nSCORE: 9/10'),
            'caption_sync': ('QC/caption_sync.txt', 'CAPTION SYNC PASS: 2/2 cards matched'),
            'av_check': ('QC/av_check.txt', 'PASS: sound and picture in sync'),
            'preflight': ('PREFLIGHT.md', 'master: MASTER.mp4\nfingerprint: ' +
                          a.preflight_fingerprint(project / 'MASTER.mp4') +
                          '\n- PASS format 1080x1920\n- PASS av_check\n- PASS T17 CAPTION SYNC PASS\n'
                          '- [x] Taste\n- [n/a] Earlier revision\n'),
        }
        render_hash = a.render_hash(project)
        for name, (path, text) in reports.items():
            if name == 'preflight':
                self.synthetic_checklists[project / path] = text
                # Keep actual scratch checklist unanswered; only the validator's
                # read in this explicitly synthetic unit fixture sees completion.
                self.write(project, path, text.replace('- [x]', '- [ ]').replace('- [n/a]', '- [ ]'))
            else:
                self.write(project, path, text)
            a.record_check(project, name, path, expected_input_hash=render_hash, returncode=0)

    def final_approve(self, project=None):
        self.apply(project=project)
        self.checks(project)
        self.apply(phase='final', project=project)

    def test_staging_and_gate_do_not_mutate_source(self):
        self.assertEqual(self.plan()['approved_beats'], [])
        self.assertEqual(a.status(self.project)['frames'], 'awaiting_approval')
        with self.assertRaises(a.ApprovalError):
            a.require_stage(self.project, 'clips')
        self.apply(beat=1)
        with self.assertRaises(a.ApprovalError):
            a.require_stage(self.project, 'clips')
        self.apply(beat=2)
        a.require_stage(self.project, 'clips')
        self.assertEqual(self.plan()['approved_beats'], [1, 2])
        self.assertEqual(self.tree(self.source), self.original)
        self.assertEqual((self.project / 'jobs.jsonl').read_bytes(), self.original['jobs.jsonl'])

    def test_revision_changes_only_affected_beat_and_queues_no_execution(self):
        self.final_approve()
        before = self.plan()
        self.apply('revise', 'final', 2, 'Keep the voice; change the movement')
        after = self.plan()
        self.assertEqual(before['beats'][0], after['beats'][0])
        self.assertEqual(after['beats'][1]['clip_note'], 'Keep the voice; change the movement')
        self.assertEqual(after['approved_beats'], [1])
        state = after[a.STATE_KEY]
        self.assertEqual(set(state['pending_redo']), {'2'})
        self.assertEqual(state['pending_redo']['2']['argv'],
                         ['ad.py', '.', 'redo', '2', 'clip', 'Keep the voice; change the movement'])
        self.assertIn('beat 2: redo-clip — Keep the voice;', state['notes'][-1])
        self.assertFalse(a.status(self.project)['approved'])
        a.require_stage(self.project, 'clips')
        with self.assertRaises(a.ApprovalError):
            a.complete_redo(self.project, 2)
        self.write(self.project, 'CLIPS/clip_02_v2.mp4', b'changed clip')
        a.complete_redo(self.project, 2)
        with self.assertRaises(a.ApprovalError):
            a.require_stage(self.project, 'final')  # stale QC cannot authorize new content
        self.assertEqual(self.tree(self.source), self.original)

    def test_frame_revision_retains_other_frame_approval(self):
        self.apply()
        self.apply('revise', 'frames', 1, 'Only correct the strand')
        self.assertEqual(self.plan()['approved_beats'], [2])
        with self.assertRaises(a.ApprovalError):
            a.require_stage(self.project, 'clips')
        self.write(self.project, 'FRAMES/scene_01_v2.png', b'changed frame')
        a.complete_redo(self.project, 1)
        self.assertEqual(self.plan()[a.STATE_KEY]['pending_redo']['1']['kind'], 'clip')
        self.apply(beat=1)
        a.require_stage(self.project, 'clips')
        self.write(self.project, 'CLIPS/clip_01_v2.mp4', b'clip from the new frame')
        a.complete_redo(self.project, 1)
        self.assertEqual(self.plan()['approved_beats'], [1, 2])

    def test_copying_old_media_to_new_version_is_not_a_completed_redo(self):
        self.apply()
        self.apply('revise', 'frames', 1, 'Change this frame')
        self.write(self.project, 'FRAMES/scene_01_v2.png', b'frame one')
        with self.assertRaises(a.ApprovalError):
            a.complete_redo(self.project, 1)

    def test_offline_operations_never_open_sockets_or_run_tools(self):
        with patch('socket.socket', side_effect=AssertionError('network forbidden')), \
                patch('subprocess.run', side_effect=AssertionError('tool execution forbidden')):
            self.final_approve()
            a.publish_review(self.project)

    def test_signature_staleness_replay_expiry_and_workspace_binding(self):
        d = self.decision()
        bad = copy.deepcopy(d); bad['payload']['note'] = 'tampered'
        for value in (bad, self.decision(expires_in=-1)):
            with self.assertRaises(a.ApprovalError):
                a.apply_decision(self.project, value, key=KEY)
        other = a.stage_project(self.source, self.files(self.source))
        self.addCleanup(__import__('shutil').rmtree, other)
        with self.assertRaises(a.ApprovalError):
            a.apply_decision(other, d, key=KEY)
        self.write(self.project, 'FRAMES/scene_01.png', b'new input')
        with self.assertRaises(a.ApprovalError):
            a.apply_decision(self.project, d, key=KEY)
        d = self.decision()
        a.apply_decision(self.project, d, key=KEY)
        with self.assertRaises(a.ApprovalError):
            a.apply_decision(self.project, d, key=KEY)
        self.write(self.project, 'VO/alignment.json', '{"changed":true}')
        with self.assertRaises(a.ApprovalError):
            a.require_stage(self.project, 'clips')

    def test_lock_source_and_staged_and_unstaged_paths_refused(self):
        for target in (self.source, self.project):
            plan = self.plan(target); plan['locked'] = True
            self.write(target, 'plan.json', json.dumps(plan))
            with self.assertRaises(a.ApprovalError):
                self.decision()
            plan['locked'] = False
            self.write(target, 'plan.json', json.dumps(plan))
        with self.assertRaises(a.ApprovalError):
            a.stage_project(self.source, ['plan.json', '../escape'])
        with self.assertRaises(a.ApprovalError):
            a.sign_decision(self.source, 'approve', 'frames', 'all', '', key=KEY)
        self.write(self.source, '.env', 'NOT_A_REAL_SECRET')
        with self.assertRaises(a.ApprovalError):
            a.stage_project(self.source, self.files(self.source))

    def test_symlinks_and_hardlinks_refused_without_target_writes(self):
        target = self.root / 'outside'; target.write_text('unchanged')
        (self.source / 'escape').symlink_to(target)
        with self.assertRaises(a.ApprovalError):
            a.stage_project(self.source, self.files(self.source))
        (self.project / 'plan.json').unlink()
        os.link(self.source / 'plan.json', self.project / 'plan.json')
        with self.assertRaises(a.ApprovalError):
            self.apply()
        self.assertEqual(target.read_text(), 'unchanged')

    def test_final_requires_current_successful_prerequisites_and_explicit_confirmation(self):
        self.apply()
        with self.assertRaises(a.ApprovalError):
            self.apply(phase='final')
        self.checks()
        a.require_stage(self.project, 'final')
        self.apply(phase='final', beat=1)
        self.apply(phase='final', beat=2)
        self.assertFalse(a.status(self.project)['approved'])
        self.apply(phase='final')
        self.assertTrue(a.status(self.project)['approved'])
        self.write(self.project, 'MASTER.mp4', b'changed final')
        self.assertFalse(a.status(self.project)['approved'])
        with self.assertRaises(a.ApprovalError):
            a.require_stage(self.project, 'final')

    def test_failed_skipped_stale_reports_and_incomplete_preflight_fail_closed(self):
        self.apply()
        render_hash = a.render_hash(self.project)
        for name, text in [('caption_sync', 'CAPTION SYNC FAIL'),
                           ('caption_sync', 'CAPTION SYNC PASS\nSKIPPED'),
                           ('masterqc', 'VERDICT: FIX'), ('qc', '[]'),
                           ('preflight', '- PASS format 1080x1920\n- [ ] Taste')]:
            path = 'QC/bad.txt'
            self.write(self.project, path, text)
            with self.assertRaises(a.ApprovalError, msg=name + text):
                a.record_check(self.project, name, path, expected_input_hash=render_hash, returncode=0)
        self.write(self.project, 'QC/good.txt', 'CAPTION SYNC PASS')
        for expected, rc in [(render_hash, 1), ('0' * 64, 0)]:
            with self.assertRaises(a.ApprovalError):
                a.record_check(self.project, 'caption_sync', 'QC/good.txt',
                               expected_input_hash=expected, returncode=rc)
        self.checks()
        self.write(self.project, 'QC/caption_sync.txt', 'CAPTION SYNC FAIL')
        with self.assertRaises(a.ApprovalError):
            a.require_stage(self.project, 'final')

    def test_batch_approved_only_after_explicit_base_and_every_hook(self):
        hooks = [a.stage_project(self.source, self.files(self.source)) for _ in range(3)]
        for h in hooks:
            self.addCleanup(__import__('shutil').rmtree, h)
        self.final_approve()
        for h in hooks[:2]:
            self.final_approve(h)
        self.assertFalse(a.batch_status(self.project, hooks)['approved'])
        self.final_approve(hooks[2])
        self.assertTrue(a.batch_status(self.project, hooks)['approved'])
        self.assertFalse(a.batch_status(self.project, hooks[:2])['approved'])
        self.write(hooks[0], 'MASTER.mp4', b'revised after batch approval')
        self.assertFalse(a.batch_status(self.project, hooks)['approved'])

    def test_review_bundle_is_content_addressed_and_relative(self):
        self.apply()
        bundle = a.publish_review(self.project)
        self.assertEqual(bundle['sha256'], hashlib.sha256(Path(bundle['path']).read_bytes()).hexdigest())
        self.assertEqual(bundle, a.publish_review(self.project))
        with tarfile.open(bundle['path']) as tf:
            self.assertEqual(tf.extractfile('REVIEW.html').read(), self.original['REVIEW.html'])
            self.assertIn('CLIPS/clip_01.mp4', tf.getnames())
            self.assertNotIn('plan.json', tf.getnames())
        board = a.publish_batch(self.project, [], expected_hooks=3)
        with tarfile.open(board['path']) as tf:
            page = tf.extractfile('index.html').read().decode()
            self.assertIn('ads/' + self.project.name + '/REVIEW.html', page)
            self.assertIn('Awaiting approval', page)
        class LocalDuck:
            def __init__(self, root):
                self.root = root
                self.calls = []
            def put(self, source, *, expected_sha256):
                self.calls.append((Path(source).read_bytes(), expected_sha256))
                return {'sha256': expected_sha256, 'size': Path(source).stat().st_size}
        backend = LocalDuck(self.root / 'objects')
        a.publish_review(self.project, storage=backend)
        self.assertEqual(len(backend.calls), 1)
        self.write(self.project, 'REVIEW.html', '<img src="https://example.invalid/remote">')
        with self.assertRaises(a.ApprovalError):
            a.publish_review(self.project)

    def test_existing_local_storage_contract(self):
        from cloud.storage import LocalStorage, ObjectRef
        backend = LocalStorage(self.root / 'local-objects')
        result = a.publish_review(self.project, storage=backend)
        downloaded = self.root / 'round-trip.tar'
        backend.get(ObjectRef(result['sha256'], result['size']), downloaded)
        self.assertEqual(downloaded.read_bytes(), Path(result['path']).read_bytes())

    def test_invalid_targets_notes_library_and_unknown_stage_refused(self):
        for args in [('approve', 'frames', 99, ''), ('approve', 'other', 1, ''),
                     ('revise', 'frames', 'all', 'change'), ('revise', 'frames', 1, ''),
                     ('revise', 'frames', 1, 'line\nbeat 2: approve')]:
            with self.assertRaises(a.ApprovalError):
                self.decision(*args)
        with self.assertRaises(a.ApprovalError):
            a.require_stage(self.project, 'vo')
        plan = self.plan(); plan['beats'][0]['lib'] = 'approved-library-asset'
        self.write(self.project, 'plan.json', json.dumps(plan))
        with self.assertRaises(a.ApprovalError):
            self.apply('revise', 'frames', 1, 'change')

    def test_concurrent_decisions_do_not_lose_beats(self):
        decisions = [self.decision(beat=n) for n in (1, 2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda d: a.apply_decision(self.project, d, key=KEY), decisions))
        self.assertEqual(self.plan()['approved_beats'], [1, 2])

    def test_cli_signed_file_workflow_without_network_or_process_execution(self):
        import sys
        env = dict(os.environ, CLOUD_APPROVAL_KEY=KEY.decode(), PYTHONDONTWRITEBYTECODE='1')
        decision = self.project / 'decision.json'
        commands = [
            ['approve', str(self.project), 'all', '--phase', 'frames', '--out', str(decision)],
            ['apply', str(self.project), str(decision)],
            ['gate', str(self.project), 'clips'],
        ]
        for args in commands:
            proc = subprocess.run([sys.executable, '-B', '-m', 'cloud.approval', *args],
                                  cwd=a.SCRATCH.parent.parent, env=env, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn(KEY.decode(), proc.stdout + proc.stderr)
        a.require_stage(self.project, 'clips')


if __name__ == '__main__':
    unittest.main()
