"""Controller v1: recipes + orchestrator core, Mac client helpers, shared clip store, shot-check gate, budget settings."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock
from decimal import Decimal as D

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'cloud'), str(ROOT / 'tools')]
from cloud import ctl  # noqa: E402
from cloud.worker import ad_job, pipeline as P  # noqa: E402
from cloud.worker.overnight_budget import Budget  # noqa: E402

CODE = 'a' * 16


def job(recipe='raw', **kw):
    return {'run': f'my-ad-{recipe}-1795000000', 'ad': 'my-ad', 'recipe': recipe, 'code': CODE, **kw}


def receipt(stages, rc=0, **kw):
    return json.dumps({'stages': [{'stage': s, 'returncode': rc if s == stages[-1] else 0, 'seconds': 2.0, 'tail': 'tail text'} for s in stages],
                       'wall_seconds': 10.0, 'log': '.cloud/x.log', 'kie_credits_consumed_this_run': 0, 'kie_create_tasks_this_run': 0, **kw})


class PipelineTests(unittest.TestCase):
    def run_it(self, j, answers):
        calls, states = [], []

        def call(kind, payload):
            calls.append((kind, payload))
            a = answers[len(calls) - 1]
            if isinstance(a, Exception):
                raise a
            return a
        clock = iter(range(1000, 9000, 5))
        out = P.run_pipeline(j, call, lambda s: states.append(json.loads(json.dumps(s))), now=lambda: next(clock))
        return out, calls, states

    def test_every_recipe_step_runs_in_a_worker_that_allows_it(self):
        for name, steps in P.RECIPES.items():
            for kind, stages in steps:
                self.assertLessEqual(set(stages), P.KINDS[kind], name)
                self.assertLessEqual(set(stages), ad_job.STAGES, name)

    def test_only_the_generation_worker_ever_gets_paid_stages_or_a_task_cap(self):
        paid_stages = {'vo', 'frames', 'clips', 'redo'}
        for kind in ('plain', 'claude'):
            self.assertFalse(P.KINDS[kind] & paid_stages)
        out, calls, _ = self.run_it(job('ai', max_tasks=6), [receipt(['plan_review']), receipt(['vo']), receipt(['frames'], kie_create_tasks_this_run=3),
                                                             receipt(['clips']), receipt(['qc', 'stitch', 'masterqc'])])
        self.assertEqual(out['state'], 'done')
        # one paid stage per step; the cap is the whole run's (the worker keeps the run's counter), never sent to other kinds
        self.assertEqual([(k, p['stages'], p['max_tasks']) for k, p in calls],
                         [('claude', ['plan_review'], 0), ('gen', ['vo'], 6), ('gen', ['frames'], 6), ('gen', ['clips'], 6), ('claude', ['qc', 'stitch', 'masterqc'], 0)])
        self.assertTrue(all(p['code'] == CODE and p['ad'] == 'my-ad' and p['run'] == 'my-ad-ai-1795000000' for _, p in calls))
        self.assertEqual({k: p['timeout_s'] for k, p in calls}, {k: P.STAGE_TIMEOUT[k] for k, _ in calls})
        for kind, limit in P.STAGE_TIMEOUT.items():   # a stage must end (and save) before its cloud function is cut off
            self.assertLessEqual(limit + 240, ctl.SHAPE[kind][2], kind)

    def test_frame_review_recipes_stop_before_clips_and_qc_only_the_stills(self):
        out, calls, _ = self.run_it(job('ai-frames', max_tasks=4), [receipt(['plan_review']), receipt(['vo']), receipt(['frames']), receipt(['qc'])])
        self.assertEqual((out['state'], calls[-1][1]['qc_stage']), ('done', 'frames'))
        self.assertNotIn('clips', [s for _, p in calls for s in p['stages']])
        redos = [[2, 'frame', 'make the couch grey']]
        out, calls, _ = self.run_it(job('ai-frames-revise', max_tasks=3, redos=redos), [receipt(['redo']), receipt(['qc'])])
        self.assertEqual((out['state'], calls[0][1]['redos'], calls[1][1]['qc_stage']), ('done', redos, 'frames'))
        out, calls, _ = self.run_it(job('ai-clips', max_tasks=4), [receipt(['clips']), receipt(['qc', 'stitch', 'masterqc'])])
        self.assertEqual(out['state'], 'done')
        self.assertNotIn('qc_stage', calls[1][1])
        self.assertLessEqual(P.FRAME_REVIEW, set(P.RECIPES))

    def test_existing_voice_is_skipped_never_made_twice(self):
        out, calls, _ = self.run_it(job('ai-frames', max_tasks=4, skip=['vo']), [receipt(['plan_review']), receipt(['frames']), receipt(['qc'])])
        self.assertEqual(out['state'], 'done')
        self.assertEqual([p['stages'] for _, p in calls], [['plan_review'], ['frames'], ['qc']])
        self.assertTrue(out['steps'][1]['skipped'])
        with self.assertRaises(ValueError):
            P.validate(job('ai', max_tasks=4, skip=['clips']))
        self.assertEqual(P.payload_for(job('ai-clips', max_tasks=2, timeout_s=75), 'gen', ['clips'])['timeout_s'], 75)
        self.assertEqual(P.payload_for(job('raw', timeout_s=3400), 'plain', ['rawrender'])['timeout_s'], P.STAGE_TIMEOUT['plain'])
        with self.assertRaises(ValueError):
            P.validate(job('raw', timeout_s=5))

    def test_blocked_shot_check_stops_before_the_render(self):
        out, calls, states = self.run_it(job('raw'), [receipt(['shotcheck'], rc=3, gate='blocked')])
        self.assertEqual((out['state'], len(calls)), ('blocked', 1))
        self.assertEqual(states[0]['state'], 'running')
        self.assertEqual(states[-1]['state'], 'blocked')
        self.assertNotIn('current', states[-1])

    def test_failed_step_stops_and_keeps_the_tail(self):
        out, calls, _ = self.run_it(job('ai', max_tasks=4), [receipt(['plan_review']), receipt(['vo']), receipt(['frames']),
                                                             receipt(['clips'], rc=1, not_done=['3:clip'])])
        self.assertEqual((out['state'], len(calls)), ('failed', 4))
        self.assertEqual((out['steps'][-1]['failed'], out['steps'][-1]['tail'], out['steps'][-1]['not_done']), ('clips', 'tail text', ['3:clip']))

    def test_unpaid_worker_crash_gets_one_more_try(self):
        out, calls, _ = self.run_it(job('raw'), [receipt(['shotcheck']), TimeoutError('function timed out'), TimeoutError('again')])
        self.assertEqual((out['state'], len(calls)), ('failed', 3))
        self.assertIn('TimeoutError', out['steps'][-1]['error'])
        out, calls, _ = self.run_it(job('raw'), [ConnectionError('container lost'), receipt(['shotcheck']), receipt(['rawrender', 'padtail'])])
        self.assertEqual((out['state'], len(calls)), ('done', 3))
        self.assertIn('ConnectionError', out['steps'][0]['retried'])
        self.assertNotIn('error', out['steps'][0])

    def test_paid_worker_crash_is_never_retried_from_the_pipeline(self):
        out, calls, _ = self.run_it(job('ai', max_tasks=4), [receipt(['plan_review']), receipt(['vo']), TimeoutError('function timed out')])
        self.assertEqual((out['state'], len(calls)), ('failed', 3))
        self.assertEqual((out['steps'][-1]['kind'], out['steps'][-1]['attempts']), ('gen', 1))

    def test_redos_travel_only_with_the_revise_recipe(self):
        redos = [[3, 'clip', 'slower swipe']]
        out, calls, _ = self.run_it(job('ai-revise', max_tasks=1, redos=redos), [receipt(['redo']), receipt(['qc', 'stitch', 'masterqc'])])
        self.assertEqual(calls[0][1]['redos'], redos)
        self.assertNotIn('redos', calls[1][1])
        self.assertNotIn('vo', [s for _, p in calls for s in p['stages']])
        self.assertTrue(P.RUN_ID.fullmatch('my-ad-ai-frames-revise-1795000000'))
        for bad in (job('ai-revise', max_tasks=1), job('ai-frames-revise', max_tasks=1), job('ai-frames', max_tasks=1, redos=redos),
                    job('raw', redos=redos), job('raw', max_tasks=2), job('nope'),
                    {**job('raw'), 'code': '../x'}, {**job('raw'), 'run': 'other-raw-1795000000'}):
            with self.assertRaises(ValueError):
                P.validate(bad)


class WorkerJobTests(unittest.TestCase):
    def test_validate_new_fields(self):
        ok = {'ad': 'a', 'stages': ['redo'], 'max_tasks': 2, 'code': CODE, 'redos': [[2, 'frame', 'note'], [3, 'clip', '']]}
        self.assertEqual(ad_job.validate(ok), ('a', ['redo']))
        for change in ({'redos': []}, {'redos': [[0, 'frame', '']]}, {'redos': [[2, 'vo', '']]}, {'redos': [[2, 'clip', 'x' * 601]]},
                       {'code': '/etc'}, {'max_tasks': 81}, {'stages': ['shell']}, {'run': '../x'}, {'qc_stage': 'everything'},
                       {'timeout_s': 99999}, {'timeout_s': '1500'}):
            with self.assertRaises(ValueError):
                ad_job.validate({**ok, **change})

    def test_shared_store_copies_only_listed_files_and_refuses_escapes(self):
        with tempfile.TemporaryDirectory() as td:
            vol, work = pathlib.Path(td) / 'vol', pathlib.Path(td) / 'work'
            (vol / '_store/footage/raw').mkdir(parents=True)
            (vol / '_store/footage/raw/a.mp4').write_text('A')
            (vol / '_store/footage/raw/other.mp4').write_text('B')
            (vol / 'secret.txt').write_text('S')
            src = vol / 'ad1'
            src.mkdir(); work.mkdir()
            (src / 'assets.json').write_text(json.dumps(['footage/raw/a.mp4']))
            self.assertEqual(ad_job.copy_assets(work, src, vol), 'store')
            self.assertEqual((work / 'footage/raw/a.mp4').read_text(), 'A')
            self.assertFalse((work / 'footage/raw/other.mp4').exists())
            for bad in ('../secret.txt', 'footage/raw/missing.mp4'):
                (src / 'assets.json').write_text(json.dumps([bad]))
                with self.assertRaises(FileNotFoundError):
                    ad_job.copy_assets(work, src, vol)

    def test_older_per_ad_asset_folder_still_works(self):
        with tempfile.TemporaryDirectory() as td:
            vol, work = pathlib.Path(td) / 'vol', pathlib.Path(td) / 'work'
            (vol / '_assets/ad1/footage').mkdir(parents=True)
            (vol / '_assets/ad1/footage/x.mp4').write_text('X')
            (vol / 'ad1').mkdir(); work.mkdir()
            self.assertEqual(ad_job.copy_assets(work, vol / 'ad1', vol), 'legacy')
            self.assertEqual((work / 'footage/x.mp4').read_text(), 'X')
            (vol / 'ad2').mkdir()
            self.assertEqual(ad_job.copy_assets(work, vol / 'ad2', vol), 'none')


class ClientTests(unittest.TestCase):
    def test_every_call_fits_the_per_call_admission_cap(self):
        for kind in ctl.SHAPE:
            self.assertLess(ctl.bound(kind), D('.25'), kind)
        self.assertGreater(ctl.bound('plain'), ctl.bound('gen'))

    def test_redo_parsing(self):
        self.assertEqual(ctl.parse_redos(['a:3:clip:slow the swipe: a lot', 'b:1:frame', 'a:4:frame:x'], ['a', 'b']),
                         {'a': [[3, 'clip', 'slow the swipe: a lot'], [4, 'frame', 'x']], 'b': [[1, 'frame', '']]})
        self.assertEqual(ctl.parse_redos(['7:clip:fix: it'], ['only']), {'only': [[7, 'clip', 'fix: it']]})
        for bad in (['c:3:clip:x'], ['a:x:clip:x'], ['a:3:vo:x'], ['3:clip:x']):
            with self.assertRaises(ValueError):
                ctl.parse_redos(bad, ['a', 'b'])

    def test_kie_need_counts_tasks_and_worst_case_from_measured_prices(self):
        plan = {'kling_mode': 'std', 'beats': [{'n': 1, 'duration': 5}, {'n': 2, 'duration': 8, 'end_visual': 'x'},
                                               {'n': 3, 'lib': 'clipA'}, {'n': 4, 'lib': 'frameA'}]}
        lib = {'clipA': {'type': 'clip'}, 'frameA': {'type': 'frame'}}
        tasks, worst = ctl.kie_need(plan, 'ai', [], lib)
        self.assertEqual(tasks, 2 + 3 + 0 + 1)                       # still+clip, 2 stills+clip, nothing, clip only
        self.assertEqual(worst, D(25) + 120 + 50 + 192 + 120)
        self.assertEqual(ctl.kie_need(plan, 'ai-revise', [[1, 'frame', ''], [2, 'clip', '']], lib), (2, D(25) + 192))
        self.assertEqual(ctl.kie_need(plan, 'ai-finish', [], lib), (0, D(0)))
        with self.assertRaises(ValueError):
            ctl.kie_need(plan, 'ai-revise', [[9, 'clip', '']], lib)
        with self.assertRaises(ValueError):
            ctl.kie_need({**plan, 'beats': [{'n': 1, 'lib': 'gone'}]}, 'ai', [], lib)
        with self.assertRaises(ValueError):                           # no measured price for pro mode: never guessed
            ctl.kie_need({**plan, 'kling_mode': 'pro'}, 'ai', [], lib)
        self.assertEqual(ctl.kie_need({'kling_mode': 'pro', 'beats': [{'n': 1}]}, 'ai', [], {}, clip_bound='300'), (2, D(325)))

    def test_settle_charges_what_ran_and_nothing_for_skipped_steps(self):
        run = {'run': 'x-ai-1795000000', 'recipe': 'ai'}
        state = {'started': 100.0, 'finished': 400.0, 'steps': [{'seconds': 60.0}, {'seconds': 200.0, 'failed': 'clips'}]}
        got = ctl.settle(run, state)
        # a paid step that ended cleanly but incomplete fails that ad only (INCOMPLETE never raises the global stop)
        self.assertEqual([(k.rsplit('-', 2)[-2:], v) for k, v, _ in got],
                         [(['s0', 'claude'], 'DONE'), (['s1', 'gen'], 'INCOMPLETE'), (['s2', 'gen'], 'SKIPPED'), (['s3', 'gen'], 'SKIPPED'),
                          (['s4', 'claude'], 'SKIPPED'), (['1795000000', 'pipeline'], 'DONE')])
        self.assertEqual(got[2][2], D(0))
        paid_crash = ctl.settle(run, {'started': 1.0, 'finished': 50.0, 'steps': [{'seconds': 30.0}, {'error': 'FunctionTimeoutError', 'seconds': 9.0}]})
        self.assertEqual((paid_crash[1][1], paid_crash[1][2]), ('FAILED', ctl.bound('gen')))
        skipped = ctl.settle({'run': 'x-ai-frames-1795000000', 'recipe': 'ai-frames'},
                             {'started': 1.0, 'finished': 90.0, 'steps': [{'seconds': 20.0}, {'skipped': True, 'seconds': 0}, {'seconds': 30.0}, {'seconds': 10.0}]})
        self.assertEqual([v for _, v, _ in skipped], ['DONE', 'SKIPPED', 'DONE', 'DONE', 'DONE'])
        twice = ctl.settle({'run': 'x-raw-1795000000', 'recipe': 'raw'}, {'started': 1.0, 'finished': 50.0, 'steps': [{'seconds': 60.0, 'retried': 'ConnectionError'}, {'seconds': 30.0}]})
        self.assertEqual(twice[0][2], (D(200) * ctl.unit('claude')).quantize(D('.0001')))
        self.assertEqual(got[0][2], (D(100) * ctl.unit('claude')).quantize(D('.0001')))
        self.assertEqual([k for k, _, _ in got], ctl.step_keys(run['run'], 'ai'))
        crashed = ctl.settle(run, None)
        self.assertTrue(all(v == 'FAILED' for _, v, _ in crashed))
        self.assertEqual(crashed[0][2], ctl.bound('claude'))
        blocked = ctl.settle({'run': 'x-raw-1795000000', 'recipe': 'raw'}, {'started': 1.0, 'finished': 50.0, 'steps': [{'seconds': 30.0, 'gate': 'blocked', 'failed': 'shotcheck'}]})
        self.assertEqual([v for _, v, _ in blocked], ['BLOCKED', 'SKIPPED', 'DONE'])
        timeout = ctl.settle({'run': 'x-raw-1795000000', 'recipe': 'raw'}, {'started': 1.0, 'finished': 50.0, 'steps': [{'seconds': 30.0}, {'error': 'FunctionTimeoutError'}]})
        self.assertEqual((timeout[1][1], timeout[1][2]), ('FAILED', ctl.bound('plain')))

    def test_code_version_follows_content_not_the_marker(self):
        with tempfile.TemporaryDirectory() as td:
            d = pathlib.Path(td)
            (d / 'tools').mkdir(); (d / 'tools/a.py').write_text('1')
            v1 = ctl.digest_tree(d)
            (d / '.complete').write_text(v1)
            self.assertEqual(ctl.digest_tree(d), v1)
            (d / 'tools/a.py').write_text('2')
            self.assertNotEqual(ctl.digest_tree(d), v1)
            self.assertRegex(v1, r'^[0-9a-f]{16}$')

    def test_only_footage_faults_flag_a_library_clip(self):
        fid = '1DBELHq8oqAbCdEfGhIjKlMnOpQrStUvW'
        rows = ctl.flag_rows([{'key': f'{fid}@3.3', 'severity': 'block', 'clip_fault': True, 'rule': 'T04', 'issue': 'burned-in graphic'},
                              {'key': f'{fid}@9.0', 'severity': 'block', 'clip_fault': False, 'rule': 'T08', 'issue': 'shepherd on a golden line'},
                              {'key': 'vac_mk36522@0.0', 'severity': 'block', 'clip_fault': True, 'rule': 'T23', 'issue': 'web clip, not in the library'}])
        self.assertEqual(rows, [{'fid': fid, 't': 3.3, 'issue': 'T04 burned-in graphic'}])

    def test_upload_skips_intermediates_and_masters_only(self):
        for rel, skip in (('SEGMENTS/s01.mp4', True), ('MASTER.mp4', True), ('MASTER-soundoff.mp4', True), ('x/.DS_Store', True), ('CLIPS/c.mp4.part', True),
                          ('plan.json', False), ('CUT_VOICE.txt', False), ('VO/vo.mp3', False), ('CLIPS/clip_01.mp4', False), ('EDIT_KIT/MASTERS.md', False)):
            self.assertEqual(bool(ctl.SKIP_UP.search(rel)), skip, rel)


class ScaleTests(unittest.TestCase):
    """Batches, the frame-review loop, crash-safe paid work, several sessions at once."""

    def project(self, td, plan, files=()):
        root = pathlib.Path(td)
        proj = root / 'projects/my-ad'
        proj.mkdir(parents=True)
        (proj / 'plan.json').write_text(json.dumps(plan))
        for rel in files:
            (proj / rel).parent.mkdir(parents=True, exist_ok=True)
            (proj / rel).write_text('x')
        return root, proj

    def test_kie_need_does_not_count_what_already_exists(self):
        plan = {'beats': [{'n': 1, 'duration': 5}, {'n': 2, 'duration': 5, 'end_visual': 'x'}, {'n': 3, 'duration': 5}]}
        with tempfile.TemporaryDirectory() as td:
            _, proj = self.project(td, plan, ['FRAMES/scene_01.png', 'FRAMES/scene_02.png', 'CLIPS/clip_01_v2.mp4'])
            self.assertEqual(ctl.kie_need(plan, 'ai-frames', [], {}, proj=proj), (2, D(50)))      # end still of 2, still of 3
            self.assertEqual(ctl.kie_need(plan, 'ai-clips', [], {}, proj=proj), (2, D(240)))       # clips of 2 and 3
            self.assertEqual(ctl.kie_need(plan, 'ai-resume', [], {}, proj=proj), (4, D(290)))
            self.assertEqual(ctl.kie_need(plan, 'ai-frames', [], {}), (4, D(100)))                 # no folder given: everything counts
        self.assertEqual(ctl.kie_need(plan, 'ai-frames-revise', [[2, 'frame', 'x']], {}), (1, D(25)))
        with self.assertRaises(ValueError):                                                        # no clips exist during the frame review
            ctl.kie_need(plan, 'ai-frames-revise', [[2, 'clip', 'x']], {})
        self.assertEqual((ctl.task_cap(1), ctl.task_cap(8), ctl.task_cap(40)), (3, 10, 50))

    def test_refusals_happen_before_anything_starts(self):
        plan = {'beats': [{'n': 1, 'duration': 5}, {'n': 2, 'duration': 5}]}
        c = {**ctl.DEFAULTS}
        with tempfile.TemporaryDirectory() as td:
            root, proj = self.project(td, plan, ['FRAMES/scene_01.png'])
            with mock.patch.object(ctl, 'ROOT', root):
                spec = lambda recipe, redos=(): {'ad': 'my-ad', 'recipe': recipe, 'redos': list(redos)}   # noqa: E731
                for bad in (spec('ai-clips'),                       # beat 2 has no still yet
                            spec('ai-revise', [[1, 'clip', 'x']]),  # no clips at all yet
                            spec('ai-frames-revise'),               # needs a redo
                            spec('ai-frames', [[1, 'frame', 'x']]), # redos do not belong here
                            spec('raw')):                           # an AI plan
                    with self.assertRaises(SystemExit, msg=bad):
                        ctl.plan_job(bad, c, {}, {})
                with self.assertRaises(SystemExit):                 # an uncollected run of the same ad
                    ctl.plan_job(spec('ai-frames'), c, {'r': {'ad': 'my-ad', 'collected': False}}, {})
                with self.assertRaises(SystemExit):                 # worst case above the cap
                    ctl.plan_job(spec('ai'), {**c, 'kie_cap_per_ad': 100}, {}, {})
                job_ = ctl.plan_job(spec('ai-frames'), c, {}, {})
                self.assertEqual((job_['kie_tasks_planned'], job_['max_tasks'], job_['kie_worst'], 'skip' in job_), (1, 3, '25', False))
                (proj / 'VO').mkdir(); (proj / 'VO/vo.mp3').write_text('v')
                self.assertEqual(ctl.plan_job(spec('ai-frames'), c, {}, {})['skip'], ['vo'])
                with self.assertRaises(SystemExit):                 # never a second voice run
                    ctl.plan_job(spec('ai'), c, {}, {})

    def test_batch_file_and_batch_names(self):
        c = {**ctl.DEFAULTS}
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / 'b.json'
            f.write_text(json.dumps({'batch': 'Rug notes v3', 'jobs': [{'ad': 'a', 'recipe': 'raw'}, {'ad': 'b', 'recipe': 'ai-revise', 'redo': [[3, 'clip', 'slower']]},
                                                                      {'ad': 'c', 'recipe': 'raw', 'skip': True}]}))
            specs, batch = ctl.specs_from(['--from', str(f), '--go'], c)
            self.assertEqual((batch, [x['ad'] for x in specs], specs[1]['redos']), ('Rug notes v3', ['a', 'b'], [[3, 'clip', 'slower']]))
        specs, batch = ctl.specs_from(['raw', 'a,b,c', '--go', '--batch', 'Car hooks'], c)
        self.assertEqual((batch, len(specs)), ('Car hooks', 3))
        self.assertRegex(ctl.specs_from(['raw', 'a', '--go'], c)[1], r'^raw \d\d-\d\d \d\d\.\d\d$')
        for bad in (['raw', 'a,a', '--go'], ['nope', 'a', '--go'], ['raw', 'a', '--batch', 'x/../y'], ['raw', ','.join(f'ad{i}' for i in range(30))]):
            with self.assertRaises(SystemExit):
                ctl.specs_from(bad, c)

    def test_two_sessions_never_lose_each_others_runs(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(ctl, 'STATE', pathlib.Path(td)):
            with ctl.runs_locked() as runs:
                runs['a-raw-1'] = {'run': 'a-raw-1', 'ad': 'a', 'collected': False}
            stale = ctl.runs_load()                                # a second session read the registry here ...
            with ctl.runs_locked() as runs:
                runs['b-raw-2'] = {'run': 'b-raw-2', 'ad': 'b', 'collected': False}
            self.assertNotIn('b-raw-2', stale)
            ctl.run_update('a-raw-1', collected=True)              # ... and its single-run update keeps the other run
            self.assertEqual({k: v['collected'] for k, v in ctl.runs_load().items()}, {'a-raw-1': True, 'b-raw-2': False})
            self.assertEqual([r['run'] for r in ctl.pick_runs(['--batch', 'x'], {'1': {'run': '1', 'ad': 'a', 'batch': 'x'}, '2': {'run': '2', 'ad': 'b', 'batch': 'y'}})], ['1'])

    def test_checkpoint_saves_paid_work_in_an_order_that_cannot_rebill(self):
        with tempfile.TemporaryDirectory() as td:
            work, vol = pathlib.Path(td) / 'work', pathlib.Path(td) / 'vol'
            src, dst = work / 'projects/my-ad', vol / 'my-ad'
            (src / 'CLIPS').mkdir(parents=True); dst.mkdir(parents=True); (work / '.adjob').mkdir()
            (dst / 'plan.json').write_text('{}')
            (dst / ad_job.MANIFEST).write_text(json.dumps({'plan.json': {'sha256': 'old', 'size': 2}}))
            (src / 'CLIPS/clip_01.mp4').write_text('CLIP1')
            rows = [{'key': 'clip_01', 'taskId': 't1', 'state': 'submitted'},
                    {'key': 'clip_01', 'taskId': 't1', 'state': 'success', 'files': [str(src / 'CLIPS/clip_01.mp4')], 'creditsConsumed': 110},
                    {'key': 'clip_02', 'taskId': 't2', 'state': 'submitted'},
                    {'key': 'x', 'taskId': 't3', 'state': 'success', 'files': ['/etc/passwd']}]
            (src / 'jobs.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
            (work / '.adjob/tasks.jsonl').write_text('{}\n{}\n')
            commits = []
            self.assertEqual(ad_job.checkpoint(work, 'my-ad', lambda: commits.append(1), 'my-ad-ai-1795000000', vol), 3)
            self.assertEqual((dst / 'CLIPS/clip_01.mp4').read_text(), 'CLIP1')
            self.assertEqual((dst / 'jobs.jsonl').read_text(), (src / 'jobs.jsonl').read_text())   # the open task id t2 is saved
            self.assertEqual(len((dst / '.cloud/tasks-my-ad-ai-1795000000.jsonl').read_text().splitlines()), 2)
            manifest = json.loads((dst / ad_job.MANIFEST).read_text())
            self.assertEqual(sorted(manifest), ['.cloud/tasks-my-ad-ai-1795000000.jsonl', 'CLIPS/clip_01.mp4', 'jobs.jsonl', 'plan.json'])
            self.assertEqual(manifest['CLIPS/clip_01.mp4']['sha256'], ad_job.sha(src / 'CLIPS/clip_01.mp4'))
            self.assertFalse(list(dst.rglob('*.ckpt')))
            self.assertEqual((len(commits), ad_job.checkpoint(work, 'my-ad', lambda: commits.append(1), 'my-ad-ai-1795000000', vol), len(commits)), (1, 0, 1))
            self.assertEqual(ad_job.checkpoint(work, 'gone', None, None, vol), 0)

    def test_missing_beats_are_named(self):
        with tempfile.TemporaryDirectory() as td:
            _, proj = self.project(td, {'beats': [{'n': 1}, {'n': 2}, {'n': 3}]}, ['FRAMES/scene_01.png', 'FRAMES/scene_02_v3.png', 'FRAMES/scene_03_end.png', 'CLIPS/clip_02.mp4'])
            self.assertEqual((ad_job.beat_gaps(proj, 'frames'), ad_job.beat_gaps(proj, 'clips')), ([3], [1, 3]))
        self.assertTrue(ad_job.NOT_DELIVERED.search('credit before: 1\nFAIL clip_03 501 moderation\nNOT DONE: [\'clip_03\']'))
        self.assertFalse(ad_job.NOT_DELIVERED.search('OK clip_03 credits=110\nALL OK'))

    def test_a_note_time_lands_on_its_beat_or_shot(self):
        ai = {'beats': [{'n': 1, 'vo_start': 0.0, 'visual': 'dog on couch'}, {'n': 2, 'vo_start': 4.2, 'visual': 'mitt swipe'}]}
        self.assertEqual(ctl.time_to_place(ai, 6.0)[:2], ('beat', 2))
        raw = {'shots': [{'src': '/x/b.mp4', 'in': 2.0, 'at': 3.0, 'note': 'rug'}, {'src': '/x/a.mp4', 'in': 1, 'at': 0.0, 'note': 'vacuum'}]}
        self.assertEqual(ctl.time_to_place(raw, 2.9), ('shot', 0, 'a@1 vacuum'))
        self.assertEqual(ctl.time_to_place(raw, 6.47)[:2], ('shot', 1))
        self.assertIsNone(ctl.time_to_place({'beats': [{'n': 1}]}, 3.0))

    def test_status_words_and_next_steps(self):
        run = {'run': 'my-ad-ai-frames-1795000000', 'ad': 'my-ad', 'recipe': 'ai-frames'}
        self.assertIn('FRAMES READY', ctl.describe(run, {'state': 'done', 'steps': [{'stages': ['frames'], 'seconds': 80.0}]}))
        self.assertIn('ai-clips my-ad', ctl.next_step(run, {'state': 'done'}))
        self.assertIn('submit ai-frames my-ad', ctl.next_step(run, {'state': 'failed'}))
        ai = {'run': 'my-ad-ai-1795000000', 'ad': 'my-ad', 'recipe': 'ai'}
        self.assertIn('submit ai-resume my-ad', ctl.next_step(ai, {'state': 'failed'}))
        self.assertIn('not delivered: 3:clip', ctl.describe(ai, {'state': 'failed', 'steps': [{'stages': ['clips'], 'seconds': 9.0, 'failed': 'clips', 'not_done': ['3:clip']}]}))
        self.assertIn('PREFLIGHT', ctl.next_step(ai, {'state': 'done'}))
        self.assertIn('Mac checks PASS', ctl.summary_line({**ai, 'mac_gate': 'PASS'}, {'state': 'done'}))

    def test_clean_paid_failure_does_not_stop_everything_but_a_paid_crash_does(self):
        with tempfile.TemporaryDirectory() as td:
            b = Budget(pathlib.Path(td) / 'ledger.json', cap='5.00', stop='5.00', task='t')
            d = {'family': 'ads-ai-gen', 'paid_call': True, 'diagnostic_only': False}
            for key in ('a', 'b', 'c'):
                b.reserve(key, '0.10', 'function', d)
            b.finish('a', 'INCOMPLETE', '0.01', 1.0)
            b.finish('b', 'INCOMPLETE', '0.01', 1.0)
            self.assertFalse(json.loads(b.path.read_text())['global_stop'])
            with self.assertRaises(PermissionError):
                b.finish('c', 'FAILED', '0.10', 1.0)
            self.assertTrue(json.loads(b.path.read_text())['global_stop'])


class BudgetSettingTests(unittest.TestCase):
    def test_ledger_uses_its_own_cap_and_stop(self):
        with tempfile.TemporaryDirectory() as td:
            b = Budget(pathlib.Path(td) / 'ledger.json', cap='1.00', stop='0.50', task='t')
            d = {'family': 'f', 'paid_call': False, 'diagnostic_only': True}
            self.assertTrue(b.reserve('a', '0.20', 'function', d))
            self.assertTrue(b.reserve('b', '0.20', 'function', d))
            with self.assertRaises(PermissionError):
                b.reserve('c', '0.20', 'function', d)               # 0.60 would pass the 0.50 stop line
            b.finish('a', 'DONE', '0.01', 1.0)
            self.assertTrue(b.reserve('c', '0.20', 'function', d))  # finished calls count what they used
            with self.assertRaises(ValueError):
                Budget(pathlib.Path(td) / 'other.json', cap='1.00', stop='2.00')


class ShotCheckTests(unittest.TestCase):
    def setUp(self):
        import shot_check
        self.S = shot_check
        self.rows = [{'i': i, 'key': k, 'at': float(i), 'said': 'line', 'note': 'n'} for i, k in enumerate(['clipA@1.0', 'clipB@2.0', 'clipC@3.0'])]

    def test_parse_keeps_only_well_formed_verdicts(self):
        got = self.S.parse('noise {"shots": [{"i": 0, "ok": true}, {"i": 1, "ok": false, "severity": "block", "rule": "T08", "issue": "dog face", '
                           '"shows": "a dog", "clip_fault": false}, {"i": "2", "ok": false}, {"i": 2, "ok": false, "severity": "odd", "clip_fault": true}]} trailing')
        self.assertEqual(sorted(got), [0, 1, 2])
        self.assertEqual((got[0]['ok'], got[0]['severity'], got[0]['clip_fault']), (True, '', False))
        self.assertEqual((got[1]['severity'], got[1]['rule']), ('block', 'T08'))
        self.assertEqual((got[2]['severity'], got[2]['clip_fault']), ('minor', True))

    def test_block_needs_a_fix_or_an_acknowledgement(self):
        v = {0: {'ok': True, 'severity': '', 'rule': '', 'issue': '', 'shows': ''},
             1: {'ok': False, 'severity': 'block', 'rule': 'T08', 'issue': 'dog face', 'shows': ''},
             2: {'ok': False, 'severity': 'minor', 'rule': 'T40', 'issue': 'late', 'shows': ''}}
        issues, blocking = self.S.decide(self.rows, v, {})
        self.assertEqual(([x['i'] for x in issues], [x['i'] for x in blocking]), ([1, 2], [1]))
        issues, blocking = self.S.decide(self.rows, v, {'clipB@2.0': 'only golden retriever clip we have'})
        self.assertEqual((len(issues), blocking), (2, []))

    def test_a_shot_with_no_verdict_blocks(self):
        issues, blocking = self.S.decide(self.rows, {0: {'ok': True, 'severity': '', 'rule': '', 'issue': '', 'shows': ''}}, {})
        self.assertEqual([x['i'] for x in blocking], [1, 2])

    def test_rows_pair_each_shot_with_its_own_words_and_find_the_reveal(self):
        plan = {'shots': [{'src': '/x/a.mp4', 'in': 1, 'at': 0.0, 'note': 'pro cleaner (blue towels)'},
                          {'src': '/x/b.mp4', 'in': 2.26, 'at': 2.0, 'note': 'carpet, no product'},
                          {'src': '/x/c.mp4', 'in': 0, 'at': 4.0, 'speed': 1.5, 'note': 'product reveal'}]}
        words = [(0.1, 'Ask'), (1.0, 'anyone.'), (2.05, 'Hair'), (3.9, 'stays.'), (3.95, 'Then'), (5.0, 'this.')]
        rows, reveal = self.S.rows_of(plan, words, 6.0)
        self.assertEqual(reveal, 2)
        self.assertEqual([r['said'] for r in rows], ['Ask anyone.', 'Hair stays.', 'Then this.'])
        self.assertEqual([r['key'] for r in rows], ['a@1.0', 'b@2.3', 'c@0.0'])
        self.assertEqual(rows[2]['slot'], 2.0)
        self.assertEqual(self.S.rows_of({**plan, 'reveal_shot': 1}, words, 6.0)[1], 1)
        self.assertNotEqual(self.S.fingerprint(rows, 'm'), self.S.fingerprint(rows[:2], 'm'))


if __name__ == '__main__':
    unittest.main()
