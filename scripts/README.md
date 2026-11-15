# History split and operational demo

Run from the repository root:

```bash
docker compose up -d --build
python3 scripts/split_history.py
python3 scripts/seed_demo.py --reset  # reset only owned demo rows, then rebuild the demo
python3 scripts/seed_demo.py          # repeat: no new readings/files
```

The order is **up -> split_history -> seed_demo**. Never reset the old catalog
before splitting it. Host Python 3.9+ and Docker Compose are sufficient; database
drivers and Python 3.12 run inside `api-files`. Secrets never go in arguments.
No command commits changes.

## Backup and restartable split

`split_history.py` first writes a custom-format `pg_dump` of catalog-db into
`backups/` (gitignored, mode 0600), validates it with `pg_restore --list`, and
reports its path, size and SHA-256. A dump failure stops the split. Keep the
backup; the script never removes it. Override its location with `--backup-dir`.

The splitter moves readings ending at/before UTC midnight minus 14 days,
historical issues, explicitly identified synthetic cases/clients, and their
file/domain metadata. It preserves meter UUIDs, topology, client types, recent
readings and unowned operational data. Recognized synthetic identities are the
original fixture UUIDs, `SYN-`/`TRAIN-` clients, and `synthetic-training-` files.
Age/category alone never classifies documents or cases as synthetic.

Each batch locks source rows, copies into history-db, verifies **exact counts
and row digests**, checks DB payload size/SHA-256 and byte equality, and commits
the history transaction **before** deleting the same locked catalog rows.
`history.split_batches` journals successful verification with the backup hash.
Already-copied rows are reverified on restart. A failed/changed/missing copy or
payload does not delete its source batch. Unreferenced synthetic clients alone
are removed; clients still referenced by meters remain until the demo safely
reassigns meters to clients of the **same** type.

`--batch-size 2000` is the default (maximum 10000); `--recent-days` cannot be
less than 14. Exact row counts and heap/total table sizes are printed before
and after. Finally, `VACUUM (FULL, ANALYZE)` compacts only the five named catalog
tables. **This briefly takes exclusive table locks: use a demo maintenance
window.** A compaction failure is reported after the verified-copy counts;
rerunning safely resumes/retries without recopying deleted rows.

For recovery, restore the retained dump into a **new** PostGIS database using
`pg_restore`; verify it before switching the app. Never restore over a live
catalog without an explicit maintenance/rollback decision.

## Isolated history and forecasts

`history-db` is version-pinned PostgreSQL on the internal network, with a
healthcheck, its own persistent volume, and versioned migrations under
`backend/app/history/migrations`. `migrate` applies them using `history_admin`.
Init generates all passwords. `filegrid_history_reader` has only schema usage
and SELECT, with read-only transactions; backend forecast/calibration and
archived-file retention use it. Only seed/split scripts use
`filegrid_history_writer` (SELECT/INSERT/UPDATE/DELETE, no DDL).

History contains meter metadata, raw readings, verified DB payloads, historical
issues, synthetic cases/clients/files, and domain metadata. Catalog versions of
already-generated file metadata are retained separately, never discarded.
Archived FTP/S3 objects remain referenced by history and are protected from
the normal orphan collector. Verified historical DB bytes live in history-db;
their old storage-db copies can be reclaimed by that collector.

Forecasts capture scoped catalog observations first, then read history-db,
union by meter and `readingKey` (catalog wins), and validate complete UTC
six-hour slots **after** merging. This ordering also prevents gaps during a
concurrent split. The checksum-verified `hgb_smooth` model, unknown-type flags,
cutoff/arrival rules and explicit tomorrow intraday bridge are unchanged.
No estimates are persisted as readings.

Threshold calibration uses the same union: preceding 28 complete UTC days,
minimum 14 complete segment days, p95 x 1.03, with MANUAL overrides preserved.
Daily real-model asset results are persisted in `forecast_snapshots`; the worker
refreshes them after the 00:10 cutoff, and the demo primes them. Cached forecast
responses still check history-db availability: down returns **503
HISTORY_UNAVAILABLE**, including `Retry-After`. Catalog health/readiness,
ordinary lists, maps, uploads and ingest do not depend on history-db. Orphan
cleanup for archived FTP/S3 objects is explicitly deferred/logged while it is down.

To extend training history without bloating the catalog:

```bash
python3 scripts/seed_history.py             # 730 days, history-db only
python3 scripts/seed_history.py --days 28    # minimum inference window
```

The unchanged history-v2 generator maps profiles to real meter UUIDs/regions/
client types. It fills only uncovered, completed intervals; it does not
overwrite real observations, backdate arrivals, assign inferred client types,
or create catalog files. Existing complete coverage makes repeats a no-op.

## Demo data and reset boundary

The demo preserves the existing 3 regions / 18 segments / 144 meters (8 each)
and last 14 complete UTC days plus already-arrived current-day slots. It adds
30 encrypted synthetic clients and 30 cases spread across all regions, preserving
the client-type scale used by the model.

The approved checklist/file tradeoff is **81 small files**, rather than 30:
75 separate AES-GCM-encrypted PDFs complete 25 cases using all three real
required document types; 5 cases remain incomplete; 3 outage JSON records and
3 one-frame AVI videos cover the regions. Required types/worker checklist
semantics are not weakened. Files go through the production metadata validation,
storage routing, encryption and SHA-256 read-back pipeline. Operational issue
types use their real validated/backend-generated paths, including real model
exceedances. There are no fabricated historical issues.

UUIDs and reading keys are deterministic. `demo_seed_entities` defines exact
reset ownership; unowned operator rows are preserved. Reset removes only owned
issues/readings/cases and unreferenced owned files, plus their generated alerts.
It does not reset users, topology, history-db, MANUAL thresholds or unowned data.
Seed locks serialize split/seed and defer checklist, reminder, forecast and
orphan jobs until the demo is coherent.

## Pagination, viewport and first-load checks

Files, cases, issues, meters and readings use capped server-side pagination and
filter/order indexes. The default `/files` browser excludes raw METER_READING
payload files; use `category=METER_READING` or `includeMeterReadings=true` to
request them explicitly. This prevents the unchanged UI's all-pages browser
from fetching thousands of raw payload rows.

`/map/features` supports optional `bbox=west,south,east,north`, `scope=country|
region|segment`, existing region/segment/subregion filters, and bounded
`page`/`size` (default 1000, maximum 2000). `hasMore` makes truncation explicit.
Spatial filtering is applied before paging. Invalid WGS84 bounds/scope return
422. Issue list locations are fetched in the same query, not per-row queries.

```bash
node scripts/measure_first_load.mjs > first-load.json
```

This executes the **unchanged** UI `ApiSource`, including its all-pages logic,
three-region map requests and 144 per-meter reading requests in eight-meter
batches. It reports every HTTPS request, status, bytes, latency and each page's
data-ready time, with targets <300 ms/request and <2 seconds/data-ready.
It uses the existing frontend esbuild dependency and generated local self-signed
TLS setup. This measures the real UI **data path**, not browser rendering.

## Validation

```bash
bash scripts/test_storage.sh  # full pytest: FTP-up suite, then ftp_down tests
python3 scripts/smoke_files.py
python3 scripts/smoke_resumable.py
python3 scripts/smoke_operations.py
python3 scripts/smoke_metering.py
python3 scripts/smoke_stats.py --skip-seed  # exercise the real demo, not the old stats fixture
python3 scripts/smoke_forecast.py  # must be hgb_smooth, no baseline; repeat dedup
python3 scripts/smoke_history.py   # real history-db stop/restart; catalog stays available
sleep 65                         # expire prior smoke login quotas on the shared nginx peer
python3 scripts/smoke_auth.py      # LAST: intentionally exercises login limits
cd frontend
npm run gen
npm run typecheck
npx --yes @redocly/cli@1.34.3 lint ../contracts/openapi.yaml
```

Measured with installed headless Chrome over local HTTPS using the unchanged
UI (195 requests across the five initial pages, including lazy-loaded statistics):

| Page | Data ready | Slowest API request |
| --- | ---: | ---: |
| Map | 1,015 ms (basemap ready 1,380 ms) | 159 ms |
| Statistics | 512 ms | 116 ms |
| Files | 93 ms | 12 ms |
| Cases | 367 ms | 268 ms |
| Issues | 102 ms | 32 ms |

Every measured browser request is below 300 ms and each page is below 2 s.
These are local measurements, not a guarantee under other hardware/load or
external tile-server latency. The unconstrained Node cold-TLS harness reached
330 ms for its slowest request; browser measurements include real connection
scheduling and basemap loading.

The existing catalog has one `MANUAL` manager threshold (confirmed in the
pre-split backup). It is preserved, while the other 17 thresholds use the
unchanged observed p95 x 1.03 calibration. The real model currently produces
one exceedance; smoke checks validate natural model output and preserved
overrides rather than forcing extra alerts by changing thresholds.

The focused split/demo tests create and drop uniquely named disposable databases;
they cover counts, interruption/restart, idempotency, corrupt-payload refusal,
read-only privileges, merged duplicate-key precedence, demo reset/repeat,
real-model forecasts, bbox paging and history-db up/down.

Integration pytest runs also use disposable catalog/storage/history databases,
a uniquely named S3 bucket and FTP directory. Full suites therefore do not
depend on the running demo's row counts or scrub/delete its storage objects.
