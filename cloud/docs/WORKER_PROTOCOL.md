# Storage-backed version 1 worker (prototype)

Part of the queue prototype, not used by `cloud/ctl.py`.

`worker.protocol.validate_job` admits a strict JSON envelope: version/id, audited no-cost stage Manifest, named ObjectRefs, timeout/output-byte limits and the project-relative path. Every pull is verified for SHA256 and size, including resumed files. Paths/symlinks, extra options, unsupported versions, paid stages and unsafe runner options fail before work. Runtime-root configuration is trusted host configuration, never an envelope-selected arbitrary command.

`execute` holds a workspace lock, binds it to the immutable envelope hash, resumes verified completed **objects**, runs the existing runner, pushes explicitly declared outputs and bounded log files, and atomically writes a versioned result envelope. Results include hashes, exit status, wall time, CPU deltas and clearly labelled cumulative max-RSS semantics. Output references are fetched and verified on completed-result replay; corrupt/missing storage never triggers re-generation. Partial object pulls retry the whole object, not a byte-range/multipart resume. A partially executed runner attempt requires explicit fresh attempt recovery; it is not blindly rerun over its immutable result folder.

`queue_once` wires any injected backend, including S3Storage, into claim → automatic lease renewal → pull/run/push → Queue completion. It refuses external/creating jobs and enforces matching stage identity. It does not invent caption/preflight/QC evidence: render/stitch completion still fails without the existing Queue post-stage gates. This protocol adapter is not a production validator.

Tests use in-process FakeS3, no socket/server/SDK, fictional zero bounds, upload-once CAS, partial-transfer interruption/restart, corrupt remote/local bytes and a real ad.py status through Seatbelt. The real status test proves metadata execution, not remote video parity. All footage bytes shared across projects resolve to the same conditional-write object; the storage backend rechecks bytes on duplicate puts. S3 operation reservations remain instance-local; an owner-approved shared distributed storage-budget authority is still required before real cloud admission. No S3 client was constructed or used against a service.

`python -m cloud.worker.entrypoint --runtime-root … --workspace … --local-cas … < job.json` is the explicit local-CAS entrypoint. Provider adapters inject storage directly; none reads credentials on import. Linux runtime closure, font/OCR parity and real cloud billing/caps remain separate prerequisites.
