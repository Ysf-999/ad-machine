"""Owner taste rules reach every automatic checker: tools/taste_rules.py, the per-shot cache in shot_check,
and the rules block / model / effort of master_qc, plan_review, vision_qc, frame_check, product_check; feedback.py repeats.
No network: every Claude client here is a fake."""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools')]
import taste_rules as TR  # noqa: E402

REAL = json.loads((ROOT / 'feedback/taste_rules.json').read_text())


def rule(i, text, stages=None, **kw):
    r = {'id': i, 'group': 'g', 'title': f'title {i}', 'rule': text, 're': i.lower(), **kw}
    if stages is not None:
        r['stages'] = stages
    return r


class RulesFile:
    """A temporary taste_rules.json, swapped in as the default path of taste_rules (and taste_tags)."""
    def __init__(self, rules):
        self.td = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.td.name) / 'taste_rules.json'
        self.write(rules)

    def write(self, rules):
        self.path.write_text(json.dumps({'_about': 'test', 'rules': rules}, indent=1))
        TR._cache.clear()

    def __enter__(self):
        self.patch = mock.patch.object(TR, 'TASTE', self.path); self.patch.start(); TR._cache.clear()
        return self

    def __exit__(self, *a):
        self.patch.stop(); TR._cache.clear(); self.td.cleanup()


class FakeClient:
    """Records every request; answers with `reply(kw)` (a string) or the default."""
    def __init__(self, reply=None, fail=lambda kw: False):
        self.calls, self.reply, self.fail = [], reply, fail
        outer = self

        class Stream:
            def __init__(self, kw): self.kw = kw
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get_final_message(self): return outer._answer(self.kw)

        class Messages:
            def create(self, **kw): return outer._answer(kw)
            def stream(self, **kw): return Stream(kw)
        self.messages = Messages()

    def _answer(self, kw):
        self.calls.append(kw)
        if self.fail(kw):
            raise RuntimeError('network down')
        text = self.reply(kw) if self.reply else 'VERDICT: SHIP'
        return types.SimpleNamespace(content=[types.SimpleNamespace(type='text', text=text)], stop_reason='end_turn')


def fake_module(client):
    return types.SimpleNamespace(Anthropic=lambda **kw: client, BadRequestError=type('BadRequestError', (Exception,), {}))


class TasteRulesTests(unittest.TestCase):
    def test_rule_without_stages_reaches_every_stage_and_empty_list_none(self):
        with RulesFile([rule('T01', 'all of them'), rule('T02', 'process', []), rule('T03', 'audio', ['plan', 'master'])]):
            for st in TR.STAGES:
                ids = [r['id'] for r in TR.for_stage(st)]
                self.assertIn('T01', ids)
                self.assertNotIn('T02', ids)
                self.assertEqual('T03' in ids, st in ('plan', 'master'))
            with self.assertRaises(ValueError):
                TR.for_stage('frames')

    def test_prompt_block_lines_and_even_shortening(self):
        with RulesFile([rule('T08', 'Every visual matches the line.  It is literal.', ['shot']), rule('T09', 'x' * 3000, ['shot']),
                        rule('T10', 'never here', ['plan'])]):
            b = TR.prompt_block('shot')
            self.assertIn('- T08 title T08: Every visual matches the line. It is literal.', b)
            self.assertNotIn('T10', b)
            short = TR.prompt_block('shot', max_chars=900)
            self.assertLessEqual(len(short), 1000)
            self.assertIn('T08 title T08', short); self.assertIn('T09 title T09', short)   # every rule keeps its line
            self.assertEqual(TR.prompt_block('still'), '')

    def test_stage_hash_follows_only_that_stages_rules(self):
        with RulesFile([rule('T01', 'a', ['shot']), rule('T02', 'b', ['plan'])]) as f:
            shot, plan = TR.stage_hash('shot'), TR.stage_hash('plan')
            f.write([rule('T01', 'a', ['shot']), rule('T02', 'b changed', ['plan'])])
            self.assertEqual(TR.stage_hash('shot'), shot)
            self.assertNotEqual(TR.stage_hash('plan'), plan)
            f.write([rule('T01', 'a', ['shot']), rule('T02', 'b changed', ['plan']), rule('T03', 'new rule, no stages')])
            self.assertNotEqual(TR.stage_hash('shot'), shot)   # a rule added tomorrow reaches the shot check too

    def test_coverage_joins_enforced_by_and_stage_checkers(self):
        r = rule('T13', 't', ['still', 'clip', 'master'], enforced_by=['preflight'])
        self.assertEqual(TR.checkers_of(r), ['vision_qc', 'master_qc'])
        self.assertEqual(TR.coverage(r), ['preflight', 'vision_qc', 'master_qc'])
        self.assertEqual(TR.coverage(rule('T27', 't', [])), [])
        self.assertEqual(TR.checkers_of(rule('T99', 't')), ['plan_review', 'shot_check', 'vision_qc', 'master_qc'])

    def test_real_file_is_classified_and_additive(self):
        rules = REAL['rules']
        self.assertGreaterEqual(len(rules), 51)
        for r in rules:
            self.assertTrue({'id', 'group', 'title', 'rule', 're'} <= set(r), r['id'])
            self.assertTrue(set(r.get('stages', [])) <= set(TR.STAGES), r['id'])
            self.assertTrue(set(r.get('enforced_by', [])) <= {'preflight', 'shot_check', 'master_qc', 'vision_qc', 'plan_review'}, r['id'])
        by = {r['id']: r for r in rules}
        for pid in ('T27', 'T28', 'T29', 'T30', 'T32'):
            self.assertEqual(by[pid]['stages'], [], pid)
        self.assertIn('shot', by['T08']['stages']); self.assertIn('shot', by['T31']['stages'])
        self.assertEqual(by['T21']['stages'], ['plan', 'master'])
        self.assertIn('preflight', by['T13']['enforced_by']); self.assertIn('preflight', by['T06']['enforced_by'])
        for r in rules:   # stored LLM checkers match what the stages imply
            self.assertEqual([c for c in r.get('enforced_by', []) if c != 'preflight'], TR.checkers_of(r), r['id'])
        backup = ROOT / 'tools/_backup_2026-11-22/taste_rules.json'
        if backup.exists():   # never renumbered or deleted; reworded only through `feedback.py taste-edit` (old wording kept in 'was')
            old = {r['id']: r for r in json.loads(backup.read_text())['rules']}
            for i, r in old.items():
                kept = [w['rule'] for w in by[i].get('was', [])]
                skip = {'rule', 'was'} if r['rule'] != by[i]['rule'] and r['rule'] in kept else set()
                self.assertEqual({k: by[i][k] for k in r if k not in skip}, {k: v for k, v in r.items() if k not in skip}, i)


class ShotCacheTests(unittest.TestCase):
    def setUp(self):
        import shot_check
        self.S = shot_check
        self.td = tempfile.TemporaryDirectory()
        self.jpg = pathlib.Path(self.td.name) / 'f.jpg'; self.jpg.write_bytes(b'\xff\xd8' + b'0' * 600)
        self.missing = set()
        self.grab = mock.patch.object(shot_check, 'grab', lambda row, td: [] if row['key'] in self.missing else [self.jpg, self.jpg, self.jpg])
        self.grab.start()
        self.rows = [{'i': i, 'key': f'clip{i}@{i}.0', 'src': f'/x/clip{i}.mp4', 'in': float(i), 'speed': 1.0, 'slot': 2.0,
                      'at': 2.0 * i, 'said': f'line {i}', 'note': f'note {i}'} for i in range(10)]

    def tearDown(self):
        self.grab.stop(); self.td.cleanup()

    @staticmethod
    def answer(kw, bad=()):
        text = kw['messages'][0]['content'][-1]['text']
        import re
        ids = [int(x) for x in re.findall(r'^SHOT (\d+) ', text, re.M)]
        return json.dumps({'shots': [{'i': i, 'ok': i not in bad, 'severity': '' if i not in bad else 'block', 'rule': 'T08',
                                      'issue': '' if i not in bad else 'wrong subject', 'shows': 'a rug', 'clip_fault': False} for i in ids]})

    def run_check(self, old, client, **kw):
        return self.S.check_rows(self.rows, 5, 'claude-opus-5-5', old, client=client, td=self.td.name, **kw)

    def test_first_run_asks_second_reuses_one_note_change_asks_one(self):
        c = FakeClient(self.answer)
        v, cache, keys, st = self.run_check({}, c)
        self.assertEqual((len(c.calls), st['asked'], st['reused']), (2, 10, 0))   # 10 shots, batches of 8
        old = {'cache': cache}
        c2 = FakeClient(self.answer)
        v2, cache2, _, st2 = self.run_check(old, c2)
        self.assertEqual((len(c2.calls), st2['reused']), (0, 10))
        self.assertEqual(v2, v)
        self.rows[3]['note'] = 'pet hair on the rug, close'
        c3 = FakeClient(self.answer)
        v3, cache3, keys3, st3 = self.run_check({'cache': cache2}, c3)
        self.assertEqual((len(c3.calls), st3['asked'], st3['reused']), (1, 1, 9))
        self.assertIn('SHOT 3 ', c3.calls[0]['messages'][0]['content'][-1]['text'])
        self.assertNotIn('SHOT 4 ', c3.calls[0]['messages'][0]['content'][-1]['text'])
        self.assertEqual(len([k for k in keys3 if k not in keys]), 1)

    def test_request_carries_rules_block_and_medium_effort(self):
        c = FakeClient(self.answer)
        self.run_check({}, c)
        kw = c.calls[0]
        self.assertEqual(kw['output_config'], {'effort': 'medium'})
        self.assertTrue(kw['system'].startswith(self.S.SYSTEM))   # fixed severity guidance kept, rules after it
        self.assertIn(TR.prompt_block('shot'), kw['system'])
        self.assertIn('T08 B-roll matches the line literally', kw['system'])

    def test_every_key_part_invalidates_only_that_shot(self):
        base = [self.S.shot_key(r, 5, 'm', 'h') for r in self.rows]
        for field, val in (('speed', 1.5), ('slot', 3.0), ('said', 'other words'), ('note', 'other'), ('key', 'other@1.0')):
            rows = [dict(r) for r in self.rows]; rows[2][field] = val
            got = [self.S.shot_key(r, 5, 'm', 'h') for r in rows]
            self.assertEqual([i for i in range(10) if got[i] != base[i]], [2], field)
        self.assertEqual([i for i, r in enumerate(self.rows) if self.S.shot_key(r, 4, 'm', 'h') != base[i]], [4, 5])   # reveal moved
        self.assertNotEqual(self.S.shot_key(self.rows[0], 5, 'other-model', 'h'), base[0])
        self.assertNotEqual(self.S.shot_key(self.rows[0], 5, 'm', 'new-rules'), base[0])

    def test_rules_change_re_asks_everything(self):
        c = FakeClient(self.answer)
        _, cache, _, _ = self.run_check({}, c)
        with mock.patch.object(TR, 'stage_hash', lambda stage, path=None: 'rules-changed'):
            c2 = FakeClient(self.answer)
            _, _, _, st = self.run_check({'cache': cache}, c2)
        self.assertEqual((st['asked'], st['reused']), (10, 0))

    def test_force_re_asks_everything(self):
        _, cache, _, _ = self.run_check({}, FakeClient(self.answer))
        c = FakeClient(self.answer)
        _, _, _, st = self.run_check({'cache': cache}, c, force=True)
        self.assertEqual((len(c.calls), st['asked']), (2, 10))

    def test_missing_verdict_is_not_cached_and_asked_again(self):
        def partial(kw):   # the reply leaves out shot 1
            d = json.loads(self.answer(kw)); d['shots'] = [x for x in d['shots'] if x['i'] != 1]; return json.dumps(d)
        v, cache, keys, st = self.run_check({}, FakeClient(partial))
        self.assertNotIn(1, v); self.assertNotIn(keys[1], cache); self.assertEqual(st['asked'], 9)
        issues, blocking = self.S.decide(self.rows, v, {})
        self.assertEqual([b['i'] for b in blocking], [1])   # still blocks as "not checked"
        c = FakeClient(self.answer)
        v2, _, _, st2 = self.run_check({'cache': cache}, c)
        self.assertEqual((len(c.calls), st2['asked'], st2['reused']), (1, 1, 9))
        self.assertIn(1, v2)

    def test_shot_without_frames_is_not_sent_and_not_cached(self):
        self.missing.add('clip2@2.0')
        c = FakeClient(self.answer)
        v, cache, keys, st = self.run_check({}, c)
        self.assertEqual((v[2]['severity'], v[2]['clip_fault'], st['no_frames']), ('block', False, 1))
        self.assertNotIn(keys[2], cache)
        self.assertFalse(any('SHOT 2 ' in k['messages'][0]['content'][-1]['text'] for k in c.calls))
        self.missing.clear()
        c2 = FakeClient(self.answer)
        v2, _, _, st2 = self.run_check({'cache': cache}, c2)
        self.assertEqual((st2['asked'], v2[2]['ok']), (1, True))

    def test_a_failed_call_keeps_the_other_batches(self):
        c = FakeClient(self.answer, fail=lambda kw: 'SHOT 0 ' in kw['messages'][0]['content'][-1]['text'])
        with contextlib.redirect_stderr(io.StringIO()):
            v, cache, keys, st = self.run_check({}, c)
        self.assertEqual((st['failed_calls'], st['asked']), (1, 2))   # shots 8, 9 came back, 0-7 failed
        self.assertEqual(sorted(v), [8, 9])
        self.assertEqual(len(cache), 2)

    def test_verdict_for_a_shot_not_in_the_batch_is_ignored(self):
        def extra(kw):
            d = json.loads(self.answer(kw)); d['shots'].append({'i': 99, 'ok': True}); return json.dumps(d)
        v, _, _, _ = self.run_check({}, FakeClient(extra))
        self.assertNotIn(99, v)

    def test_report_keeps_the_fields_ctl_and_docs_read(self):
        v, cache, keys, st = self.run_check({}, FakeClient(lambda kw: self.answer(kw, bad=(4,))))
        issues, blocking = self.S.decide(self.rows, v, {})
        proj = pathlib.Path(self.td.name)
        fp = self.S.fingerprint(self.rows, 'claude-opus-5-5', 5, 'h')
        self.S.report(proj, self.rows, v, issues, blocking, fp, 'claude-opus-5-5', cache, keys, st)
        d = json.loads((proj / 'SHOT_CHECK.json').read_text())
        for k in ('fingerprint', 'model', 'shots', 'verdicts', 'issues', 'blocking', 'cache', 'shot_keys'):
            self.assertIn(k, d)
        self.assertEqual(d['blocking'], ['clip4@4.0'])
        self.assertEqual([x['key'] for x in d['issues']], ['clip4@4.0'])
        from cloud import ctl
        self.assertEqual(ctl.flag_rows(d['issues']), [])   # clip_fault false: a wrong pick for a line never flags the footage
        self.assertEqual(ctl.flag_rows([{**d['issues'][0], 'key': 'A' * 24 + '@4.0', 'clip_fault': True}])[0]['issue'], 'T08 wrong subject')
        # the cache written to disk is what the next run reads
        c = FakeClient(self.answer)
        _, _, _, st2 = self.S.check_rows(self.rows, 5, 'claude-opus-5-5', d, client=c, td=self.td.name)
        self.assertEqual((len(c.calls), st2['reused']), (0, 10))
        self.assertIn('**BLOCK** shot 4', (proj / 'SHOT_CHECK.md').read_text())

    def test_fingerprint_now_covers_notes_reveal_and_rules(self):
        f = self.S.fingerprint
        self.assertNotEqual(f(self.rows, 'm', 5, 'h'), f(self.rows, 'm', 4, 'h'))
        self.assertNotEqual(f(self.rows, 'm', 5, 'h'), f(self.rows, 'm', 5, 'h2'))
        rows = [dict(r) for r in self.rows]; rows[0]['note'] = 'changed'
        self.assertNotEqual(f(self.rows, 'm', 5, 'h'), f(rows, 'm', 5, 'h'))


class CheckerPromptTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.proj = pathlib.Path(self.td.name) / 'ad1'
        self.proj.mkdir()
        (self.proj / 'plan.json').write_text(json.dumps({'ad': 'ad1', 'style': 'claymation', 'characters': {},
                                                         'beats': [{'n': 1, 'vo': 'Dog hair everywhere.', 'visual': 'a hairy couch'}]}))
        from PIL import Image
        self.img = self.proj / 'img.png'
        Image.new('RGB', (64, 64), 'white').save(self.img)

    def tearDown(self):
        self.td.cleanup()

    def test_master_qc_opus_medium_rules_no_halloween(self):
        import master_qc as M
        c = FakeClient(lambda kw: 'VERDICT: SHIP\nSCORE: 9/10\nFIX LIST:\n')
        (self.proj / 'MASTER.mp4').write_bytes(b'0')
        with mock.patch.object(M, 'anthropic', fake_module(c)), mock.patch.object(M, 'transcript', lambda mp4: '[0.0-1.0] Dog hair everywhere.'), \
                mock.patch.object(M, 'sheets', lambda mp4, tmp: [(0.0, b'\xff\xd8jpeg')]), \
                mock.patch.object(M.subprocess, 'run', lambda *a, **k: types.SimpleNamespace(stdout='LUFS -14', returncode=0)), \
                mock.patch.object(sys, 'argv', ['master_qc.py', str(self.proj)]), contextlib.redirect_stdout(io.StringIO()):
            M.main()
        kw = c.calls[0]
        self.assertEqual((kw['model'], kw['output_config']), ('claude-opus-5-5', {'effort': 'medium'}))
        prompt = kw['messages'][0]['content'][-1]['text']
        self.assertNotIn('HALLOWEEN', prompt.upper())
        self.assertIn(TR.prompt_block('master'), prompt)
        self.assertIn('Output format (plain text):\nVERDICT: SHIP or FIX\nSCORE: n/10', prompt)   # format unchanged
        self.assertIn('VERDICT: SHIP', (self.proj / 'QC/master_qc.md').read_text())

    def test_plan_review_keeps_opus_high_and_adds_plan_rules(self):
        import plan_review as P
        c = FakeClient(lambda kw: json.dumps({'beats': [{'n': 1, 'issues': [], 'visual': 'a hairy couch'}], 'summary': 'ok'}))
        with mock.patch.object(P, 'anthropic', fake_module(c)), mock.patch.object(sys, 'argv', ['plan_review.py', str(self.proj)]), \
                contextlib.redirect_stdout(io.StringIO()):
            P.main()
        kw = c.calls[0]
        self.assertEqual((kw['model'], kw['output_config']), ('claude-opus-5-5', {'effort': 'high'}))
        self.assertTrue(kw['system'].startswith(P.SYSTEM))
        self.assertIn(TR.prompt_block('plan'), kw['system'])
        self.assertIn('T31', kw['system'])

    def test_vision_qc_stills_and_clips_get_their_own_rules(self):
        import vision_qc as V
        c = FakeClient(lambda kw: '{"verdict": "PASS", "defects": [], "severity": "none"}')
        with mock.patch.object(V, 'anthropic', fake_module(c)), contextlib.redirect_stdout(io.StringIO()):
            r1 = V.check(c, 'claude-opus-5-5', [self.img], 'ctx', 'still')
            r2 = V.check(c, 'claude-opus-5-5', [self.img], 'ctx', 'clip')
        self.assertEqual((r1['verdict'], r2['verdict']), ('PASS', 'PASS'))
        self.assertIn(TR.prompt_block('still'), c.calls[0]['system'])
        self.assertIn(TR.prompt_block('clip'), c.calls[1]['system'])
        self.assertIn('T43', c.calls[0]['system']); self.assertNotIn('T43 ', c.calls[1]['system'])   # T43 = statics only
        self.assertIn('T41', c.calls[1]['system']); self.assertNotIn('- T41 ', c.calls[0]['system'])
        self.assertEqual(c.calls[0]['output_config'], {'effort': 'medium'})

    def test_vision_qc_main_defaults_to_opus_and_keeps_the_model_flag(self):
        import vision_qc as V
        (self.proj / 'FRAMES').mkdir()
        from PIL import Image
        Image.new('RGB', (64, 64), 'white').save(self.proj / 'FRAMES/scene_01.png')
        for argv, want in (([str(self.proj), '--stage', 'frames'], 'claude-opus-5-5'),
                           ([str(self.proj), '--stage', 'frames', '--model', 'claude-haiku-5-5'], 'claude-haiku-5-5')):
            c = FakeClient(lambda kw: '{"verdict": "FAIL", "defects": ["T10 fluff on top"], "severity": "major"}')
            with mock.patch.object(V, 'anthropic', fake_module(c)), mock.patch.object(sys, 'argv', ['vision_qc.py'] + argv), \
                    contextlib.redirect_stdout(io.StringIO()):
                V.main()
            self.assertEqual(c.calls[0]['model'], want)
            self.assertIn('- T10 ', c.calls[0]['system'])
            rep = json.loads((self.proj / 'QC/qc_report.json').read_text())
            self.assertEqual((rep[0]['kind'], rep[0]['verdict']), ('frame', 'FAIL'))

    def test_frame_and_product_check_default_opus_medium(self):
        import frame_check as F, product_check as G
        for mod, argv in ((F, ['frame_check.py', str(self.img), 'a hairy couch']), (G, ['product_check.py', str(self.img)])):
            c = FakeClient(lambda kw: 'VERDICT PASS')
            refs = mock.patch.object(mod, 'photos', lambda: [self.img]) if hasattr(mod, 'photos') else contextlib.nullcontext()
            with mock.patch.object(mod, 'anthropic', fake_module(c)), mock.patch.object(sys, 'argv', argv), refs, \
                    contextlib.redirect_stdout(io.StringIO()):
                mod.main()
            self.assertEqual((c.calls[0]['model'], c.calls[0]['output_config']), ('claude-opus-5-5', {'effort': 'medium'}), mod.__name__)


class FeedbackRulesTests(unittest.TestCase):
    def setUp(self):
        import feedback, taste_tags
        self.F, self.T = feedback, taste_tags
        self.td = tempfile.TemporaryDirectory()
        d = pathlib.Path(self.td.name)
        self.rules = d / 'taste_rules.json'
        self.rules.write_text(json.dumps({'_about': 'x', 'rules': [rule('T01', 'old', ['plan'], added='2026-11-10', **{'from': [1]}),
                                                                    rule('T02', 'no stages')]}, indent=1))
        self.log = d / 'log.jsonl'
        notes = [{'id': 1, 'ad': 'a', 'ts': '2026-11-10T09:00', 'text': 't01', 'taste': ['T01'], 'status': 'learned'},
                 {'id': 2, 'ad': 'a', 'ts': '2026-11-10T10:00', 'text': 't01', 'taste': ['T01'], 'status': 'learned'},   # same day as added
                 {'id': 3, 'ad': 'b', 'ts': '2026-11-12T10:00', 'text': 't01', 'taste': ['T01'], 'status': 'learned'},
                 {'id': 4, 'ad': 'c', 'ts': '2026-11-14T10:00', 'text': 't01 t02', 'taste': ['T01', 'T02'], 'status': 'dismissed'},
                 {'id': 5, 'ad': 'c', 'ts': '2026-11-16T10:00', 'text': 'liked t01', 'taste': ['T01'], 'status': 'like'},
                 {'id': 6, 'ad': 'd', 'ts': '2026-11-20T10:00', 'text': 't02', 'taste': ['T02'], 'status': 'learned'}]
        self.log.write_text(''.join(json.dumps(n) + '\n' for n in notes))
        self.patches = [mock.patch.object(self.T, 'TASTE', self.rules), mock.patch.object(TR, 'TASTE', self.rules),
                        mock.patch.object(self.F, 'LOG', self.log), mock.patch.object(self.F, 'TASTE_MD', d / 'OWNER_TASTE.md')]
        for p in self.patches:
            p.start()
        TR._cache.clear(); self.T._cache.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        TR._cache.clear(); self.T._cache.clear(); self.td.cleanup()

    def test_repeats_counts_only_after_the_rule_was_added(self):
        got = {x['id']: x for x in self.F.repeats()}
        self.assertEqual((got['T01']['repeats'], got['T01']['ads'], got['T01']['latest'], got['T01']['note_ids']), (2, 2, '2026-11-14', [3, 4]))
        self.assertEqual((got['T02']['added'], got['T02']['repeats'], got['T02']['note_ids']), (TR.BUILT, 1, [6]))   # no 'added' = built day
        self.assertEqual(got['T01']['checked_by'], ['plan_review'])
        self.assertEqual(got['T02']['checked_by'], ['plan_review', 'shot_check', 'vision_qc', 'master_qc'])
        self.assertEqual([x['id'] for x in self.F.repeats()], ['T01', 'T02'])

    def test_repeats_json_and_text_are_read_only(self):
        before = (self.log.read_text(), self.rules.read_text())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.F.cmd_repeats(as_json=True)
        d = json.loads(buf.getvalue())
        self.assertEqual([x['id'] for x in d['rules']], ['T01', 'T02'])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.F.cmd_repeats()
        self.assertIn('T01', out.getvalue())
        self.assertEqual((self.log.read_text(), self.rules.read_text()), before)

    def test_taste_add_takes_stages_and_edit_keeps_them(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.F.cmd_taste_add('New one', 'never do x', r'\bxyz\b', stages='master,plan')
            self.F.cmd_taste_add('All stages', 'never do y', r'\byyy\b')
            self.F.cmd_taste_edit('T01', 'newer owner wording')
        d = {r['id']: r for r in json.loads(self.rules.read_text())['rules']}
        self.assertEqual(d['T03']['stages'], ['plan', 'master'])
        self.assertNotIn('stages', d['T04'])
        self.assertEqual((d['T01']['stages'], d['T01']['rule'], d['T01']['from']), (['plan'], 'newer owner wording', [1]))
        TR._cache.clear()
        self.assertIn('T03', [r['id'] for r in TR.for_stage('master')])
        self.assertNotIn('T03', [r['id'] for r in TR.for_stage('shot')])
        self.assertIn('T04', [r['id'] for r in TR.for_stage('shot')])
        with self.assertRaises(SystemExit):
            self.F.parse_stages('plan,frames')


if __name__ == '__main__':
    unittest.main()
