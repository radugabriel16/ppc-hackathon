# FileGrid simulator integration

Implemented independently of frontend/backend. No commits. The only existing file
changed is docker-compose.yml: one include of compose.simulator.yml.

## Map button / demo flow (frontend agent)

1. Map button **Start** opens the interval selector; generation starts only after
   confirmation. Offer 5, 10, 30 and 60 seconds per meter (default 5).
2. As MANAGER, GET /api/v1/admin/simulator/status. Read meterCount=N.
3. POST /api/v1/admin/simulator/start with
   `{"profile":"normal","readingsPerSecond":N/selectedSeconds}`.
   Use the existing session cookie, Origin and X-CSRF-Token handling.
   Keep normal selected for the short demo. No contract changes needed.
4. Poll status every 2 seconds and refresh readings/map as appropriate. Show running,
   outboxSize, generationPaused, lastError and meterSource (api/fallback).
5. Stop: POST /api/v1/admin/simulator/stop without a body. Generation stops;
   queued readings keep sending. Show "draining" while outboxSize > 0.

The first cycle starts immediately; meters are staggered across the selected
interval to avoid simultaneous bursts. Every meter gets one new reading per cycle.
Each reading advances its meter by 15 simulated minutes; 5 seconds does NOT mean
5-second consumption intervals. Simulated timestamps can advance into the future.
At 12 meters / 5 seconds: 2.4 readings/s, about 144 readings and 3 simulated hours
per meter in 60 seconds. Approximate counts depend on request timing.

## Existing compatibility preserved

- Internal http://simulator:8080: GET /status; POST /start (200), /stop (200),
  /backfill (202); GET /runs (zero-based paginated ScenarioRunPage).
- Status keeps running/profile/readingsPerSecond and adds operational fields.
- Start accepts existing optional profile/readingsPerSecond, or an empty body.
  Internal-only aliases rate or intervalSeconds are also accepted; choose one speed
  parameter. The current admin proxy only forwards profile/readingsPerSecond.
- Backfill accepts existing profile/from/to; defaults to the preceding full day.
  Boundaries must be 15-minute aligned, aware datetimes, maximum span 31 days.
  Internal API also accepts anomalies: spike/zero/gap. The existing admin proxy
  does NOT forward anomalies; exposing this in UI needs a future coordinated
  backend/contract change. No change was made here.
- Backfill is asynchronous and restartable, uses the same bounded outbox, and
  pauses on Stop; Start resumes it before live generation. An existing paused job
  returns 409 to another backfill request. Gaps deliberately omit readings;
  counters.intentionalGaps is separate from generated/delivery counts.
- Repeated Start while running updates the active configuration. /runs is local
  SQLite history. Existing /admin/scenario-runs reads catalog-db, and the current
  proxy does not write ScenarioRun rows. The integration agent must choose whether
  to proxy this history or record catalog runs; simulator does not access catalog-db.

## Data, durability and load protection

- Ingest goes directly to api-ingest:8000 on internal with the simulator_token
  secret. No published ports. api-files can already reach simulator on internal.
- Discovery uses operator_password from the existing secrets volume, real
  /auth/login, paginated /meters and /clients. Secure session cookies returned by
  login are explicitly forwarded to the fixed internal api-files address only;
  bearer auth is used only for ingest. No passwords/tokens are logged.
- Missing/unavailable discovery falls back to meters.json, with the actual seeded
  MTR-0001..MTR-0012 codes. Fixtures include synthetic client types. API discovery
  uses actual clientType; unlinked meters default to RESIDENTIAL. Restart after
  recovery to rediscover meters. The local fixture must match any changed seed.
- Daily/weekly Europe/Bucharest shapes for residential/commercial/industrial,
  deterministic noise. UTC ISO timestamps, camelCase payload, per-meter sequence.
- SQLite WAL + synchronous FULL: sequence, next interval, exact payload and queue
  insert commit together. Restart resumes control, pending backfill and retries.
  One process/one replica only; do not scale this simulator using the same volume.
- Exact original bytes are retried; ledger prevents overlapping backfill from
  changing an already generated key. Existing intervals are skipped, so anomalies
  cannot overwrite prior data. seq is generation order, including backfill.
- Only 200/201/409 remove pending rows. 409 is a CONFLICT, never counted as stored
  successfully; the original payload remains in the local ledger for inspection.
  All other responses/errors retry indefinitely with capped exponential backoff,
  jitter, persisted deadlines and numeric/date Retry-After. Retries are serial;
  a failure applies global sending backpressure, avoiding retry storms.
- Base rate limited to at most one reading per 5 seconds per meter. Profiles peak
  multiply traffic x5; storm uses x10 during 2-second bursts every 10 seconds.
  Both are capped by SIM_MAX_RPS (default 20, allowed <=100). SIM_SPEED_FACTOR
  multiplies pacing (default 1); use 1 for the safe demo. Consumption magnitudes
  remain realistic; peak/storm are traffic profiles.
- SIM_MAX_OUTBOX defaults to 10000. At the cap generation pauses before allocating
  more readings and resumes after sending frees room; simulated time does not
  advance for readings not yet generated. Memory remains bounded for queued data.
  Persisted ledger/history grow with the demo; monitor disk for long-running use.
  Disk write failure makes the background task unhealthy; previously committed
  rows remain durable. Volumes must be retained; do not run compose down -v.
- /metrics exposes filegrid_sim_sent_total{result=created|duplicate|conflict|retry},
  filegrid_sim_outbox_size, filegrid_sim_send_duration_seconds. Wire Prometheus in
  its owning change (infra is untouched).
- OTEL_SERVICE_NAME=simulator and OTEL endpoint/protocol/resource env forwarded.
  Tracing is intentionally a no-op (optional in scope); no SDK/exporter is enabled.

## Files and local verification

New: compose.simulator.yml; simulator/{app.py,engine.py,store.py,meters.json,
Dockerfile,.dockerignore,requirements.in,requirements.txt,tests/test_simulator.py,
smoke_stack.py,MERGE_NOTES.md}. requirements.txt pins transitive dependencies too.
Python base image is version pinned. Control and metrics share port 8080.

From repository root, with Python 3.12 and dependencies installed:

```sh
python3.12 -m venv /tmp/filegrid-sim-venv
/tmp/filegrid-sim-venv/bin/pip install -r simulator/requirements.txt
PYTHONPATH=simulator /tmp/filegrid-sim-venv/bin/python -m unittest discover -s simulator/tests -v
```

Tests include a real local HTTP fake ingest, randomized 201/200/409/503, an actual
30-second outage with a simulator restart midway, byte-identical retries,
Retry-After, count reconciliation, queue cap, Stop, backfill/anomalies, discovery
and control API compatibility. Fake 409 is a terminal acknowledgment for testing
queue semantics; it does not prove that real conflicts are successful writes.

## Real-stack verification (Docker host)

Docker/Compose are unavailable in the implementation session, so Docker build,
Compose include validation, real API ingest, database outage recovery and browser
controls have NOT been verified. Requires Docker Compose 2.20+ for include.

```sh
# From repository root; builds/starts stack, runs 60s normal + 30s storage outage.
# Mutates demo readings and temporarily stops storage-db; restores it in finally.
/tmp/filegrid-sim-venv/bin/python simulator/smoke_stack.py
```

The script authenticates as manager using the generated secret, controls the
existing admin API, checks growth/drain, conflicts and exact reading counts.
Run with no competing ingest/scenarios and an empty pending queue. Its TLS bypass
is limited to the local self-signed demo endpoint. Review output before claiming
integration verified. The browser map button and speed selector still need the
frontend change above; visually verify them at https://localhost afterward.

## Verification performed in this change

- Python 3.12.14: first six tests passed in 97.560s, including the actual 30s outage.
- Two additional tests passed (lost response -> identical retry -> 200 duplicate;
  durable backfill cursor restart), together with two repeated control/Stop checks:
  four tests in 1.114s. Eight distinct tests passed overall.
- Python AST parsing and YAML structural/reference checks passed.
- git diff --check passed; git status shows only the authorized paths.
- No Docker or browser integration result is claimed. No commit was created.
