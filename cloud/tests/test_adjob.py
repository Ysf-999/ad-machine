"""Offline tests for the cloud ad-job launcher and runner (no Modal, no network, no secrets)."""
import json
import os
import pathlib
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

CLOUD = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLOUD / 'worker'))
import adjob_boot  # noqa: E402
import ad_job  # noqa: E402


class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {'code': 200, 'data': {'taskId': 't1'}}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')

    def json(self):
        return self._data


def fake_kie(calls, fail=False):
    httpx = types.SimpleNamespace(request=lambda m, u, **kw: calls.append((m, u)) or FakeResp(500 if fail else 200))
    mod = types.SimpleNamespace(httpx=httpx, _h=lambda: {'Authorization': 'Bearer x'})
    mod._req = lambda m, u, **kw: [calls.append(('retry', u)) for _ in range(3)] and FakeResp().json()
    return mod


class AdJobBootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        adjob_boot.STATE = pathlib.Path(self.tmp.name) / '.adjob'

    def test_post_sent_exactly_once_even_on_error(self):
        calls = []
        mod = fake_kie(calls, fail=True)
        adjob_boot.patch_kie(mod)
        with mock.patch.dict(os.environ, {'ADJOB_MAX_TASKS': '5'}):
            with self.assertRaises(RuntimeError):
                mod._req('POST', 'https://api.kie.ai/api/v1/jobs/createTask', json={'model': 'm'})
        self.assertEqual([c for c in calls if c[0] == 'POST'], [('POST', 'https://api.kie.ai/api/v1/jobs/createTask')])
        self.assertFalse(any(c[0] == 'retry' for c in calls))

    def test_get_keeps_original_retry_path(self):
        calls = []
        mod = fake_kie(calls)
        adjob_boot.patch_kie(mod)
        mod._req('GET', 'https://api.kie.ai/api/v1/jobs/recordInfo')
        self.assertEqual(sum(c[0] == 'retry' for c in calls), 3)

    def test_task_cap_refuses_before_post(self):
        calls = []
        mod = fake_kie(calls)
        adjob_boot.patch_kie(mod)
        url = 'https://api.kie.ai/api/v1/jobs/createTask'
        with mock.patch.dict(os.environ, {'ADJOB_MAX_TASKS': '2'}):
            mod._req('POST', url, json={'model': 'a'})
            mod._req('POST', url, json={'model': 'b'})
            with self.assertRaises(RuntimeError):
                mod._req('POST', url, json={'model': 'c'})
        self.assertEqual(sum(c[0] == 'POST' for c in calls), 2)

    def test_mlx_shim_installed(self):
        adjob_boot._install_mlx_shim()
        self.assertTrue(callable(sys.modules['mlx_whisper'].transcribe))


    def test_whisper_model_is_loaded_once_per_settings(self):
        built = []

        class Model:
            def __init__(self, *a, **k):
                built.append((a, k))
        fake = types.SimpleNamespace(WhisperModel=Model)
        with mock.patch.dict(sys.modules, {'faster_whisper': fake}):
            adjob_boot._keep_whisper_model_loaded()
            adjob_boot._keep_whisper_model_loaded()   # a second install changes nothing
            a = fake.WhisperModel('/m', device='cpu', compute_type='int8', local_files_only=True)
            b = fake.WhisperModel('/m', device='cpu', compute_type='int8', local_files_only=True)
            c = fake.WhisperModel('/m', device='cpu', compute_type='int8', local_files_only=True, cpu_threads=2)
        self.assertIs(a, b)
        self.assertIsNot(a, c)
        self.assertEqual(len(built), 2)


class AdJobRunnerTests(unittest.TestCase):
    def test_validate(self):
        self.assertEqual(ad_job.validate({'ad': 'cloud-test-01', 'stages': ['vo'], 'max_tasks': 6}), ('cloud-test-01', ['vo']))
        for bad in ({'ad': '../x', 'stages': ['vo']}, {'ad': 'a', 'stages': ['rm']}, {'ad': 'a', 'stages': ['vo'], 'max_tasks': 99}):
            with self.assertRaises(ValueError):
                ad_job.validate(bad)

    def test_redactor_hides_secret_values(self):
        with mock.patch.dict(os.environ, {'KIE_API_KEY': 'synthetic-secret-123456', 'PATH': '/bin'}, clear=True):
            safe = ad_job.redactor()
        self.assertEqual(safe('key synthetic-secret-123456 end'), 'key [REDACTED] end')

    def test_credits_sums_finished_tasks_only(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td)
            (p / 'jobs.jsonl').write_text('\n'.join(json.dumps(x) for x in [
                {'key': 'a', 'state': 'submitted'}, {'key': 'a', 'state': 'success', 'creditsConsumed': 18.0},
                {'key': 'b', 'state': 'fail'}, {'key': 'c', 'state': 'success', 'creditsConsumed': 90.8}]))
            self.assertEqual(ad_job.credits(p), (108.8, 2))


class RawEditPatchTests(unittest.TestCase):
    def test_loudnorm_mix_gets_48k_and_voice_pad(self):
        seen = []
        mod = types.SimpleNamespace(sh=lambda *a, **k: seen.append(list(a)))
        adjob_boot.patch_rawedit(mod)
        mod.sh('ffmpeg', '-filter_complex', '[0:a]highpass=f=80,loudnorm=I=-16[a]', '-c:a', 'aac', 'out.mp4')
        mod.sh('ffmpeg', '-i', 'x.mp4', '-c:a', 'aac', 'y.mp4')   # no loudnorm: untouched
        self.assertIn('[0:a]apad=pad_dur=0.6,highpass', seen[0][2])
        self.assertEqual(seen[0][3:6], ['-ar', '48000', '-c:a'])
        self.assertEqual(seen[1], ['ffmpeg', '-i', 'x.mp4', '-c:a', 'aac', 'y.mp4'])


    def test_whisper_results_are_remembered_by_audio_settings_and_model(self):
        with tempfile.TemporaryDirectory() as td:
            td = pathlib.Path(td); folder = td / 'SEGMENTS' / '_whisper'
            wav = td / '_beat.wav'; wav.write_bytes(b'RIFF-one')
            ran = []

            def run():
                ran.append(1)
                return {'text': ' hi', 'segments': [{'start': 0.0, 'end': 0.48, 'words': [{'word': ' hi', 'start': 0.12, 'end': 0.4800000000000001}]}]}
            first = adjob_boot._cached_transcribe(wav, {'beam_size': 1, 'initial_prompt': 'hi'}, run, folder, 'model-a')
            again = adjob_boot._cached_transcribe(wav, {'initial_prompt': 'hi', 'beam_size': 1}, run, folder, 'model-a')
            self.assertEqual(first, again)   # exact floats back
            self.assertEqual(len(ran), 1)
            adjob_boot._cached_transcribe(wav, {'beam_size': 1, 'initial_prompt': 'other words'}, run, folder, 'model-a')   # other settings
            adjob_boot._cached_transcribe(wav, {'beam_size': 1, 'initial_prompt': 'hi'}, run, folder, 'model-b')            # other model
            wav.write_bytes(b'RIFF-two')
            adjob_boot._cached_transcribe(wav, {'beam_size': 1, 'initial_prompt': 'hi'}, run, folder, 'model-a')            # other audio
            self.assertEqual(len(ran), 4)
            for f in folder.glob('*.json'):   # a damaged entry is computed again, never trusted
                f.write_text('{"key": "x", "result"')
            adjob_boot._cached_transcribe(wav, {'beam_size': 1, 'initial_prompt': 'hi'}, run, folder, 'model-a')
            self.assertEqual(len(ran), 5)
            self.assertEqual(list(folder.glob('*.tmp')), [])


class BudgetFinishedCallsTests(unittest.TestCase):
    def test_finished_calls_count_their_estimate_not_worst_case(self):
        sys.path.insert(0, str(CLOUD / 'worker'))
        from overnight_budget import Budget
        with tempfile.TemporaryDirectory() as td:
            b = Budget(pathlib.Path(td) / 'ledger.json')
            for i in range(9):   # 9 x 0.25 worst case = 2.25 admitted
                b.reserve(f'c{i}', '0.25', 'function', {'family': 'f', 'diagnostic_only': True})
                b.finish(f'c{i}', 'DONE', '0.01', 1.0)
            self.assertTrue(b.reserve('next', '0.25', 'function', {'family': 'f', 'diagnostic_only': True}))   # 0.09 + 0.25
            b.reserve('open1', '0.25', 'function', {'family': 'f', 'diagnostic_only': True})
            for i in range(7):   # 0.09 + 9 open x 0.25 = 2.34, under the 2.40 stop
                b.reserve(f'o{i}', '0.25', 'function', {'family': 'f', 'diagnostic_only': True})
            with self.assertRaises(PermissionError):   # open calls still count their full worst case: 2.59 refused
                b.reserve('over', '0.25', 'function', {'family': 'f', 'diagnostic_only': True})


class ManifestTests(unittest.TestCase):
    def test_manifest_hashes_finished_files_and_skips_intermediates(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td)
            (p / 'MASTER.mp4').write_bytes(b'master')
            (p / 'SEGMENTS').mkdir(); (p / 'SEGMENTS' / 's1.mp4').write_bytes(b'x')
            (p / 'CUT.mp4').write_bytes(b'cut'); (p / 'clip.dl').write_bytes(b'partial')
            m = ad_job.write_manifest(p)
            self.assertEqual(list(m), ['MASTER.mp4'])
            self.assertEqual(m['MASTER.mp4']['sha256'], hashlib.sha256(b'master').hexdigest())
            self.assertEqual(json.loads((p / ad_job.MANIFEST).read_text()), m)


if __name__ == '__main__':
    unittest.main()
