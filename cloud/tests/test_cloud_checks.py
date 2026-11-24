"""Final checks in the cloud: one more unpaid step so a run comes back already checked. The checks are
advisory (they never fail a finished video), off unless the config asks for them, and the Mac stays the authority until
`trust_cloud_checks` is set."""
import json
import pathlib
import sys
import tempfile
import unittest
from decimal import Decimal as D
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'cloud'), str(ROOT / 'tools')]
from cloud import ctl  # noqa: E402
from cloud.worker import ad_job, pipeline as P  # noqa: E402

CODE = 'a' * 16
FINISHED = ('raw', 'ai', 'ai-resume', 'ai-clips', 'ai-revise', 'ai-finish')


def job(recipe='raw', **kw):
    return {'run': f'my-ad-{recipe}-1795000000', 'ad': 'my-ad', 'recipe': recipe, 'code': CODE, **kw}


def receipt(stages, **kw):
    return json.dumps({'stages': [{'stage': s, 'returncode': 0, 'seconds': 2.0, 'tail': 't'} for s in stages], 'wall_seconds': 10.0,
                       'log': '.cloud/x.log', 'kie_credits_consumed_this_run': 0, 'kie_create_tasks_this_run': 0, **kw})


def run_it(j, answers):
    calls = []

    def call(kind, payload):
        calls.append((kind, payload))
        a = answers[len(calls) - 1]
        if isinstance(a, Exception):
            raise a
        return a
    clock = iter(range(1000, 9000, 5))
    return P.run_pipeline(j, call, lambda s: None, now=lambda: next(clock)), calls


class PipelineTests(unittest.TestCase):
    def test_the_check_step_exists_only_when_asked_and_only_after_a_finished_video(self):
        for recipe in P.RECIPES:
            self.assertEqual(P.steps_of(recipe), list(P.RECIPES[recipe]), recipe)            # nothing changes by default
            extra = P.steps_of(recipe, True)[len(P.RECIPES[recipe]):]
            self.assertEqual(bool(extra), recipe in FINISHED, recipe)
            for kind, stages in extra:
                self.assertEqual(kind, 'plain')                                               # no secret, no network, never paid
                self.assertLessEqual(set(stages), P.KINDS['plain'])
                self.assertLessEqual(set(stages), ad_job.STAGES)
                self.assertLessEqual(set(stages), {'rawverify', 'preflight'})
        self.assertEqual(P.CHECK_STEP['raw'], ('plain', ['rawverify', 'preflight']))
        self.assertEqual(P.validate(job('raw')), P.RECIPES['raw'])
        self.assertEqual(P.validate(job('raw', checks=True))[-1], P.CHECK_STEP['raw'])
        self.assertEqual(P.validate(job('ai-frames', skip=[], checks=True)), list(P.RECIPES['ai-frames']))
        for bad in ('yes', 1, None):
            with self.assertRaises(ValueError):
                P.validate(job('raw', checks=bad))

    def test_a_run_comes_back_with_what_the_checks_found(self):
        found = {'rawverify': {'returncode': 0, 'seconds': 40.0}, 'preflight': {'returncode': 1, 'fingerprint': 'f' * 12, 'lines': 9, 'fails': ['FAIL T09 repeated shot at 12.0s']}}
        out, calls = run_it(job('raw', checks=True), [receipt(['shotcheck']), receipt(['rawrender', 'padtail']),
                                                      receipt(['rawverify', 'preflight'], checks=found)])
        self.assertEqual(out['state'], 'done')                                                # a check that FAILs never fails the run
        self.assertEqual(out['steps'][-1]['checks'], found)
        self.assertEqual([p.get('advisory') for _, p in calls], [None, None, True])           # only the check step is advisory
        self.assertEqual(out['plan'][-1], ['plain', ['rawverify', 'preflight']])
        self.assertNotIn('checks', out['steps'][0])

    def test_a_check_worker_that_cannot_run_leaves_the_video_done(self):
        for error in (ValueError('stage not allowed'), RuntimeError('container died')):
            out, calls = run_it(job('raw', checks=True), [receipt(['shotcheck']), receipt(['rawrender', 'padtail']), error, error])
            self.assertEqual(out['state'], 'done', error)
            self.assertIsNone(out['steps'][-1]['checks'])
            self.assertIn(type(error).__name__, out['steps'][-1]['error'])
        # the render itself failing is still a failed run, and the checks never start
        out, calls = run_it(job('raw', checks=True), [receipt(['shotcheck']), RuntimeError('x'), RuntimeError('x')])
        self.assertEqual((out['state'], len(calls)), ('failed', 3))

    def test_without_the_flag_a_run_is_exactly_as_before(self):
        out, calls = run_it(job('raw'), [receipt(['shotcheck']), receipt(['rawrender', 'padtail'])])
        self.assertEqual((out['state'], len(calls), len(out['steps'])), ('done', 2, 2))
        self.assertFalse(any('advisory' in p for _, p in calls))

    def test_an_ai_run_checks_after_the_finish_step(self):
        out, calls = run_it(job('ai-finish', checks=True), [receipt(['qc', 'stitch', 'masterqc']),
                                                            receipt(['preflight'], checks={'preflight': {'returncode': 0, 'fingerprint': 'abc', 'fails': []}})])
        self.assertEqual((out['state'], calls[-1][0], calls[-1][1]['stages']), ('done', 'plain', ['preflight']))


class WorkerTests(unittest.TestCase):
    def test_only_the_final_checks_can_be_advisory(self):
        ok = {'ad': 'a', 'stages': ['rawverify', 'preflight'], 'code': CODE, 'advisory': True}
        self.assertEqual(ad_job.validate(ok), ('a', ['rawverify', 'preflight']))
        for stages in (['rawrender'], ['preflight', 'padtail'], ['clips']):
            with self.assertRaises(ValueError):
                ad_job.validate({**ok, 'stages': stages, 'max_tasks': 2})

    def worker(self, td, answers, **kw):
        """ad_job.run with the container set-up and the tools replaced: `answers` = {stage: (returncode, writes media file?)}."""
        work = pathlib.Path(td)
        project = work / 'projects/my-ad'
        project.mkdir(parents=True, exist_ok=True)
        ran = []

        class Proc:
            pid = 1

            def __init__(self, cmd, **_):
                self.stage = 'preflight' if 'tools/preflight.py' in cmd else 'rawverify'
                ran.append((self.stage, cmd))
                self.returncode, media = answers[self.stage]
                if media is not None:
                    (project / ad_job.MEDIA_CHECKS).parent.mkdir(exist_ok=True)
                    (project / ad_job.MEDIA_CHECKS).write_text(json.dumps(media))

            def communicate(self, timeout=None):
                return f'{self.stage} output', None
        with mock.patch.object(ad_job, 'WORK', work), mock.patch.object(ad_job, 'setup') as setup, mock.patch.object(ad_job, 'env_for', lambda w, n: {}), \
                mock.patch.object(ad_job, 'credits', lambda p: (0.0, 0)), mock.patch.object(ad_job, 'persist') as persist, \
                mock.patch.object(ad_job, 'redactor', lambda: (lambda t: t)), mock.patch.object(ad_job.subprocess, 'Popen', Proc):
            out = json.loads(ad_job.run({'ad': 'my-ad', 'stages': ['rawverify', 'preflight'], 'code': CODE, **kw}))
        return out, ran, setup, persist, project

    def test_the_worker_reports_each_check_and_never_fails_the_step(self):
        media = {'master': 'MASTER.mp4', 'fingerprint': 'abc123', 'lines': ['PASS format', 'FAIL T09 repeated shot', 'PASS tail']}
        with tempfile.TemporaryDirectory() as td:
            out, ran, setup, persist, project = self.worker(td, {'rawverify': (1, None), 'preflight': (1, media)}, advisory=True)
            self.assertEqual([s for s, _ in ran], ['rawverify', 'preflight'])                 # a failed verify does not stop preflight
            self.assertTrue(all(s['returncode'] == 0 for s in out['stages']))
            self.assertEqual([s['check_returncode'] for s in out['stages']], [1, 1])
            self.assertEqual(out['checks']['rawverify']['returncode'], 1)
            pre = out['checks']['preflight']
            self.assertEqual((pre['returncode'], pre['fingerprint'], pre['lines'], pre['fails']), (1, 'abc123', 3, ['FAIL T09 repeated shot']))
            self.assertTrue(setup.call_args.kwargs['need_model'])                              # caption sync needs the speech model
            self.assertTrue(persist.called)                                                    # the results travel back with the project
            cmd = ran[1][1]
            self.assertEqual(cmd[cmd.index('--media-json') + 1], 'projects/my-ad/.cloud/media-checks.json')

    def test_a_preflight_that_did_not_finish_carries_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            stale = pathlib.Path(td) / 'projects/my-ad' / ad_job.MEDIA_CHECKS
            stale.parent.mkdir(parents=True)
            stale.write_text(json.dumps({'fingerprint': 'old', 'lines': ['PASS format']}))     # from an earlier render
            out, *_ = self.worker(td, {'rawverify': (0, None), 'preflight': (-9, None)}, advisory=True)
            self.assertIsNone(out['checks']['preflight']['fingerprint'])
            self.assertFalse(stale.exists())

    def test_outside_a_check_step_a_failed_verify_still_stops(self):
        with tempfile.TemporaryDirectory() as td:
            out, ran, *_ = self.worker(td, {'rawverify': (1, None), 'preflight': (0, None)})
            self.assertEqual(([s for s, _ in ran], out['stages'][0]['returncode']), (['rawverify'], 1))
            self.assertNotIn('checks', out)


class ClientTests(unittest.TestCase):
    RUN = {'run': 'x-raw-1795000000', 'ad': 'x', 'recipe': 'raw', 'checks': True}

    def test_the_extra_step_is_admitted_and_settled(self):
        self.assertEqual(ctl.step_keys('r', 'raw'), ['r-s0-claude', 'r-s1-plain', 'r-pipeline'])
        self.assertEqual(ctl.step_keys('r', 'raw', True), ['r-s0-claude', 'r-s1-plain', 'r-s2-plain', 'r-pipeline'])
        done = {'started': 1.0, 'finished': 400.0, 'steps': [{'seconds': 30.0}, {'seconds': 200.0}, {'seconds': 90.0, 'checks': {}}]}
        got = ctl.settle(self.RUN, done)
        self.assertEqual([k for k, _, _ in got], ctl.step_keys(self.RUN['run'], 'raw', True))
        self.assertEqual([v for _, v, _ in got], ['DONE'] * 4)
        self.assertEqual(got[2][2], (D(130) * ctl.unit('plain')).quantize(D('.0001')))
        # a check step that was refused costs the seconds the tries took, not the 45-minute bound
        refused = ctl.settle(self.RUN, {**done, 'steps': done['steps'][:2] + [{'seconds': 5.0, 'error': 'ValueError: stage', 'checks': None}]})
        self.assertEqual(refused[2][1], 'FAILED')
        self.assertLess(refused[2][2], ctl.bound('plain') / 10)
        # a run admitted WITHOUT checks settles exactly as before
        old = ctl.settle({'run': 'x-raw-1795000000', 'recipe': 'raw'}, {**done, 'steps': done['steps'][:2]})
        self.assertEqual(len(old), 3)
        never = ctl.settle(self.RUN, {'state': 'failed', 'steps': [], 'never_started': True})
        self.assertEqual(len(never), 4)

    def test_every_check_call_fits_the_admission_cap_and_is_never_a_stop_reason(self):
        from cloud.worker.overnight_budget import Budget
        with tempfile.TemporaryDirectory() as td:
            b = Budget(pathlib.Path(td) / 'ledger.json', '10.00', '10.00', task='t')
            for i in range(3):   # the check step failing on three ads in a row must not raise the global stop
                b.reserve(f'k{i}', str(ctl.bound('plain')), 'function', {'family': 'ads-raw-checks', 'paid_call': False, 'diagnostic_only': True,
                                                                         'cpu': '4', 'memory_GiB': '8', 'timeout': 2700, 'stages': ['preflight']})
                b.finish(f'k{i}', 'FAILED', '0.0010', 5)
            self.assertFalse((pathlib.Path(td) / 'GLOBAL_STOP.json').exists())

    def test_what_the_cloud_found(self):
        self.assertIsNone(ctl.cloud_checks_of({'state': 'done', 'steps': [{'seconds': 1}, {'seconds': 2}]}))
        row = {'stages': ['rawverify', 'preflight'], 'checks': {'rawverify': {'returncode': 0}, 'preflight': {'returncode': 0, 'fingerprint': 'abc', 'fails': []}}}
        self.assertEqual(ctl.cloud_checks_of({'steps': [{}, row]})['verdict'], 'PASS')
        row['checks']['preflight'].update(returncode=1, fails=['FAIL T09 repeated shot at 12s'])
        got = ctl.cloud_checks_of({'steps': [{}, row]})
        self.assertEqual((got['verdict'], got['fails']), ('FAIL', ['FAIL T09 repeated shot at 12s']))
        row['checks'] = {'rawverify': {'returncode': 1}, 'preflight': {'returncode': 0, 'fingerprint': 'abc', 'fails': []}}
        got = ctl.cloud_checks_of({'steps': [row]})
        self.assertEqual((got['verdict'], got['fails']), ('FAIL', ['FAIL rawverify stopped with code 1']))
        # preflight that did not finish (no fingerprint) is never a PASS; a refused or crashed step is NOT RUN
        row['checks'] = {'rawverify': {'returncode': 0}, 'preflight': {'returncode': 0, 'fingerprint': None}}
        self.assertEqual(ctl.cloud_checks_of({'steps': [row]})['verdict'], 'FAIL')
        for checks in (None, {}, {'rawverify': {'returncode': 0}}):
            self.assertEqual(ctl.cloud_checks_of({'steps': [{'stages': ['rawverify', 'preflight'], 'checks': checks, 'error': 'ValueError: x'}]})['verdict'], 'NOT RUN')

    def test_parity_says_when_cloud_and_mac_differ(self):
        r = {'run': 'x-raw-1', 'ad': 'x', 'recipe': 'raw'}
        cloud = {'verdict': 'FAIL', 'fails': ['FAIL T09 repeated shot at 12.0s'], 'fingerprint': 'abc', 'stages': {'rawverify': 0, 'preflight': 1}}
        both = [('rawedit.py verify', 0), ('preflight.py x', 1)]
        with mock.patch.object(ctl, 'mac_fail_lines', lambda ad: ['FAIL T09 repeated shot at 12.5s', 'FAIL T13 tilted text at 3s']):
            row = ctl.parity_row(r, cloud, both, now=5)
            self.assertEqual((row['agree'], row['cloud_only'], row['mac_only'], row['cloud'], row['mac']), (True, [], ['FAIL T13'], 'FAIL', 'FAIL'))
        with mock.patch.object(ctl, 'mac_fail_lines', lambda ad: []):
            row = ctl.parity_row(r, cloud, [('rawedit.py verify', 0), ('preflight.py x', 0)])
            self.assertEqual((row['agree'], row['cloud_only']), (False, ['FAIL T09']))             # the cloud raised what the Mac did not
            ok = {'verdict': 'PASS', 'fails': [], 'fingerprint': 'abc', 'stages': {'rawverify': 0, 'preflight': 0}}
            self.assertTrue(ctl.parity_row(r, ok, [('rawedit.py verify', 0), ('preflight.py x', 0)])['agree'])
            self.assertFalse(ctl.parity_row(r, ok, [('rawedit.py verify', 1)])['agree'])           # verify: cloud passed, Mac failed
            self.assertFalse(ctl.parity_row(r, {**ok, 'verdict': 'NOT RUN', 'stages': {}}, both)['agree'])
        with mock.patch.object(ctl, 'mac_fail_lines', side_effect=AssertionError('stale file must not be read')):
            row = ctl.parity_row(r, {**cloud, 'stages': {'rawverify': 1, 'preflight': 1}}, [('rawedit.py verify', 1)])
            self.assertEqual((row['agree'], row['mac_preflight_ran']), (True, False))

    def plan(self, td, **config):
        root = pathlib.Path(td)
        proj = root / 'projects/my-ad'
        proj.mkdir(parents=True)
        (proj / 'plan.json').write_text(json.dumps({'shots': [{'src': 'footage/a.mp4', 'in': 1, 'at': 0}]}))
        with mock.patch.object(ctl, 'ROOT', root), mock.patch.object(ctl, 'banned_hits', lambda plan: []):
            return ctl.plan_job({'ad': 'my-ad', 'recipe': 'raw'}, {**ctl.DEFAULTS, **config}, {}, {})

    def test_checks_are_off_until_the_config_turns_them_on(self):
        self.assertIs(ctl.DEFAULTS['cloud_checks'], False)
        self.assertIs(ctl.DEFAULTS['trust_cloud_checks'], False)
        with tempfile.TemporaryDirectory() as td:
            self.assertNotIn('checks', self.plan(td))
        with tempfile.TemporaryDirectory() as td:
            self.assertIs(self.plan(td, cloud_checks=True)['checks'], True)
        with tempfile.TemporaryDirectory() as td:
            self.assertNotIn('checks', self.plan(td, cloud_checks='true'))                     # only a real true counts
        with tempfile.TemporaryDirectory() as td:                                             # one submit can ask for it: --checks
            root = pathlib.Path(td)
            (root / 'projects/my-ad').mkdir(parents=True)
            (root / 'projects/my-ad/plan.json').write_text(json.dumps({'shots': [{'src': 'footage/a.mp4', 'in': 1, 'at': 0}]}))
            with mock.patch.object(ctl, 'ROOT', root), mock.patch.object(ctl, 'banned_hits', lambda plan: []):
                self.assertIs(ctl.plan_job({'ad': 'my-ad', 'recipe': 'raw'}, dict(ctl.DEFAULTS), {}, {}, checks=True)['checks'], True)

    def gate(self, carried):
        ran = []

        def fake(cmd, **kw):
            ran.append(cmd[1:])
            return mock.Mock(returncode=0)
        with tempfile.TemporaryDirectory() as td, mock.patch.object(ctl, 'ROOT', pathlib.Path(td)), mock.patch.object(ctl.subprocess, 'run', fake):
            (pathlib.Path(td) / 'projects/my-ad').mkdir(parents=True)
            results, _, _ = ctl.mac_gate('my-ad', True, carried)
        return ran, results

    def test_the_mac_checks_everything_unless_the_cloud_is_trusted(self):
        ran, results = self.gate(None)
        self.assertEqual(ran, [['tools/rawedit.py', 'projects/my-ad', 'verify'], ['tools/preflight.py', 'projects/my-ad']])
        self.assertEqual(results, [('rawedit.py verify', 0), ('preflight.py my-ad', 0)])
        ran, results = self.gate('/x/media-checks.json')
        self.assertEqual(ran, [['tools/preflight.py', 'projects/my-ad', '--media-from', '/x/media-checks.json']])
        self.assertEqual(results, [('preflight.py my-ad', 0)])


class PreflightSplitTests(unittest.TestCase):
    def setUp(self):
        import preflight
        self.pf = preflight

    def test_cloud_results_are_only_used_for_the_exact_same_file(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / 'MASTER.mp4'
            f.write_bytes(b'video one')
            data = {'master': 'MASTER.mp4', 'fingerprint': self.pf.fingerprint(f), 'lines': ['PASS format', 'PASS T09 no repeats']}
            carried = pathlib.Path(td) / 'media.json'
            carried.write_text(json.dumps(data))
            self.assertEqual(self.pf.load_media(carried, f)['lines'], data['lines'])
            for change in ({'fingerprint': 'other'}, {'master': 'MASTER_v2.mp4'}, {'lines': []}, {'lines': 'PASS'}):
                carried.write_text(json.dumps({**data, **change}))
                self.assertIsNone(self.pf.load_media(carried, f), change)
            carried.write_text(json.dumps(data))
            f.write_bytes(b'video two, rendered again')                                        # a new render: the old results are void
            self.assertIsNone(self.pf.load_media(carried, f))
            carried.write_text('not json')
            self.assertIsNone(self.pf.load_media(carried, f))
            self.assertIsNone(self.pf.load_media(pathlib.Path(td) / 'missing.json', f))

    def test_the_cloud_part_never_runs_a_mac_only_check(self):
        pf, called = self.pf, []
        names = ('check_repeats', 'check_hook_cuts', 'check_freezes', 'check_tail', 'check_length', 'check_caption_events', 'check_external')
        mac_only = ('check_tilt', 'check_banned', 'check_sale_line', 'check_flash', 'check_reuse')
        with tempfile.TemporaryDirectory() as td, contextlib_stack() as stack:
            for n in names:
                stack.enter_context(mock.patch.object(pf, n, lambda *a, n=n, **k: called.append(n) or [f'PASS {n}']))
            for n in mac_only:
                stack.enter_context(mock.patch.object(pf, n, side_effect=AssertionError(f'{n} is a Mac-only check')))
            stack.enter_context(mock.patch.object(pf, 'frames', lambda *a, **k: []))
            lines = pf.media_lines(pathlib.Path(td), pathlib.Path(td) / 'MASTER.mp4', 1080, 1920, 30.0)
        self.assertEqual(set(called), set(names))
        self.assertEqual(lines[0], pf.format_line(1080, 1920))
        self.assertTrue(all(isinstance(x, str) for x in lines))


def contextlib_stack():
    import contextlib
    return contextlib.ExitStack()


if __name__ == '__main__':
    unittest.main()
