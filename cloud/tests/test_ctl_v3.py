"""Controller v3: a network error is never a crash, a crashed run is settled from what the
status board saw, a submit claims its ads first, bad redo notes and banned footage are refused before anything starts,
collect survives one bad ad, unsent Slack notes are kept, a half-saved project folder is recovered."""
import json
import os
import pathlib
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
from decimal import Decimal as D

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'cloud'), str(ROOT / 'tools')]
from cloud import ctl  # noqa: E402
from cloud.worker import ad_job, adjob_boot, pipeline as P  # noqa: E402
from cloud.worker.overnight_budget import Budget  # noqa: E402

_quiet_board = mock.patch.object(ctl, 'board_refresh', lambda *a, **k: None)   # no test writes the real board / usage cache


def setUpModule():
    _quiet_board.start()


def tearDownModule():
    _quiet_board.stop()


def fake_modal(board=None, get=None, spawn=None, board_error=None):
    """A stand-in for the modal package: only what ctl touches."""
    class Error(Exception): pass
    class TimeoutError_(Error): pass
    class FunctionTimeoutError(TimeoutError_): pass
    class OutputExpiredError(TimeoutError_): pass
    class NotFoundError(Error): pass
    exc = types.SimpleNamespace(ConnectionError=type('ConnectionError', (Error,), {}), ClientClosed=type('ClientClosed', (Error,), {}),
                                AuthError=type('AuthError', (Error,), {}), ServiceError=type('ServiceError', (Error,), {}),
                                InternalError=type('InternalError', (Error,), {}), ResourceExhaustedError=type('ResourceExhaustedError', (Error,), {}),
                                NotFoundError=NotFoundError, TimeoutError=TimeoutError_, FunctionTimeoutError=FunctionTimeoutError,
                                OutputExpiredError=OutputExpiredError)

    class Dict:
        @staticmethod
        def from_name(*a, **k):
            if board_error:
                raise board_error
            return types.SimpleNamespace(get=lambda key: (board or {}).get(key))

    class Call:
        def __init__(self, cid): self.object_id = cid
        def get(self, timeout=0):
            out = get() if callable(get) else get
            if isinstance(out, BaseException):
                raise out
            return out

    class FunctionCall:
        @staticmethod
        def from_id(cid): return Call(cid)

    class Function:
        @staticmethod
        def from_name(*a, **k):
            def do(payload):
                out = spawn(payload) if spawn else 'fc-1'
                if isinstance(out, BaseException):
                    raise out
                return Call(out)
            return types.SimpleNamespace(spawn=do)

    class Volume:
        @staticmethod
        def from_name(*a, **k): return object()
    return types.SimpleNamespace(exception=exc, Dict=Dict, FunctionCall=FunctionCall, Function=Function, Volume=Volume)


RUN = {'run': 'my-ad-ai-1795000000', 'ad': 'my-ad', 'recipe': 'ai', 'call': 'fc-1', 'submitted': time.time() - 300}


class StateTests(unittest.TestCase):
    def state(self, run=RUN, **kw):
        m = fake_modal(**kw)
        with mock.patch.dict(sys.modules, {'modal': m}):
            return ctl.state_of(run), m

    def test_no_connection_is_not_a_crash(self):
        running = {'state': 'running', 'steps': [{'seconds': 5.0}], 'current': {'kind': 'gen', 'stages': ['frames'], 'since': 1}}
        for kw in ({'board_error': OSError('network down')},                               # nothing reachable at all
                   {'board': {RUN['run']: running}, 'get': ConnectionError('reset')},      # board answered, the call lookup blipped
                   {'board': {}, 'get': ConnectionResetError('reset')}):
            st, _ = self.state(**kw)
            self.assertNotIn(st['state'], P.TERMINAL, kw)
            self.assertTrue(st.get('unreachable'), kw)
        st, m = self.state(board={RUN['run']: running}, get=None)
        m2 = fake_modal(board={RUN['run']: running})
        with mock.patch.dict(sys.modules, {'modal': m2}):
            m2.FunctionCall.from_id = lambda cid: types.SimpleNamespace(get=lambda timeout=0: (_ for _ in ()).throw(m2.exception.ServiceError('unavailable')))
            self.assertNotIn(ctl.state_of(RUN)['state'], P.TERMINAL)

    def test_real_crashes_are_terminal_and_a_running_call_is_not(self):
        m = fake_modal(board={})
        cases = [(m.exception.FunctionTimeoutError('t'), 'crashed'), (m.exception.OutputExpiredError('gone'), 'crashed'),
                 (ValueError('pipeline raised'), 'crashed'), (m.exception.NotFoundError('no such call'), 'crashed'),
                 (m.exception.TimeoutError('not ready'), 'queued'), (TimeoutError('not ready'), 'queued')]
        for error, want in cases:
            with mock.patch.dict(sys.modules, {'modal': m}):
                m.FunctionCall.from_id = lambda cid, error=error: types.SimpleNamespace(get=lambda timeout=0: (_ for _ in ()).throw(error))
                self.assertEqual(ctl.state_of(RUN)['state'], want, error)
        done = {'state': 'done', 'steps': []}
        st, _ = self.state(board={RUN['run']: done}, get=ValueError('never asked'))
        self.assertEqual(st, done)                                                         # a finished board state needs no call lookup
        old = {**RUN, 'submitted': time.time() - ctl.SHAPE['pipeline'][2] - 2000}
        st, _ = self.state(run=old, board={}, get=ConnectionError('still down'))
        self.assertEqual(st['state'], 'crashed')                                           # past the pipeline's own time limit

    def test_a_submit_that_never_reached_the_cloud(self):
        entry = {k: v for k, v in RUN.items() if k != 'call'}
        st, _ = self.state(run={**entry, 'pid': os.getpid(), 'submitted': time.time() - 900})
        self.assertEqual((st['state'], st.get('note')), ('queued', 'submit in progress'))  # its process is still alive
        st, _ = self.state(run={**entry, 'pid': 2 ** 22 + 12345, 'submitted': time.time() - 30})
        self.assertEqual(st['state'], 'queued')                                            # just started: give it two minutes
        st, _ = self.state(run={**entry, 'pid': 2 ** 22 + 12345, 'submitted': time.time() - 900})
        self.assertEqual((st['state'], st['never_started']), ('failed', True))
        running = {'state': 'running', 'steps': []}
        st, _ = self.state(run={**entry, 'pid': 2 ** 22 + 12345, 'submitted': time.time() - 900}, board={RUN['run']: running})
        self.assertEqual(st['state'], 'running')                                           # the cloud run exists: keep tracking it

    def test_settle_uses_what_the_board_saw(self):
        run = {'run': 'x-ai-1795000000', 'recipe': 'ai'}
        died = {'state': 'crashed', 'started': 1.0, 'steps': [{'seconds': 60.0}, {'seconds': 90.0}],
                'current': {'kind': 'gen', 'stages': ['frames'], 'since': 5}}
        got = ctl.settle(run, died)
        self.assertEqual([v for _, v, _ in got], ['DONE', 'DONE', 'FAILED', 'SKIPPED', 'SKIPPED', 'FAILED'])
        self.assertEqual(got[2][2], ctl.bound('gen'))
        between = ctl.settle(run, {'state': 'crashed', 'started': 1.0, 'steps': [{'seconds': 60.0}]})
        self.assertEqual([v for _, v, _ in between], ['DONE', 'SKIPPED', 'SKIPPED', 'SKIPPED', 'SKIPPED', 'FAILED'])
        never = ctl.settle(run, {'state': 'failed', 'steps': [], 'never_started': True})
        self.assertTrue(all((v, e) == ('SKIPPED', D(0)) for _, v, e in never))
        self.assertEqual(len(never), 6)

    def test_describe_says_when_modal_is_unreachable(self):
        self.assertIn('cannot reach Modal', ctl.describe(RUN, {'state': 'running', 'steps': [], 'unreachable': 'OSError'}))


class SubmitTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = pathlib.Path(self.td.name)
        (self.root / 'projects/my-ad').mkdir(parents=True)
        (self.root / 'projects/my-ad/plan.json').write_text('{}')
        self.state = self.root / 'cloud/controller'
        self.state.mkdir(parents=True)

    def submit(self, spawn=None, stage=None, runs_before=None):
        if runs_before:
            (self.state / 'runs.json').write_text(json.dumps(runs_before))
        budget = Budget(self.state / 'ledger.json', cap='5.00', stop='5.00', task='t')
        with mock.patch.multiple(ctl, ROOT=self.root, C=self.root / 'cloud', STATE=self.state, guard=lambda: None,
                                 plan_job=lambda spec, *a, **k: {'ad': spec['ad'], 'recipe': spec['recipe'], 'max_tasks': 0},
                                 build_snapshot=lambda folder=None: 'a' * 16, stage=stage or (lambda *a, **k: {}), ledger=lambda: budget), \
                mock.patch.dict(sys.modules, {'modal': fake_modal(spawn=spawn)}), mock.patch('builtins.print'):
            ctl.submit(['raw', 'my-ad', '--go', '--batch', 'T'])
        return json.loads((self.state / 'runs.json').read_text()), json.loads((self.state / 'ledger.json').read_text())

    def test_a_started_run_is_recorded_with_its_call(self):
        runs, ledger = self.submit()
        (r,) = runs.values()
        self.assertEqual((r['call'], r['collected'], r['code'], r['batch']), ('fc-1', False, 'a' * 16, 'T'))
        self.assertIn('plan_sha', r)
        self.assertEqual({c['status'] for c in ledger['calls']}, {'ADMITTED', 'REMOTE_STARTED'})

    def test_the_ad_is_claimed_before_anything_is_uploaded(self):
        seen = {}

        def stage(*a, **k):   # another session looks at the registry while this submit is still uploading
            seen.update(json.loads((self.state / 'runs.json').read_text()))
        self.submit(stage=stage)
        (claim,) = seen.values()
        self.assertEqual((claim['ad'], claim['collected'], claim['pid'], 'call' in claim), ('my-ad', False, os.getpid(), False))
        with self.assertRaises(SystemExit) as stop:      # ... and its own submit of the same ad is refused
            self.submit(runs_before=seen)
        self.assertIn('another submit or run of this ad is open', str(stop.exception))

    def test_a_submit_that_fails_before_the_cloud_leaves_no_entry(self):
        def stage(*a, **k):
            raise SystemExit('upload refused')
        with self.assertRaises(SystemExit):
            self.submit(stage=stage)
        self.assertEqual(json.loads((self.state / 'runs.json').read_text()), {})

    def test_a_spawn_error_keeps_the_claim_and_frees_the_budget(self):
        runs, ledger = self.submit(spawn=lambda payload: ConnectionError('reset by peer'))
        (r,) = runs.values()
        self.assertNotIn('call', r)                      # unknown whether the cloud took it: the ad stays claimed
        self.assertEqual({c['status'] for c in ledger['calls']}, {'SKIPPED'})
        self.assertEqual(ledger['estimated_total_usd'], '0')


class RefusalTests(unittest.TestCase):
    def project(self, td, plan):
        root = pathlib.Path(td)
        proj = root / 'projects/my-ad'
        (proj / 'CLIPS').mkdir(parents=True)
        (proj / 'plan.json').write_text(json.dumps(plan))
        for b in plan.get('beats', []):
            (proj / 'CLIPS' / f"clip_{b['n']:02d}.mp4").write_text('x')
        return root

    def test_redo_notes_are_checked_on_the_mac(self):
        plan = {'beats': [{'n': 1, 'duration': 5}, {'n': 2, 'duration': 5}]}
        with tempfile.TemporaryDirectory() as td, mock.patch.object(ctl, 'ROOT', self.project(td, plan)):
            spec = lambda redos: {'ad': 'my-ad', 'recipe': 'ai-revise', 'redos': redos}   # noqa: E731
            self.assertEqual(ctl.plan_job(spec([[2, 'clip', 'slower swipe']]), {**ctl.DEFAULTS}, {}, {})['redos'], [[2, 'clip', 'slower swipe']])
            for bad in ([[2, 'clip', 'x' * 601]], [[7, 'clip', 'no such beat']], [[0, 'clip', '']]):
                with self.assertRaises(SystemExit, msg=bad):
                    ctl.plan_job(spec(bad), {**ctl.DEFAULTS}, {}, {})

    def test_banned_footage_is_refused_before_the_render(self):
        plan = {'shots': [{'src': '/x/footage/raw/abc.mp4', 'in': 44.9, 'at': 0}], 'aroll': {'file': 'a.mp4'}}
        with tempfile.TemporaryDirectory() as td, mock.patch.object(ctl, 'ROOT', self.project(td, plan)):
            hit = [{'where': 'shot 0', 'src': '/x/footage/raw/abc.mp4', 'in': 44.9, 'reason': 'owner 11/8: not satisfying'}]
            with mock.patch.object(ctl, 'banned_hits', lambda p: hit), self.assertRaises(SystemExit) as stop:
                ctl.plan_job({'ad': 'my-ad', 'recipe': 'raw', 'redos': []}, {**ctl.DEFAULTS}, {}, {})
            self.assertIn('abc.mp4', str(stop.exception))
            self.assertIn('not satisfying', str(stop.exception))
            with mock.patch.object(ctl, 'banned_hits', lambda p: []):
                self.assertEqual(ctl.plan_job({'ad': 'my-ad', 'recipe': 'raw', 'redos': []}, {**ctl.DEFAULTS}, {}, {})['recipe'], 'raw')

    def test_small_text_files_in_the_store_are_always_sent_again(self):
        store = {'footage/raw/a.mp4': 5_000_000, 'footage/transcripts/a.words.json': 900, 'library/music/x.mp3': 1_500_000}
        self.assertTrue(ctl.store_has(store, 'footage/raw/a.mp4', 5_000_000))
        self.assertTrue(ctl.store_has(store, 'library/music/x.mp3', 1_500_000))
        self.assertFalse(ctl.store_has(store, 'footage/raw/a.mp4', 5_000_001))
        self.assertFalse(ctl.store_has(store, 'footage/transcripts/a.words.json', 900))   # same length, maybe edited
        self.assertFalse(ctl.store_has(store, 'footage/raw/new.mp4', 10))


class CollectTests(unittest.TestCase):
    def test_generation_records_made_on_the_mac_survive_a_download(self):
        cloud = '{"key": "a", "taskId": "1"}\n{"key": "a", "state": "success"}\n'
        local = '{"key": "a", "taskId": "1"}\n{"key": "b", "taskId": "2", "state": "submitted"}\n'
        self.assertEqual(ctl.local_only_lines(local, cloud), ['{"key": "b", "taskId": "2", "state": "submitted"}'])
        self.assertEqual(ctl.local_only_lines(cloud, cloud), [])

    def test_a_partly_finished_redo_list_names_only_the_rest(self):
        r = {'run': 'my-ad-ai-revise-1795000000', 'ad': 'my-ad', 'recipe': 'ai-revise',
             'redos': [[2, 'frame', 'grey couch'], [3, 'clip', 'slower swipe'], [5, 'clip', '']]}
        st = {'state': 'failed', 'steps': [{'stages': ['redo'], 'failed': 'redo', 'redos_done': [[2, 'frame']]}]}
        nxt = ctl.next_step(r, st)
        self.assertIn('do NOT send them again', nxt)
        self.assertIn('"my-ad:3:clip:slower swipe"', nxt)
        self.assertIn('"my-ad:5:clip:"', nxt)
        self.assertNotIn('my-ad:2:frame', nxt)
        self.assertNotIn('NOT send', ctl.next_step(r, {'state': 'failed', 'steps': [{'stages': ['redo'], 'failed': 'redo'}]}))

    def test_finished_redos_travel_from_the_worker_to_the_board(self):
        job = {'run': 'my-ad-ai-revise-1795000000', 'ad': 'my-ad', 'recipe': 'ai-revise', 'code': 'a' * 16, 'redos': [[2, 'frame', 'x'], [3, 'clip', 'y']]}
        receipt = json.dumps({'stages': [{'stage': 'redo', 'returncode': 1, 'seconds': 2.0, 'tail': 't'}], 'wall_seconds': 9.0,
                              'log': '.cloud/x.log', 'redos_done': [[2, 'frame']]})
        clock = iter(range(1000, 9000, 5))
        out = P.run_pipeline(job, lambda kind, payload: receipt, lambda s: None, now=lambda: next(clock))
        self.assertEqual((out['state'], out['steps'][0]['redos_done']), ('failed', [[2, 'frame']]))

    def test_one_bad_ad_does_not_stop_the_collect_of_the_others(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(ctl, 'STATE', pathlib.Path(td)):
            with ctl.runs_locked() as runs:
                for i, ad in enumerate(('a', 'b', 'c')):
                    runs[f'{ad}-raw-{i}'] = {'run': f'{ad}-raw-{i}', 'ad': ad, 'recipe': 'raw', 'submitted': i, 'collected': False}

            def one(vol, r):
                if r['ad'] == 'b':
                    raise SystemExit('download failed on b/MASTER.mp4')
                return r, {'state': 'done'}, None
            with mock.patch.object(ctl, 'collect_one', one), mock.patch.object(ctl, 'ledger', lambda: None), \
                    mock.patch.dict(sys.modules, {'modal': fake_modal()}), mock.patch('builtins.print') as out:
                done = ctl.collect([])
            self.assertEqual([r['ad'] for r, _ in done], ['a', 'c'])
            self.assertTrue(any('b: NOT collected' in str(c) for c in out.call_args_list))

    def test_a_submit_that_never_started_is_closed_without_a_download(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(ctl, 'STATE', pathlib.Path(td)):
            entry = {'run': 'a-raw-1', 'ad': 'a', 'recipe': 'raw', 'submitted': 1, 'collected': False, 'plan_sha': 'x'}
            with ctl.runs_locked() as runs:
                runs['a-raw-1'] = entry
            never = {'state': 'failed', 'steps': [], 'never_started': True, 'error': 'the submit did not finish'}
            with mock.patch.object(ctl, 'state_of', lambda r: never), mock.patch.object(ctl, 'pull', side_effect=AssertionError('no download')), \
                    mock.patch('builtins.print'):
                r, st, stop = ctl.collect_one(None, dict(entry))
            self.assertEqual((r['collected'], r['final_state'], stop), (True, 'failed', None))
            self.assertIn('submit a again', ctl.runs_load()['a-raw-1']['next'])


class WatchTests(unittest.TestCase):
    def test_unsent_slack_notes_are_kept_and_sent_in_order(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(ctl, 'STATE', pathlib.Path(td)), \
                mock.patch.object(ctl, 'SLACK_POST', pathlib.Path(td) / 'slack-post'):
            (pathlib.Path(td) / 'slack-post').write_text('#!/bin/sh\n')
            sent, up = [], [False]
            with mock.patch.object(ctl, 'cfg', lambda: {'slack_user_id': 'U1'}), \
                    mock.patch.object(ctl, 'notify', lambda text: up[0] and (sent.append(text) or True)):
                self.assertFalse(ctl.notify_queued('first'))
                self.assertFalse(ctl.notify_queued('second'))
                self.assertEqual(len((pathlib.Path(td) / 'slack-unsent.jsonl').read_text().splitlines()), 2)
                up[0] = True
                self.assertTrue(ctl.notify_queued())
                self.assertEqual(sent, ['first', 'second'])
                self.assertFalse((pathlib.Path(td) / 'slack-unsent.jsonl').exists())
            with mock.patch.object(ctl, 'cfg', lambda: {}):
                self.assertFalse(ctl.notify_queued('slack is off'))
                self.assertFalse((pathlib.Path(td) / 'slack-unsent.jsonl').exists())

    def test_once_returns_at_once_when_idle_and_keeps_looking_while_runs_are_open(self):
        left, naps = iter([2, 1, 0]), []
        with mock.patch.object(ctl, 'watch_pass', lambda: next(left)), mock.patch.object(ctl, 'cfg', lambda: {'watch_fast_s': 45}), \
                mock.patch.object(ctl.time, 'sleep', naps.append):
            ctl.watch(['--once'])
        self.assertEqual(naps, [45, 45])
        with mock.patch.object(ctl, 'watch_pass', lambda: 0), mock.patch.object(ctl, 'cfg', lambda: {}), \
                mock.patch.object(ctl.time, 'sleep', side_effect=AssertionError('idle: no waiting')):
            ctl.watch(['--once'])
        with mock.patch.object(ctl, 'watch_pass', lambda: 3), mock.patch.object(ctl, 'cfg', lambda: {'watch_linger_s': 0}), \
                mock.patch.object(ctl.time, 'sleep', naps.append):
            ctl.watch(['--once'])   # past the linger time: hands back to launchd even with runs open


class WorkerTests(unittest.TestCase):
    def test_a_half_saved_project_folder_is_put_back(self):
        with tempfile.TemporaryDirectory() as td:
            vol = pathlib.Path(td)
            for suffix, plan in (('.incoming', 'new'), ('.previous', 'old')):
                (vol / f'my-ad{suffix}').mkdir()
                (vol / f'my-ad{suffix}' / 'plan.json').write_text(plan)
            (vol / 'my-ad.incoming' / ad_job.MANIFEST).write_text('{}')
            self.assertEqual(ad_job.recover(vol / 'my-ad'), '.incoming')            # the finished new copy wins
            self.assertEqual((vol / 'my-ad/plan.json').read_text(), 'new')
            self.assertIsNone(ad_job.recover(vol / 'my-ad'))                        # nothing to do when the folder is there
            import shutil
            shutil.rmtree(vol / 'my-ad')
            self.assertEqual(ad_job.recover(vol / 'my-ad'), '.previous')
            self.assertEqual((vol / 'my-ad/plan.json').read_text(), 'old')
            shutil.rmtree(vol / 'my-ad')
            self.assertIsNone(ad_job.recover(vol / 'my-ad'))

    def test_an_upload_is_retried_but_a_paid_task_is_asked_for_once(self):
        import httpx
        calls, answers = [], []

        def request(method, url, **kw):
            calls.append(url)
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return httpx.Response(a, json={'code': 200, 'data': {'downloadUrl': 'u'}}, request=httpx.Request(method, url))
        mod = types.SimpleNamespace(httpx=types.SimpleNamespace(request=request, HTTPStatusError=httpx.HTTPStatusError, HTTPError=httpx.HTTPError),
                                    _h=lambda: {}, _req=lambda *a, **k: None)
        with tempfile.TemporaryDirectory() as td, mock.patch.object(adjob_boot, 'STATE', pathlib.Path(td) / '.adjob'), \
                mock.patch.object(adjob_boot.time, 'sleep', lambda s: None), mock.patch.dict(os.environ, {'ADJOB_MAX_TASKS': '5'}):
            adjob_boot.patch_kie(mod)
            up, task = 'https://kieai.example/api/file-stream-upload', 'https://api.kie.ai/api/v1/jobs/createTask'
            answers[:] = [httpx.ConnectError('blip'), 502, 200]
            self.assertEqual(mod._req('POST', up, data={})['data']['downloadUrl'], 'u')
            self.assertEqual(calls, [up] * 3)
            calls.clear(); answers[:] = [httpx.ConnectError('blip'), 200]
            with self.assertRaises(httpx.ConnectError):
                mod._req('POST', task, json={'model': 'm'})
            self.assertEqual(calls, [task])                                         # never a second createTask
            calls.clear(); answers[:] = [401]
            with self.assertRaises(httpx.HTTPStatusError):
                mod._req('POST', up, data={})                                       # a refusal is not retried
            self.assertEqual(calls, [up])


if __name__ == '__main__':
    unittest.main()
