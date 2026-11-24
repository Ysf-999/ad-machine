"""Drop-in for the slice of the anthropic SDK the tools use: `Anthropic().messages.create(...)` and `BadRequestError`.

Every call goes to the Anthropic API key in .env first. When that key is out of credit or invalid, the process switches
to headless `claude -p` on the owner's Claude login (his plan, no API spend) and stays there. Images and PDFs in the
message are written to a temp folder and read by that subprocess only, so they never enter the calling agent's context.

  import claude_client as anthropic          # in a tool, instead of `import anthropic`
  CLAUDE_BACKEND=api|cli|auto                # default auto; cli skips the key entirely
  CLAUDE_BACKEND=local-cli|callback|token-cli|skip  # opt-in cloud modes; see cloud/docs/LLM_BACKENDS.md
  CLAUDE_CALL_LOG=/local/path/calls.jsonl    # optional metadata only; default off

messages.stream(...) supports context/get_final_message/text_stream; CLI replies are buffered, API streams delegate.

The reply object has what the tools read: .content (blocks with .type "text" and .text), .usage.input_tokens /
.output_tokens, .stop_reason. On the CLI path output_config={"effort": ...} becomes `--effort` (Opus defaults to medium);
`thinking` and other API-only options are ignored there.
"""
import base64, json, os, pathlib, subprocess, tempfile, threading
# CLOUD 5.2/5.8: metadata-only instrumentation and opt-in backend hook.
import importlib.util, re, stat, sys, time

try:
    import anthropic as _real
    BadRequestError = _real.BadRequestError
    APIError = _real.APIError
except Exception:   # SDK missing: CLI only
    _real = None
    class BadRequestError(Exception): pass
    class APIError(Exception): pass

_STATE = {"use": os.environ.get("CLAUDE_BACKEND", "auto")}
_LOCK = threading.Lock()
_LOG_LOCK = threading.Lock()
_CLOUD_BACKEND = None
_DRY = ("credit balance", "authentication", "invalid x-api-key", "api key", "permission_error")


def _cloud_llm():
    """Lazy path import: workers need ROOT/cloud/llm.py only for new modes."""
    global _CLOUD_BACKEND
    with _LOCK:
        if _CLOUD_BACKEND is None:
            name = "cloud.llm"
            module = sys.modules.get(name)
            if module is None:
                path = pathlib.Path(__file__).resolve().parent.parent / "cloud" / "llm.py"
                spec = importlib.util.spec_from_file_location(name, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                sys.modules[name] = module
            _CLOUD_BACKEND = module
    return _CLOUD_BACKEND


def _log_label(value, default):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", value) else default


def _prompt_metrics(system, messages):
    """Count textual characters and image blocks, never serialize attachments."""
    def count(content):
        if isinstance(content, str): return len(content), 0
        size = images = 0
        for block in content if isinstance(content, (list, tuple)) else ():
            if not isinstance(block, dict): continue
            kind = block.get("type")
            if kind == "text" and isinstance(block.get("text"), str): size += len(block["text"])
            elif kind == "image": images += 1
            elif kind == "tool_result":
                s, i = count(block.get("content")); size += s; images += i
        return size, images
    size, images = count(system)
    for message in messages if isinstance(messages, (list, tuple)) else ():
        if isinstance(message, dict):
            s, i = count(message.get("content")); size += s; images += i
    return size, images


def _log_call(path, record):
    """Best effort JSONL; thread + process locks, private file, no content/errors."""
    try:
        import fcntl
        data = (json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        with _LOG_LOCK:
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode): return
                fcntl.flock(fd, fcntl.LOCK_EX)
                while data:
                    n = os.write(fd, data)
                    if n <= 0: raise OSError("short log write")
                    data = data[n:]
            finally:
                os.close(fd)
    except Exception:
        pass  # Telemetry must not change existing success/failure behavior.


def _env():
    f = pathlib.Path(__file__).resolve().parent.parent / ".env"
    if f.exists():
        for l in f.read_text().splitlines():
            if "=" in l and not l.startswith("#"):
                k, v = l.split("=", 1); os.environ.setdefault(k.strip(), v.strip())


class _Block:
    def __init__(self, text): self.type, self.text = "text", text


class _Usage:
    def __init__(self, i, o): self.input_tokens, self.output_tokens = i, o


class _Resp:
    def __init__(self, text, i, o, stop):
        self.content, self.usage, self.stop_reason = [_Block(text)], _Usage(i, o), stop


def _cli_model(m):
    m = (m or "").lower()
    for k in ("haiku", "sonnet", "opus", "fable"):
        if k in m: return k
    return m or "sonnet"


def _flatten(system, messages, td):
    """messages -> one prompt; image/document blocks become files the subprocess must Read first."""
    files, parts = [], []
    for msg in messages:
        c = msg.get("content")
        blocks = [{"type": "text", "text": c}] if isinstance(c, str) else (c or [])
        txt = []
        for b in blocks:
            t = b.get("type")
            if t == "text": txt.append(b.get("text", ""))
            elif t in ("image", "document"):
                src = b.get("source") or {}
                if src.get("type") == "base64":
                    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
                           "application/pdf": "pdf"}.get(src.get("media_type"), "bin")
                    p = pathlib.Path(td) / f"file_{len(files)+1}.{ext}"; p.write_bytes(base64.b64decode(src["data"]))
                    files.append(str(p)); txt.append(f"[attachment {len(files)}: {p.name}]")
                elif src.get("type") == "url":
                    txt.append(f"[{t} at URL {src.get('url')}]")
            elif t == "tool_result": txt.append(str(b.get("content", "")))
        role = msg.get("role", "user")
        parts.append(("" if role == "user" and len(messages) == 1 else f"[{role}]\n") + "\n".join(txt))
    sysm = system if isinstance(system, str) else "\n".join(x.get("text", "") for x in (system or []) if isinstance(x, dict))
    prompt = (sysm + "\n\n" if sysm else "")
    if files:
        prompt += ("First use the Read tool on each attached file, in order (attachment 1 = the first). They are:\n"
                   + "\n".join(files) + "\nThe attachment markers below show where each one sits in the message.\n\n")
    prompt += "\n\n".join(parts) + "\n\nReply with your answer only (no preamble), in exactly the format asked for."
    return prompt, files


def _cli_effort(model, output_config=None):
    """Reasoning effort for the CLI path (owner 2026-11-22: Opus at medium unless a tool asks for more).
    A tool asks with output_config={"effort": "low|medium|high"}; smaller models keep their own default."""
    asked = (output_config or {}).get("effort") if isinstance(output_config, dict) else None
    if asked in ("low", "medium", "high", "xhigh", "max"): return asked
    return "medium" if _cli_model(model) in ("opus", "fable") else None


def _cli(model, max_tokens, messages, system=None, _token_cli=False, output_config=None, **_):
    with tempfile.TemporaryDirectory(prefix="claude_client_") as td:
        prompt, files = _flatten(system, messages, td)
        e = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_SIMPLE")}
        if _token_cli:
            # CLOUD 5.8: explicit token mode cannot fall back to saved login/API config.
            for key in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
                        "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
                e.pop(key, None)
            config = pathlib.Path(td) / "token-config"; config.mkdir()
            e["CLAUDE_CONFIG_DIR"] = str(config)
        cmd = ["claude", "-p", prompt, "--model", _cli_model(model), "--output-format", "json", "--allowedTools", "Read",
               "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "",
               "--disable-slash-commands", "--no-session-persistence", "--max-turns", str(len(files) + 4)]
        effort = _cli_effort(model, output_config)
        if effort: cmd += ["--effort", effort]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=td, env=e, timeout=1800)
        try: j = json.loads(r.stdout)
        except Exception: raise RuntimeError(f"claude cli failed ({r.returncode}): {(r.stderr or r.stdout)[-400:]}")
        if j.get("is_error"): raise RuntimeError(f"claude cli error: {str(j.get('result'))[:400]}")
        u = j.get("usage") or {}
        return _Resp(j.get("result") or "", int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0)),
                     int(u.get("output_tokens", 0)), "end_turn")


# CLOUD TASK B: buffered CLI compatibility for the repository's stream consumer.
class _CompatStream:
    """Minimal context/get_final_message/text_stream surface; CLI is buffered.

    Healthy API calls delegate to the installed SDK stream. Auto-mode credit
    failures at opening/final-message retrieval may fall back once to CLI.
    API text iteration stays native: never replay text after partial output.
    """
    def __init__(self, messages, request):
        self._messages, self._request = messages, request
        self._manager = self._native = self._response = self._texts = None
        self._entered = self._closed = self._api_entered = False
        self._mode = None

    def _buffer(self):
        self._response = self._messages.create(**self._request)

    def _fallback(self, error):
        if self._mode != "auto" or not any(d in str(error).lower() for d in _DRY):
            raise error
        if self._api_entered:
            self._api_entered = False
            self._manager.__exit__(type(error), error, error.__traceback__)
        self._native = None
        with _LOCK:
            _STATE["use"] = "cli"
        print("  [claude_client] API stream key unusable: using the Claude login via claude -p", flush=True)
        self._buffer()

    def __enter__(self):
        if self._entered:
            raise RuntimeError("message stream contexts are single-use")
        self._entered = True
        self._mode = _STATE["use"]
        if self._mode in {"cli", "local-cli", "callback", "token-cli", "skip"} or _real is None:
            self._buffer()
        else:
            request = dict(self._request)
            request.pop("purpose", None)  # metadata only, not an SDK option
            _env()
            try:
                self._manager = _real.Anthropic(**self._messages._kw).messages.stream(**request)
                self._native = self._manager.__enter__()
                self._api_entered = True
            except Exception as error:
                self._fallback(error)
        return self

    def _require_open(self):
        if not self._entered or self._closed:
            raise RuntimeError("message stream must be used inside its context")

    def get_final_message(self):
        self._require_open()
        if self._response is None:
            try:
                self._response = self._native.get_final_message()
            except Exception as error:
                self._fallback(error)
        return self._response

    def get_final_text(self):
        return "".join(b.text for b in self.get_final_message().content if b.type == "text")

    @property
    def text_stream(self):
        self._require_open()
        if self._native is not None:
            return self._native.text_stream
        if self._texts is None:
            self._texts = iter(b.text for b in self._response.content if b.type == "text")
        return self._texts

    def __exit__(self, exc_type, exc, traceback):
        self._closed = True
        if self._api_entered:
            self._api_entered = False
            return self._manager.__exit__(exc_type, exc, traceback)
        return False


class _Messages:
    def __init__(self, kw): self._kw = kw

    def stream(self, **kw):
        if os.environ.get("CLAUDE_CALL_LOG") and "purpose" not in kw:
            kw["purpose"] = pathlib.Path(sys._getframe(1).f_code.co_filename).stem
        return _CompatStream(self, kw)

    def create(self, **kw):
        # CLOUD 5.2/5.8: one record per logical call, not one per fallback attempt.
        purpose = kw.pop("purpose", None)
        log_path = os.environ.get("CLAUDE_CALL_LOG")
        started, active, status = time.monotonic(), _STATE["use"], "error"
        metrics = None
        if log_path:
            try:
                metrics = _prompt_metrics(kw.get("system"), kw.get("messages"))
                if purpose is None: purpose = pathlib.Path(sys._getframe(1).f_code.co_filename).stem
            except Exception:
                metrics = (0, 0)
        try:
            if active in {"local-cli", "callback", "token-cli", "skip"}:
                response = _cloud_llm().create(backend=active, cli=_cli, **kw)
            else:
                if _STATE["use"] != "cli" and _real is not None:
                    active = "api"
                    try:
                        _env()
                        response = _real.Anthropic(**self._kw).messages.create(**kw)
                    except Exception as ex:
                        msg = str(ex).lower()
                        if _STATE["use"] == "api" or not any(d in msg for d in _DRY): raise
                        with _LOCK:
                            if _STATE["use"] != "cli":
                                _STATE["use"] = "cli"; print("  [claude_client] API key unusable (no credit): using the Claude login via claude -p", flush=True)
                        active = "cli"
                        response = _cli(**kw)
                else:
                    active = "cli"
                    response = _cli(**kw)
            status = "ok"
            return response
        except Exception as ex:
            if getattr(ex, "check_status", None) == "not_checked": status = "not_checked"
            raise
        finally:
            if log_path:
                _log_call(log_path, {
                    "model": _log_label(kw.get("model"), "unspecified"),
                    "purpose": _log_label(purpose, "unspecified"),
                    "prompt_size": metrics[0], "image_count": metrics[1],
                    "duration": round(time.monotonic() - started, 6),
                    "backend": _log_label(active, "unknown"), "status": status,
                })


class Anthropic:
    def __init__(self, **kw): self.messages = _Messages(kw)


def backend(): return _STATE["use"]
