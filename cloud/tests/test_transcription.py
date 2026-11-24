"""No downloads, network, credentials, or model inference in this unit suite."""
from disk_test_support import DiskIndependentTestCase

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

import transcription as tx


class TranscriptionTests(DiskIndependentTestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / '.scratch'
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.audio = self.root / 'voice.wav'
        self.audio.write_bytes(b'fixture; inference is mocked')
        self.model = self.root / 'model'
        self.model.mkdir()
        for f in ('config.json', 'weights.safetensors', 'model.bin', 'tokenizer.json', 'vocabulary.txt'):
            (self.model / f).write_text('{}')

    def test_import_does_not_import_optional_sdks(self):
        result = subprocess.run([sys.executable, '-c',
            "import sys, transcription, providers; "
            "assert not any(n in sys.modules for n in ('mlx_whisper','faster_whisper','modal'))"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_model_is_explicit_and_local_before_sdk_import(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(tx.importlib, 'import_module') as imp:
            for model in (None, 'mlx-community/whisper-large-v3-turbo', 'https://example.invalid/model'):
                with self.subTest(model=model), self.assertRaises(tx.ModelUnavailable):
                    tx.transcribe(self.audio, model_path=model)
            imp.assert_not_called()

    def test_incomplete_faster_model_refused_before_sdk_import(self):
        (self.model / 'tokenizer.json').unlink()
        with patch.object(tx.importlib, 'import_module') as imp:
            with self.assertRaises(tx.ModelUnavailable):
                tx.transcribe(self.audio, backend='faster-whisper', model_path=self.model)
            imp.assert_not_called()

    def test_mlx_preserves_sdk_result_and_options(self):
        expected = {'text': ' Hello', 'language': 'en', 'segments': [
            {'start': 0., 'end': .5, 'text': ' Hello', 'words': [
                {'word': ' Hello', 'start': .1, 'end': .5, 'probability': .9}]}]}
        sdk = NS(transcribe=Mock(return_value=expected))
        with patch.dict(sys.modules, {'mlx_whisper': sdk}):
            result = tx.transcribe(self.audio, path_or_hf_repo=str(self.model), initial_prompt='Hello')
        self.assertEqual(result, expected)
        self.assertEqual(sdk.transcribe.call_args.kwargs['path_or_hf_repo'], str(self.model.resolve()))
        self.assertTrue(sdk.transcribe.call_args.kwargs['word_timestamps'])
        self.assertEqual(sdk.transcribe.call_args.kwargs['initial_prompt'], 'Hello')

    def test_faster_generator_is_materialized_and_json_compatible(self):
        word = NS(word=' Hello', start=.1, end=.5, probability=.9)
        seg = NS(id=0, seek=0, start=0., end=.5, text=' Hello', tokens=[1], temperature=0.,
                 avg_logprob=-.1, compression_ratio=1., no_speech_prob=0., words=[word])
        engine = Mock()
        engine.transcribe.return_value = (iter([seg]), NS(language='en'))
        factory = Mock(return_value=engine)
        with patch.dict(sys.modules, {'faster_whisper': NS(WhisperModel=factory)}):
            result = tx.transcribe(self.audio, backend='faster-whisper', model_path=self.model,
                                   logprob_threshold=-1., device='cpu', compute_type='int8')
        json.dumps(result, allow_nan=False)
        self.assertEqual(result['text'], ' Hello')
        self.assertEqual(result['segments'][0]['words'][0]['word'], ' Hello')
        self.assertEqual(result['segments'][0]['words'][0]['probability'], .9)
        self.assertTrue(factory.call_args.kwargs['local_files_only'])
        self.assertEqual(factory.call_args.args, (str(self.model.resolve()),))
        self.assertFalse(engine.transcribe.call_args.kwargs['vad_filter'])
        self.assertEqual(engine.transcribe.call_args.kwargs['beam_size'], 1)
        self.assertIn('log_prob_threshold', engine.transcribe.call_args.kwargs)

    def test_no_fallback_when_dependency_missing(self):
        with patch.object(tx.importlib, 'import_module', side_effect=ModuleNotFoundError('missing')):
            with self.assertRaises(tx.DependencyUnavailable):
                tx.transcribe(self.audio, backend='faster-whisper', model_path=self.model)

    def test_missing_audio_refused_before_sdk_import(self):
        with patch.object(tx.importlib, 'import_module') as imp:
            with self.assertRaises(FileNotFoundError):
                tx.transcribe(self.root / 'missing.wav', model_path=self.model)
            imp.assert_not_called()

    def test_unknown_backend_and_unsafe_options_refused(self):
        with self.assertRaises(ValueError):
            tx.transcribe(self.audio, backend='auto', model_path=self.model)
        for options in ({'vad_filter': True}, {'download_root': '/tmp'}, {'fp16': True}):
            with self.subTest(options=options), self.assertRaises((TypeError, ValueError)):
                tx.transcribe(self.audio, backend='faster-whisper', model_path=self.model, **options)

    def test_model_paths_cannot_conflict(self):
        with self.assertRaises(ValueError):
            tx.transcribe(self.audio, model_path=self.model, path_or_hf_repo=self.root)

    def test_bad_word_timings_and_missing_words_fail_closed(self):
        for words in (None, [{'word': 'hi', 'start': float('nan'), 'end': .5}],
                      [{'word': 'hi', 'start': .6, 'end': .5}]):
            result = {'text': 'hi', 'language': 'en', 'segments': [{'start': 0., 'end': 1., 'words': words}]}
            with patch.dict(sys.modules, {'mlx_whisper': NS(transcribe=lambda *a, **kw: result)}):
                with self.subTest(words=words), self.assertRaises(tx.TranscriptionError):
                    tx.transcribe(self.audio, model_path=self.model)

    def test_timing_comparison_requires_coverage_and_both_endpoints(self):
        def result(words):
            return {'segments': [{'words': [{'word': w, 'start': s, 'end': e} for w, s, e in words]}]}
        baseline = result([('Hello', .1, .4), ('world', .5, .8)])
        self.assertEqual(tx.compare_word_timings(baseline, baseline)['status'], 'PASS')
        moved = result([('Hello', .1, .7), ('world', .5, .8)])
        self.assertEqual(tx.compare_word_timings(baseline, moved)['status'], 'FAIL')
        missing = result([('Hello', .1, .4)])
        self.assertEqual(tx.compare_word_timings(baseline, missing)['status'], 'FAIL')
        self.assertEqual(tx.compare_word_timings(result([]), result([]))['status'], 'FAIL')


class ProviderTests(DiskIndependentTestCase):
    def test_modal_default_refuses_before_optional_import(self):
        from providers import ModalProvider, CloudAuthorization
        from providers.base import ProviderRefused
        with patch('providers.modal.importlib.import_module') as imp:
            with self.assertRaises(ProviderRefused):
                ModalProvider().run({}, CloudAuthorization())
            imp.assert_not_called()

    def test_modal_missing_go_budget_credentials_or_readiness_refused(self):
        from providers import ModalProvider, CloudAuthorization
        from providers.base import ProviderRefused
        complete = dict(go=True, budget_cap=2., reserved_cost=1., credentials_ready=True,
                        linux_worker_verified=True)
        for k, value in [('go', False), ('budget_cap', None), ('budget_cap', float('nan')),
                         ('reserved_cost', None), ('reserved_cost', 3.), ('reserved_cost', -1.),
                         ('credentials_ready', False), ('linux_worker_verified', False)]:
            opts = {**complete, k: value}
            with self.subTest(opts=opts), patch('providers.modal.importlib.import_module') as imp:
                with self.assertRaises(ProviderRefused):
                    ModalProvider().run({}, CloudAuthorization(**opts))
                imp.assert_not_called()

    def test_modal_transport_uses_injected_remote_after_gates(self):
        from providers import ModalProvider, CloudAuthorization
        sdk = NS(Function=NS(from_name=Mock()))
        sdk.Function.from_name.return_value.remote.return_value = {'status': 'failed', 'deliverable': False}
        with patch('providers.modal.importlib.import_module', return_value=sdk):
            result = ModalProvider('owner-app', 'stage').run({'tool': 'fixture'}, CloudAuthorization(
                go=True, budget_cap=2., reserved_cost=1., credentials_ready=True, linux_worker_verified=True))
        self.assertEqual(result['status'], 'failed')
        sdk.Function.from_name.assert_called_once_with('owner-app', 'stage')

    def test_local_subprocess_does_not_inherit_credentials(self):
        from providers import LocalSubprocessProvider
        with patch.dict(os.environ, {'KIE_API_KEY': 'unit-test-placeholder'}), patch('providers.local.subprocess.run') as run:
            run.return_value = NS(returncode=0, stdout='{"status":"done","deliverable":false}', stderr='')
            result = LocalSubprocessProvider().run({'root': '/fixture', 'manifest': {'timeout': 2}})
        self.assertEqual(result['status'], 'done')
        self.assertNotIn('KIE_API_KEY', run.call_args.kwargs['env'])
        self.assertEqual(run.call_args.kwargs['env']['HF_HUB_OFFLINE'], '1')
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_local_worker_rejects_malformed_request(self):
        from providers import LocalSubprocessProvider
        with self.assertRaises(RuntimeError):
            LocalSubprocessProvider().run({'unexpected': True})


if __name__ == '__main__':
    unittest.main()
