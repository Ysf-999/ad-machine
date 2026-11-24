# Paid adapters (prototype) — mock transport only

Part of the queue prototype, not used by `cloud/ctl.py` (the live controller runs the unchanged tools in Modal).

`providers/paid.py` never imports Kie/Eleven SDKs, reads keys, imports original paid tools or constructs a network client. `JournalAdapter.real(provider, go=False)` refuses missing `--go`; even `go=True` always raises `RealCallsDisabled`. There is no executable real transport here.

Before a mock submission, Queue validates the live lease/gates, explicit run admission, known cost bound, durable provider slot and cap reservation. Reservations are conservative and never refunded. Queue stores the full declared request descriptor in SQLite; `paid_intents` stores its SHA and submission intent in a FULL transaction before transport submission. An existing intent is never submitted again. Returned receipt is fsynced in the adapter table, then Queue/provider-ID outbox and fsynced `jobs.jsonl`; `poll_ready` must validate/flush these before polling. Adapter restart repairs a missing Queue ID only from an already durable matching local receipt. An intent without a known returned ID stays ambiguous and blocks its remote slot for manual reconciliation. It never asks the service to create another task.

Remote slots survive worker lease expiry, retries, cancellation and ambiguous failure. They release only on confirmed terminal status/completion. Running leases also respect the provider limit. An accepted task whose outcome is unknown can intentionally block progress; that is safer than guessing it ended or refunding spend. Current limits/costs are mock inputs; actual owner dashboard limits and known per-request upper bounds are missing.

## Original tools, read-only findings

- `tools/kie.py:_req` lines32–41 retries both transport failures and HTTP errors up to3times, including POST create/upload. An accepted POST with a lost response can therefore create duplicates. The new wrapper must not call `kie.run` or `_req` for submission.
- `kie.run` lines108–124 has no pre-submit durable intent. A crash after create succeeds and before `_log` can submit again on restart. Its file fsync after returned ID helps resume normal polling, but does not close that crash window or fsync the parent directory.
- `kie.run` deliberately clears an ID for a prior `fail`, and for `success` when a previous output file is missing. The latter is an intentional reroll in the local workflow; under unchanged cloud inputs it would violate once-per-job submission. Failed-task rebilling assumptions in source were not verified with the service and are not relied on here.
- Concurrent local calls can both read no ID and submit under the same key; `_log` has no transaction/submit lock. Kie's original key also does not prove a request-body hash. GET status retries and pending-task resume with a saved ID do not themselves create new generation tasks. Output download failure after a saved submitted ID normally resumes that task; deleting output after success deliberately rerolls.
- `tools/ad.py:_tts` lines132–141 calls synchronous ElevenLabs `/with-timestamps` once, returning audio/alignment; no durable submission intent, request/history ID or receipt is captured. Restart after accepted generation/lost response or before file writes can repeat the charge. The ordinary single-voice `vo` path calls TTS on every invocation even if `vo_raw.mp3` exists. It must never be rerun for a clip-only change.
- Dialogue groups reuse existing audio+metadata by voice/text. A crash between API return, audio write and metadata write can repeat a take. Concurrent processes can miss the same cache entry. The cache ignores voice-settings/context changes, which is stale reuse risk rather than duplicate suppression proof. A changed voice/text deliberately regenerates. No automatic HTTP retry was found in `_tts` itself.

## Limits

ElevenLabs has no historical async task journal in this code. Its source-derived synchronous response structure is explicitly synthetic. A future real adapter must persist the response/result reference and any actual provider request/history ID supported by the owner-approved API. Local receipt replay is not an invented ElevenLabs polling API. Real service response compatibility, idempotency support, dashboard limits and spend enforcement remain unverified.

Mock tests cover intent-before-call, ID-before-poll, restart, lost queue-ID write, no second submit, stale leases, cap and remote concurrency. These prove local scheduling/receipt semantics, not provider billing or real network correctness.
