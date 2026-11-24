# Claude backends and metadata logging

Implemented for `tools/claude_client.py` (`messages.create`) and `tools/moments.py`
(`llm`). All verification in this change uses mocks. No subscription, API,
callback endpoint, authentication, token, or cloud account has been exercised.

## Runtime files

The isolated runtime must include these exact relative paths:

```
ROOT/tools/claude_client.py
ROOT/tools/moments.py       # when a stage uses moment cards/search planning
ROOT/cloud/llm.py
```

`claude_client._cloud_llm()` loads `ROOT/cloud/llm.py` using a file-path import,
resolving ROOT from `tools/claude_client.py`. No `cloud/__init__.py`, Python path
change, host checkout access, or extra package is required. Include `cloud/llm.py`
in the runtime source hash. Legacy default paths do not load that file. The
isolated-runtime test checks this layout and also runs a mocked default CLI call
with the cloud file absent.

## Selection and result semantics

`CLAUDE_BACKEND` selects the shared client. `MOMENTS_BACKEND` independently selects
moment calls. Both retain the existing import-time selection and sticky legacy
fallback behavior. Set the variable before starting the worker.

| Mode | Behavior |
| --- | --- |
| `auto` (unchanged default) | Existing API-first path, then sticky CLI fallback on the existing credential/credit errors. |
| `api` | Existing API behavior; unchanged. Cloud workers must not select it for this no-paid-API project. |
| `cli` | Existing local Claude CLI path; unchanged. |
| `local-cli` | Explicit local CLI, no API attempt or `.env` read in the backend. Moments retains its own existing CLI prompt/reply path. |
| `callback` | Request a result from an explicitly configured owner-hosted bridge. Missing/invalid configuration, transport errors, and invalid results raise `NotCheckedError`. |
| `token-cli` | Disabled unless `CLAUDE_TOKEN_CLI_OPT_IN` is exactly `1` AND `CLAUDE_CODE_OAUTH_TOKEN` is already present and nonblank. Never obtains a token or logs in. |
| `skip` | Immediately raises `cloud.llm.NotCheckedError`, with `check_status == status == "not_checked"`. No success response, verdict, or placeholder PASS is returned. |

The legacy defaults remain potentially outward-facing; selecting `auto` is not
a no-network guard. Offline workers should select `skip` for both switches, or
use mocks for tests. Other existing stage code may independently load `.env`;
these hooks do not change those callers.

New-mode shared-client responses have `backend`, `executed_backend`, and
`check_status="checked"`. Here **checked means the model returned a result**;
the content may explicitly say FAIL/FIX. Callers must evaluate the content and
existing QC gates. Moments preserves its `(text, input_tokens, output_tokens)`
return shape, so its mode is recorded in metadata logs rather than added tuple
fields. Unchecked calls raise the same typed exception from either hook.

Existing QC tools let `NotCheckedError` propagate, producing a failed subprocess
instead of a fabricated QC pass. The cloud orchestrator must retain a pending or
failed gate and record `not_checked`; a missing/stale report is never evidence
of a fresh pass. The vision-checker regression verifies propagation with image
loading mocked. No QC image was viewed.

Existing limitation: `tools/plan_review.py` uses `messages.stream()`, whereas
the original shared client implements only `messages.create()`. This change
does not add streaming or claim that plan-review works. That stage requires a
separately scoped compatibility fix before cloud readiness can be claimed.

## Callback protocol

Environment names only:

- `CLAUDE_CALLBACK_URL`: HTTPS endpoint, or HTTP on literal loopback/localhost.
  Embedded credentials, query strings, and fragments are rejected.
- `CLAUDE_CALLBACK_TOKEN`: preconfigured bearer secret; required for remote
  endpoints. This code does not create credentials or authenticate an account.

The transport POSTs JSON `{"version":1,"request":{...messages.create arguments...}}`.
Messages may contain private text/base64 attachments; **never log request or
response bodies** at the host/proxy. Redirects, environment proxy forwarding,
and automatic retries are disabled. Request and response bodies are capped at
32 MiB; the timeout is 1800 seconds. Transport errors expose fixed reason codes,
not URLs, secrets, prompt text, or remote response bodies.

`cloud.llm.handle_callback_request(payload, cli=claude_client._cli)` is the pure
bridge adapter. It always runs `local-cli` and rejects injected backend/private
arguments. An owner-hosted HTTP service must enforce authentication and a request
size limit **before** calling the adapter, and manage its own queue/rate limit.
No listening server, deployment, tunnel, authentication, or live callback test is
included. The Mac must be on for callback calls to complete.

The successful response envelope is:

```json
{"backend":"local-cli","check_status":"checked","content":[{"type":"text","text":"model answer"}],"usage":{"input_tokens":0,"output_tokens":0},"stop_reason":"end_turn"}
```

Only the expected backend, `checked` marker, text blocks, nonnegative integer
usage, and recognized stop reasons are accepted. A remote `not_checked` marker
raises the local typed exception. A `passed` marker is invalid. A caller may
inject a pure `callback(payload)` transport for local tests; all bridge tests
use this or a mocked opener.

## Token mode: owner decision remains pending

The owner must decide whether to enable this mode and provision the token
separately. No `claude setup-token`, login, token validation, or real Claude
process was run. Availability and permission for automated cloud subscription
use remain unverified.

The enabled path passes the preexisting `CLAUDE_CODE_OAUTH_TOKEN` to `claude -p`
in a fresh temporary `CLAUDE_CONFIG_DIR`. It removes API-key/auth/base-URL and
Bedrock/Vertex/Foundry selector variables from that child. No saved login/config
is copied. CLI failures become typed `not_checked`, with no fallback to API.
Behavior of an actual installed CLI with token auth remains untested.

## Optional call log

Set `CLAUDE_CALL_LOG` to an existing parent directory plus a JSONL filename.
Unset/empty means off. One record is appended per logical `messages.create()` or
moment `llm()` call, after completion/failure; legacy fallback/retry attempts are
not separate records. Killed processes may leave no final record.

The only fields are `model`, `purpose`, `prompt_size`, `image_count`, `duration`,
`backend`, and `status`. `status` is `ok`, `error`, or `not_checked`; `ok` is call
completion, never a QC verdict. Backend records the final execution path.

`prompt_size` counts textual Unicode characters, including system text and
text/tool-result blocks; it excludes image/document bytes, source URLs, role
labels, generated attachment instructions, and responses. Moments includes its
`image N` text labels. This is not a token count or a cost/plan-usage estimate.
`duration` is monotonic elapsed seconds for the whole logical call.

For the shared client, `purpose="vision_qc"` is an optional metadata-only
argument, removed before dispatch. Without it, purpose is the caller's module
stem. Moments uses `moments`. Model/purpose must be short identifier labels;
invalid labels become `unspecified`. Never place private content in a label.
No keys, constructor options, prompts, replies, image bytes, exception strings,
or source paths are logged.

JSONL appends use a thread lock and POSIX advisory `flock`, with short-write
handling and a single append-only file. New files are created with mode 0600;
existing file permissions are unchanged. Symlinks/nonregular files are refused,
including nonblocking refusal for a FIFO with no reader. Parent directories are
not created. Logging failures are swallowed to preserve existing call behavior.
Use a local filesystem supporting advisory locks; shared/object-storage logging
has not been verified.

## Tests

From the repo root:

```sh
PYTHONPATH=cloud:.:tools .venv/bin/python -m unittest discover -s cloud/tests -p 'test_llm.py' -v
```

Coverage includes default dispatch, fallback/retry and CLI command/environment; metadata privacy; thread/process
JSONL appends (including forced short writes); log failures; symlink/FIFO rejection; isolated runtime imports;
shared/moments skip behavior; disabled token mode; mocked enabled token environment; callback protocol and endpoint
validation; and skipped vision-QC propagation. Network sockets, real subprocess launches and model/API calls are
mocked. Temporary fixtures live under `cloud/.scratch/` and are cleaned after the tests.
