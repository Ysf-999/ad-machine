"""No-cost tests: all model execution, transports and .env reads are mocked."""
from disk_test_support import DiskIndependentTestCase

import concurrent.futures
import builtins
import contextlib
import importlib.util
from importlib.machinery import SourceFileLoader
import io
import json
import multiprocessing
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = ROOT / "cloud" / ".scratch"
_TEMPORARY_DIRECTORY = tempfile.TemporaryDirectory


def scratch_directory(*args, **kwargs):
    """Also keep CLI-wrapper temp files inside the authorized test scratch root."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    kwargs["dir"] = SCRATCH
    return _TEMPORARY_DIRECTORY(*args, **kwargs)


def load_client(path, name):
    spec = importlib.util.spec_from_file_location(name, path, loader=SourceFileLoader(name, str(path)))
    module = importlib.util.module_from_spec(spec)
    # Do not import a real paid SDK, even if it is installed.
    sdk = SimpleNamespace(BadRequestError=type("BadRequestError", (Exception,), {}),
                          APIError=type("APIError", (Exception,), {}))
    with patch.dict(sys.modules, {"anthropic": sdk}):
        spec.loader.exec_module(module)
    return module


client = load_client(ROOT / "tools/claude_client.py", "llm_test_client")
llm = client._cloud_llm()
REQUEST = {"model": "claude-sonnet-5-5", "max_tokens": 23,
           "system": "system", "messages": [{"role": "user", "content": "private prompt"}]}


def response():
    return client._Resp('{"verdict":"FAIL"}', 17, 4, "end_turn")


def append_records(path, count):
    for _ in range(count):
        client._log_call(path, {"model": "sonnet", "purpose": "qc", "prompt_size": 12,
                                "image_count": 0, "duration": 0.001,
                                "backend": "cli", "status": "ok"})


def append_short_records(path, count):
    # Deliberately short writes force interleaving without a process lock.
    real_write = os.write
    with patch.object(client.os, "write", side_effect=lambda fd, b: real_write(fd, b[:7])):
        append_records(path, count)


class LLMTests(DiskIndependentTestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.stack.enter_context(patch.object(tempfile, "TemporaryDirectory", side_effect=scratch_directory))
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(patch.object(socket, "socket", side_effect=AssertionError("network forbidden")))
        self.stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")))
        self.stack.enter_context(patch.object(subprocess, "Popen", side_effect=AssertionError("process forbidden")))
        self.run = self.stack.enter_context(patch.object(subprocess, "run", side_effect=AssertionError("CLI forbidden")))
        self.env = self.stack.enter_context(patch.object(client, "_env", side_effect=AssertionError(".env forbidden")))
        self.stack.enter_context(patch.dict(client._STATE, {"use": "cli"}))
        self.cli = self.stack.enter_context(patch.object(client, "_cli", return_value=response()))
        self.sdk = Mock()
        self.stack.enter_context(patch.object(client, "_real", self.sdk))
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory(dir=SCRATCH))
        self.log = Path(self.temp) / "calls.jsonl"

    def records(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_logging_default_off_without_metadata_or_cloud_reads(self):
        with patch.object(client, "_prompt_metrics", side_effect=AssertionError("metrics off")), \
             patch.object(client, "_log_call", side_effect=AssertionError("logger off")), \
             patch.object(client, "_cloud_llm", side_effect=AssertionError("cloud import off")):
            result = client.Anthropic().messages.create(**REQUEST)
        self.assertIs(result, self.cli.return_value)
        self.assertFalse(self.log.exists())
        self.cli.assert_called_once_with(**REQUEST)
        self.env.assert_not_called()

    def test_private_metadata_only_and_purpose_not_forwarded(self):
        os.environ["CLAUDE_CALL_LOG"] = str(self.log)
        request = dict(REQUEST, system=[{"type": "text", "text": "sys"}], messages=[{
            "role": "user", "content": [
                {"type": "text", "text": "secret prompt"},
                {"type": "image", "source": {"type": "base64", "data": "SECRET_IMAGE"}},
                {"type": "image", "source": {"type": "url", "url": "https://secret"}},
                {"type": "document", "source": {"type": "base64", "data": "SECRET_PDF"}},
                {"type": "tool_result", "content": [{"type": "text", "text": "tool"}]}]}])
        os.environ["ANTHROPIC_API_KEY"] = "FAKE_KEY_NEVER_LOG"
        client.Anthropic(api_key="FAKE_CONSTRUCTOR_KEY").messages.create(purpose="vision_qc", **request)
        self.cli.assert_called_once_with(**request)
        record, = self.records()
        self.assertEqual(set(record), {"model", "purpose", "prompt_size", "image_count", "duration", "backend", "status"})
        self.assertEqual(record["prompt_size"], 20)
        self.assertEqual(record["image_count"], 2)
        self.assertEqual(record["purpose"], "vision_qc")
        self.assertEqual(record["backend"], "cli")
        self.assertEqual(record["status"], "ok")
        self.assertGreaterEqual(record["duration"], 0)
        raw = self.log.read_text()
        for private in ("secret", "SECRET", "FAKE", "verdict", "FAIL"):
            self.assertNotIn(private, raw)
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)

    def test_labels_cannot_inject_log_content(self):
        os.environ["CLAUDE_CALL_LOG"] = str(self.log)
        client.Anthropic().messages.create(**dict(REQUEST, model="private model\nbody", purpose="private purpose\nbody"))
        record, = self.records()
        self.assertEqual(record["model"], "unspecified")
        self.assertEqual(record["purpose"], "unspecified")

    def test_default_purpose_is_calling_module(self):
        os.environ["CLAUDE_CALL_LOG"] = str(self.log)
        client.Anthropic().messages.create(**REQUEST)
        self.assertEqual(self.records()[0]["purpose"], "test_llm")

    def test_log_failure_does_not_change_result_or_exception(self):
        os.environ["CLAUDE_CALL_LOG"] = str(Path(self.temp) / "absent" / "calls.jsonl")
        result = client.Anthropic().messages.create(**REQUEST)
        self.assertIs(result, self.cli.return_value)
        original = RuntimeError("private backend error")
        self.cli.side_effect = original
        with self.assertRaises(RuntimeError) as raised:
            client.Anthropic().messages.create(**REQUEST)
        self.assertIs(raised.exception, original)

    def test_logger_refuses_symlink(self):
        target = Path(self.temp) / "target"
        target.write_text("untouched")
        self.log.symlink_to(target)
        client._log_call(self.log, {"model": "sonnet"})
        self.assertEqual(target.read_text(), "untouched")

    def test_logger_does_not_block_on_fifo(self):
        os.mkfifo(self.log)
        client._log_call(self.log, {"model": "sonnet"})

    def test_isolated_runtime_needs_only_explicit_cloud_file(self):
        runtime = Path(self.temp) / "runtime"
        (runtime / "tools").mkdir(parents=True)
        (runtime / "cloud").mkdir()
        tool = runtime / "tools" / "claude_client.py"
        tool.write_bytes((ROOT / "tools/claude_client.py").read_bytes())
        (runtime / "cloud" / "llm.py").write_bytes((ROOT / "cloud/llm.py").read_bytes())
        isolated = load_client(tool, "isolated_test_client")
        with patch.dict(sys.modules):
            sys.modules.pop("cloud.llm", None)
            with patch.dict(isolated._STATE, {"use": "skip"}):
                with self.assertRaises(RuntimeError) as raised:
                    isolated.Anthropic().messages.create(**REQUEST)
            self.assertEqual(raised.exception.check_status, "not_checked")
            self.assertEqual(Path(isolated._cloud_llm().__file__).resolve(), (runtime / "cloud/llm.py").resolve())
        (runtime / "cloud" / "llm.py").unlink()
        isolated = load_client(tool, "isolated_defaults_test_client")
        with patch.dict(isolated._STATE, {"use": "cli"}), \
             patch.object(isolated, "_cli", return_value=response()) as cli, \
             patch.object(isolated, "_cloud_llm", side_effect=AssertionError("no cloud source")):
            isolated.Anthropic().messages.create(**REQUEST)
        cli.assert_called_once_with(**REQUEST)

    def test_existing_vision_qc_does_not_convert_skip_to_pass(self):
        # Import the checker with .env hidden, and replace image loading with a dummy block.
        exists = Path.exists
        with patch.dict(sys.modules, {"claude_client": client}), \
             patch.object(Path, "exists", lambda p: False if p.name == ".env" else exists(p)):
            checker = load_client(ROOT / "tools/vision_qc.py", "llm_test_vision_qc")
        client._STATE["use"] = "skip"
        with patch.object(checker, "img_block", return_value={"type": "text", "text": "mock"}):
            with self.assertRaises(llm.NotCheckedError):
                checker.check(client.Anthropic(), "sonnet", ["unused.png"], "mock")

    def test_error_record_omits_exception(self):
        os.environ["CLAUDE_CALL_LOG"] = str(self.log)
        self.cli.side_effect = RuntimeError("PRIVATE_ERROR_KEY")
        with self.assertRaises(RuntimeError):
            client.Anthropic().messages.create(**REQUEST)
        self.assertEqual(self.records()[0]["status"], "error")
        self.assertNotIn("PRIVATE_ERROR_KEY", self.log.read_text())

    def test_concurrent_thread_jsonl(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda _: append_records(str(self.log), 15), range(12)))
        self.assertEqual(len(self.records()), 180)

    @unittest.skipUnless(sys.platform != "win32", "POSIX file locks")
    def test_concurrent_process_jsonl_with_short_writes(self):
        context = multiprocessing.get_context("fork")
        processes = [context.Process(target=append_short_records, args=(str(self.log), 25)) for _ in range(4)]
        for process in processes: process.start()
        for process in processes:
            process.join(timeout=10)
            if process.is_alive(): process.terminate(); process.join(); self.fail("logger child timed out")
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(len(self.records()), 100)

    def test_auto_fallback_is_sticky_and_logged_once_per_call(self):
        os.environ["CLAUDE_CALL_LOG"] = str(self.log)
        client._STATE["use"] = "auto"
        self.env.side_effect = None
        self.sdk.Anthropic.return_value.messages.create.side_effect = RuntimeError("credit balance")
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(2): client.Anthropic().messages.create(**REQUEST)
        self.assertEqual(self.sdk.Anthropic.call_count, 1)
        self.assertEqual(self.cli.call_count, 2)
        self.assertEqual([r["backend"] for r in self.records()], ["cli", "cli"])

    def test_local_cli_hook_never_uses_sdk_or_env(self):
        client._STATE["use"] = "local-cli"
        result = client.Anthropic().messages.create(**REQUEST)
        self.assertEqual(result.backend, "local-cli")
        self.assertEqual(result.check_status, "checked")
        self.assertEqual(result.content[0].text, '{"verdict":"FAIL"}')
        self.sdk.Anthropic.assert_not_called()
        self.env.assert_not_called()
        self.cli.assert_called_once_with(**REQUEST)

    def test_skip_raises_not_checked_and_logs_no_fake_response(self):
        os.environ["CLAUDE_CALL_LOG"] = str(self.log)
        client._STATE["use"] = "skip"
        with self.assertRaises(llm.NotCheckedError) as raised:
            client.Anthropic().messages.create(**REQUEST)
        self.assertEqual(raised.exception.check_status, "not_checked")
        self.assertEqual(self.records()[0]["status"], "not_checked")
        self.cli.assert_not_called()
        self.sdk.Anthropic.assert_not_called()
        self.env.assert_not_called()

    def test_token_requires_exact_opt_in_and_existing_token(self):
        client._STATE["use"] = "token-cli"
        for opt_in in (None, "0", "true", "yes"):
            if opt_in is not None: os.environ["CLAUDE_TOKEN_CLI_OPT_IN"] = opt_in
            with self.assertRaises(llm.NotCheckedError) as raised:
                client.Anthropic().messages.create(**REQUEST)
            self.assertEqual(raised.exception.reason, "owner_opt_in_required")
        os.environ["CLAUDE_TOKEN_CLI_OPT_IN"] = "1"
        with self.assertRaises(llm.NotCheckedError) as raised:
            client.Anthropic().messages.create(**REQUEST)
        self.assertEqual(raised.exception.reason, "token_missing")
        self.cli.assert_not_called()
        self.env.assert_not_called()
        self.sdk.Anthropic.assert_not_called()

    def test_token_opt_in_passes_private_cli_switch(self):
        client._STATE["use"] = "token-cli"
        os.environ.update(CLAUDE_TOKEN_CLI_OPT_IN="1", CLAUDE_CODE_OAUTH_TOKEN="FAKE_TEST_TOKEN")
        result = client.Anthropic().messages.create(**REQUEST)
        self.cli.assert_called_once_with(**REQUEST, _token_cli=True)
        self.assertEqual(result.backend, "token-cli")

    def test_token_cli_isolates_config_and_provider_env(self):
        os.environ.update(CLAUDE_CODE_OAUTH_TOKEN="FAKE_TOKEN", ANTHROPIC_API_KEY="FAKE_KEY",
                          ANTHROPIC_AUTH_TOKEN="FAKE_AUTH", ANTHROPIC_BASE_URL="https://fake",
                          CLAUDE_CODE_USE_BEDROCK="1", CLAUDE_CODE_USE_VERTEX="1", CLAUDE_CODE_USE_FOUNDRY="1")
        self.run.side_effect = None
        self.run.return_value = SimpleNamespace(stdout='{"result":"answer"}', stderr="", returncode=0)
        self.cli_original(**REQUEST, _token_cli=True)
        env = self.run.call_args.kwargs["env"]
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
            self.assertNotIn(key, env)
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "FAKE_TOKEN")
        self.assertEqual(Path(env["CLAUDE_CONFIG_DIR"]).name, "token-config")

    def test_callback_round_trip_uses_only_local_cli(self):
        def bridge(payload):
            self.assertEqual(payload, {"version": 1, "request": REQUEST})
            return llm.handle_callback_request(payload, cli=self.cli)
        result = llm.create(backend="callback", cli=Mock(), callback=bridge, **REQUEST)
        self.assertEqual(result.backend, "callback")
        self.assertEqual(result.executed_backend, "local-cli")
        self.assertEqual(result.check_status, "checked")
        self.assertEqual(result.content[0].text, '{"verdict":"FAIL"}')

    def test_callback_hook_uses_no_local_cli_or_api(self):
        client._STATE["use"] = "callback"
        envelope = llm.handle_callback_request({"version": 1, "request": REQUEST}, cli=Mock(return_value=response()))
        with patch.object(llm, "_http_callback", return_value=envelope) as callback:
            result = client.Anthropic().messages.create(**REQUEST)
        self.assertEqual(result.backend, "callback")
        callback.assert_called_once_with({"version": 1, "request": REQUEST})
        self.cli.assert_not_called()
        self.sdk.Anthropic.assert_not_called()

    def test_callback_absent_configuration_is_not_checked(self):
        client._STATE["use"] = "callback"
        with self.assertRaises(llm.NotCheckedError) as raised:
            client.Anthropic().messages.create(**REQUEST)
        self.assertEqual(raised.exception.reason, "callback_url_missing_or_invalid")

    def test_callback_rejects_unsafe_endpoints_before_transport(self):
        for endpoint in ("http://owner.example/call", "https://user:password@owner.example/call",
                         "https://owner.example/call?token=private", "file:///tmp/owner"):
            os.environ["CLAUDE_CALLBACK_URL"] = endpoint
            with self.assertRaises(llm.NotCheckedError) as raised:
                llm._http_callback({})
            self.assertEqual(raised.exception.reason, "callback_url_missing_or_invalid")
        os.environ["CLAUDE_CALLBACK_URL"] = "https://owner.example/call"
        with self.assertRaises(llm.NotCheckedError) as raised:
            llm._http_callback({})
        self.assertEqual(raised.exception.reason, "callback_token_missing")

    def test_callback_rejects_fake_pass_and_invalid_results(self):
        good = llm.handle_callback_request({"version": 1, "request": REQUEST}, cli=self.cli)
        bad = [{}, {"check_status": "not_checked"}, dict(good, check_status="passed"),
               dict(good, backend="api"), dict(good, is_error=True), dict(good, content=[]),
               dict(good, usage={"input_tokens": True, "output_tokens": 4}),
               dict(good, stop_reason="unknown")]
        for envelope in bad:
            with self.subTest(envelope=envelope), self.assertRaises(llm.NotCheckedError):
                llm.create(backend="callback", cli=self.cli, callback=lambda _: envelope, **REQUEST)

    def test_callback_rejects_backend_injection_and_redacts_errors(self):
        for extra in ({"backend": "api"}, {"_token_cli": True}, {"cli": "bad"}, {"callback": "bad"}):
            with self.assertRaises(llm.NotCheckedError):
                llm.handle_callback_request({"version": 1, "request": dict(REQUEST, **extra)}, cli=self.cli)
        with self.assertRaises(llm.NotCheckedError) as raised:
            llm.create(backend="callback", cli=self.cli, callback=Mock(side_effect=RuntimeError("PRIVATE_ERROR")), **REQUEST)
        self.assertNotIn("PRIVATE", str(raised.exception))

    def test_http_transport_is_mocked_and_does_not_follow_redirects(self):
        os.environ.update(CLAUDE_CALLBACK_URL="https://owner.example/call", CLAUDE_CALLBACK_TOKEN="FAKE_TOKEN")
        result = Mock()
        result.__enter__ = Mock(return_value=result)
        result.__exit__ = Mock(return_value=False)
        result.read.return_value = b'{}'
        with patch.object(llm, "build_opener") as opener:
            opener.return_value.open.return_value = result
            self.assertEqual(llm._http_callback({"version": 1, "request": REQUEST}), {})
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(json.loads(request.data), {"version": 1, "request": REQUEST})
            self.assertEqual(request.get_header("Authorization"), "Bearer FAKE_TOKEN")
            self.assertEqual(opener.return_value.open.call_count, 1)
        self.assertIsNone(llm._NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))


# Save the unmocked function without ever invoking a real subprocess.
LLMTests.cli_original = staticmethod(client._cli)


class MomentsBackendTests(DiskIndependentTestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.stack.enter_context(patch.object(tempfile, "TemporaryDirectory", side_effect=scratch_directory))
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(patch.dict(sys.modules, {"claude_client": client}))
        self.stack.enter_context(patch.object(socket, "socket", side_effect=AssertionError("network forbidden")))
        self.stack.enter_context(patch.object(subprocess, "run", side_effect=AssertionError("CLI forbidden")))
        self.stack.enter_context(patch.object(subprocess, "Popen", side_effect=AssertionError("process forbidden")))
        self.moments = load_client(ROOT / "tools/moments.py", "llm_test_moments")
        self.stack.enter_context(patch.object(self.moments, "env", side_effect=AssertionError(".env forbidden")))
        self.api = self.stack.enter_context(patch.object(self.moments, "_api_call", return_value=("api", 1, 2)))
        self.cli = self.stack.enter_context(patch.object(self.moments, "_cli_call", return_value=("cli", 3, 4)))
        self.stack.enter_context(patch.object(self.moments.time, "sleep"))

    def test_default_has_no_new_client_import(self):
        self.moments.BACKEND["use"] = "cli"
        original_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name == "claude_client": raise AssertionError("new client import forbidden")
            return original_import(name, *args, **kwargs)
        with patch.object(builtins, "__import__", side_effect=guarded_import):
            self.assertEqual(self.moments.llm("haiku", "system", "text"), ("cli", 3, 4))

    def test_local_cli_preserves_existing_prompt_path(self):
        self.moments.BACKEND["use"] = "local-cli"
        self.assertEqual(self.moments.llm("haiku", "system", "text", (), 20), ("cli", 3, 4))
        self.cli.assert_called_once_with("haiku", "system", "text", (), 20)
        self.api.assert_not_called()

    def test_skip_and_disabled_token_are_not_checked_without_retry(self):
        for mode in ("skip", "token-cli"):
            self.moments.BACKEND["use"] = mode
            with self.assertRaises(llm.NotCheckedError) as raised:
                self.moments.llm("haiku", "system", "text")
            self.assertEqual(raised.exception.check_status, "not_checked")
        self.cli.assert_not_called()
        self.api.assert_not_called()
        self.moments.time.sleep.assert_not_called()

    def test_callback_uses_shared_protocol_without_local_call(self):
        self.moments.BACKEND["use"] = "callback"
        envelope = llm.handle_callback_request({"version": 1, "request": REQUEST}, cli=Mock(return_value=response()))
        with patch.object(llm, "_http_callback", return_value=envelope) as transport:
            result = self.moments.llm("haiku", "system", "text", (b"FAKE_IMAGE_PRIVATE",), 20)
        self.assertEqual(result, ('{"verdict":"FAIL"}', 17, 4))
        payload = transport.call_args.args[0]
        self.assertEqual(payload["request"]["messages"][0]["content"][1]["type"], "image")
        self.cli.assert_not_called()
        self.api.assert_not_called()

    def test_moments_logs_only_metadata_for_legacy_and_skipped_calls(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as temp:
            path = Path(temp) / "calls.jsonl"
            os.environ["CLAUDE_CALL_LOG"] = str(path)
            self.moments.BACKEND["use"] = "cli"
            self.moments.llm("haiku", "PRIVATE_SYS", "PRIVATE_TEXT", (b"PRIVATE_IMAGE",), 20)
            self.moments.BACKEND["use"] = "skip"
            with self.assertRaises(llm.NotCheckedError):
                self.moments.llm("haiku", "PRIVATE_SYS", "PRIVATE_TEXT", (b"PRIVATE_IMAGE",), 20)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([r["backend"] for r in records], ["cli", "skip"])
            self.assertEqual([r["status"] for r in records], ["ok", "not_checked"])
            self.assertTrue(all(r["image_count"] == 1 and r["purpose"] == "moments" for r in records))
            self.assertNotIn("PRIVATE", path.read_text())


if __name__ == "__main__":
    unittest.main()
