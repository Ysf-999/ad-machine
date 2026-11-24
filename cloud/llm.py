"""Opt-in Claude backends. Standard library only; importing this does no I/O.

The existing tool owns auto/cli/api. It passes its CLI implementation here so
local-cli stays identical. No backend treats an absent check as a successful QC.
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler


class NotCheckedError(RuntimeError):
    """No usable LLM result exists. Callers must retain a failed/pending gate."""

    status = check_status = "not_checked"

    def __init__(self, backend: str, reason: str):
        self.backend, self.reason = backend, reason
        super().__init__(f"LLM not_checked: backend={backend}; reason={reason}")


MODES = frozenset({"local-cli", "callback", "token-cli", "skip"})
_MAX_CALLBACK_BYTES = 32 * 1024 * 1024


def _label(response, backend, executed_backend):
    response.backend = backend
    response.executed_backend = executed_backend
    # 'checked' means a model answered, never that its QC verdict passed.
    response.check_status = "checked"
    return response


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_callback(payload):
    """Explicit callback mode only; redirects/proxies cannot forward attachments."""
    endpoint = os.environ.get("CLAUDE_CALLBACK_URL", "")
    try:
        url = urlsplit(endpoint)
        local = url.hostname in {"localhost", "127.0.0.1", "::1"}
        valid = (url.scheme == "https" or (url.scheme == "http" and local))
        valid = valid and bool(url.hostname) and not (url.username or url.password or url.query or url.fragment)
        if not valid:
            raise ValueError
    except ValueError:
        raise NotCheckedError("callback", "callback_url_missing_or_invalid") from None
    token = os.environ.get("CLAUDE_CALLBACK_TOKEN", "")
    if not local and not token:
        raise NotCheckedError("callback", "callback_token_missing")
    try:
        body = json.dumps(payload).encode("utf-8")
        if len(body) > _MAX_CALLBACK_BYTES:
            raise NotCheckedError("callback", "callback_request_too_large")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = Request(endpoint, data=body, headers=headers, method="POST")
        # No automatic retries: an uncertain response must not duplicate a call.
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=1800) as result:
            raw = result.read(_MAX_CALLBACK_BYTES + 1)
        if len(raw) > _MAX_CALLBACK_BYTES:
            raise NotCheckedError("callback", "callback_response_too_large")
        return json.loads(raw)
    except NotCheckedError:
        raise
    except Exception:
        # URLs, response bodies and transport errors can contain private data.
        raise NotCheckedError("callback", "callback_transport_failed") from None


def _callback_response(payload):
    if isinstance(payload, dict) and payload.get("check_status") == "not_checked":
        raise NotCheckedError("callback", "callback_not_checked")
    try:
        if not isinstance(payload, dict) or payload.get("backend") != "local-cli":
            raise ValueError
        if payload.get("check_status") != "checked" or payload.get("is_error"):
            raise ValueError
        blocks = payload["content"]
        if not isinstance(blocks, list) or not blocks:
            raise ValueError
        content = []
        for block in blocks:
            if block.get("type") != "text" or not isinstance(block.get("text"), str):
                raise ValueError
            content.append(SimpleNamespace(type="text", text=block["text"]))
        usage = payload["usage"]
        for key in ("input_tokens", "output_tokens"):
            if type(usage[key]) is not int or usage[key] < 0:
                raise ValueError
        stop = payload["stop_reason"]
        if stop not in {"end_turn", "max_tokens", "stop_sequence"}:
            raise ValueError
        response = SimpleNamespace(content=content, usage=SimpleNamespace(**{
            key: usage[key] for key in ("input_tokens", "output_tokens")}), stop_reason=stop)
        return _label(response, "callback", "local-cli")
    except (KeyError, TypeError, ValueError, AttributeError):
        raise NotCheckedError("callback", "callback_response_invalid") from None


def create(*, backend, cli, callback=None, **request):
    """Return the tool's SDK-shaped response, or raise typed NotCheckedError.

    ``callback`` is an optional in-process transport for tests/owner adapters. Its
    request/response is the same JSON envelope used by the HTTP bridge.
    """
    if backend == "skip":
        raise NotCheckedError(backend, "explicit_skip")
    if backend not in MODES:
        raise NotCheckedError("unknown", "unsupported_backend")
    if backend == "token-cli":
        if os.environ.get("CLAUDE_TOKEN_CLI_OPT_IN") != "1":
            raise NotCheckedError(backend, "owner_opt_in_required")
        if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip():
            raise NotCheckedError(backend, "token_missing")
    if backend == "callback":
        payload = {"version": 1, "request": request}
        try:
            result = (callback or _http_callback)(payload)
        except NotCheckedError:
            raise
        except Exception:
            raise NotCheckedError(backend, "callback_transport_failed") from None
        return _callback_response(result)
    try:
        if backend == "token-cli":
            response = cli(**request, _token_cli=True)
        else:
            response = cli(**request)
        return _label(response, backend, backend)
    except NotCheckedError:
        raise
    except Exception:
        raise NotCheckedError(backend, "cli_execution_failed") from None


def handle_callback_request(payload, *, cli):
    """Owner-hosted bridge adapter; does not start a server or authenticate.

    The host must authenticate and size-limit requests before calling this.
    Never accept a requested backend: this bridge executes local-cli only.
    """
    if (not isinstance(payload, dict) or payload.get("version") != 1
            or not isinstance(payload.get("request"), dict)):
        raise NotCheckedError("callback", "callback_request_invalid")
    request = payload["request"]
    if not {"model", "max_tokens", "messages"} <= request.keys():
        raise NotCheckedError("callback", "callback_request_invalid")
    if any(key.startswith("_") or key in {"backend", "cli", "callback"} for key in request):
        raise NotCheckedError("callback", "callback_request_invalid")
    response = create(backend="local-cli", cli=cli, **request)
    return {
        "backend": "local-cli", "check_status": "checked",
        "content": [{"type": "text", "text": block.text} for block in response.content],
        "usage": {"input_tokens": response.usage.input_tokens,
                  "output_tokens": response.usage.output_tokens},
        "stop_reason": response.stop_reason,
    }
