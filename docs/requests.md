# Worker operations

`ROLE=worker` reuses the five-second upload loop. PostgreSQL session advisory
locks serialize each job across replicas without holding SQL transactions during
storage or SMTP calls. `worker_state` persists scheduling and scan cursors.
`WORKER_BATCH_SIZE` defaults to 25; upload recovery retains its existing
100-session bound per operation. The existing loop schedules at most one local
task per job; a slow scrub does not block reminders, gap sampling or upload
recovery. Shutdown cancels and joins all local job tasks.

READY files are scrubbed every `INTEGRITY_SCRUB_INTERVAL_SECONDS` (86400).
Reads use the existing decrypt/hash/storage instrumentation and bulkheads.
`INTEGRITY_SCRUB_BYTES_PER_SECOND` (5242880) paces whole-file reads, averaged
over transfer plus post-read sleep, rather than slowing an individual transfer
past its storage deadline. A run reads at most one batch; large files can
therefore delay that job's next run. Storage failures are deferred by
`WORKER_RETRY_SECONDS` (300), not treated as corruption.

After `STUCK_FILE_AFTER_SECONDS` (3600), abandoned direct STAGING files become
FAILED (`STAGING_ABANDONED_METADATA_UNAVAILABLE`): their original linking metadata
cannot safely be reconstructed. Active multipart sessions are left to the
existing completion/expiry recovery. Unlinked VERIFYING files fail explicitly;
linked ones retry full verification, at most `WORKER_MAX_ATTEMPTS` (3), before
`VERIFY_RETRIES_EXHAUSTED`. Failure reasons and cleanup progress are durable.
Failed writes are deleted on their recorded backend and possible policy fallback.
All three storage inventories are scanned with durable UUID cursors, one batch
per backend per iteration; objects older than ten minutes without a catalog
reference on that backend are deleted. STAGING files protect possible fallback
writes. FTP lacks server pagination, so its MLSD scan streams into bounded
memory under an explicit deadline; deletion remains batch-bounded.

## Meter missing-reading rule

`filegrid_meter_readings_missing{region}` is a shared snapshot of **observed
internal gaps**, not a prediction of future readings. A meter is active only if
both its most recent received reading and latest interval end are within
`METER_ACTIVE_SECONDS` (300) of now. Old backfill does not reactivate it.
Never-seen and idle meters contribute zero even when no simulator is running;
there is no trailing-gap extrapolation after the last observed interval.

For each active meter, compare consecutive readings ordered by interval end,
inside `METER_GAP_WINDOW_SECONDS` (3600), bounded to the newest
`METER_GAP_READINGS_LIMIT` (1000) readings. Add the larger of the sequence gap
and interval gap (rounded up using the preceding interval duration), avoiding
double-counting the same loss. Sequence resets do not themselves create gaps.
The meter scan resumes by UUID each batch; snapshots expire at the activity
deadline even on non-owning worker replicas. Each known region exports zero
when no active gaps remain. Region codes, never meter IDs, are labels.

## Reminders

PHASE1 defines no reminder cases, so the worker reminds the operations mailbox
about unresolved issues older than `REMINDER_AFTER_HOURS` (24), and OPEN
connection cases missing any required READY document. Closed cases, resolved
issues and complete checklists do not qualify. SMTP uses `SMTP_HOST=mailpit`,
`SMTP_PORT=1025`, `REMINDER_FROM=filegrid@filegrid.local` and
`REMINDER_TO=operations@filegrid.local`; provision the SMTP service separately.
Messages contain entity references, not client names, addresses or documents.

`REMINDER_PERIOD_HOURS` (24) defines UTC epoch-aligned periods. The dedupe key is
(kind, entity, period). An attempt is committed **before** SMTP: retries and
replicas never duplicate a period's mail, including ambiguous SMTP acknowledgments.
SMTP cannot participate in a database transaction; a crash after reservation or
failed send may lose that period's email. ATTEMPTED/FAILED rows expose this
at-most-once tradeoff, failures are logged, and the next period is eligible again.

## Telemetry

`filegrid_document_access_total{action,outcome}` accompanies the existing audited
document download path. `requested` counts the committed audit entry; `success`
means the complete plaintext passed verification; `failure` includes integrity,
storage and cancelled reads. No separate document-view endpoint currently exists;
the reserved `view` series stays zero. Do not sum requested and success as if they
were separate accesses.

Tracing is disabled unless `OTEL_EXPORTER_OTLP_ENDPOINT` or
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` is set. Standard OTEL resource, sampler,
headers, timeout and TLS exporter settings apply; protocols are `grpc` (default)
and `http/protobuf`. `OTEL_SDK_DISABLED=true` or `OTEL_TRACES_EXPORTER=none`
disables initialization. The default service name is `filegrid-<role>`.
FastAPI, httpx, SQLAlchemy and asyncpg are instrumented; health/metrics requests
are excluded. Each worker job run has a span, and JSON logs include `trace_id`
(null without an active trace).

Run the integration suite with `bash scripts/test_storage.sh`. It temporarily
pauses a running worker so background jobs cannot consume the tests' deliberate
stale files/reminder candidates, and restores it (and FTP) even if tests fail.