# Running-stack checks and demo history

From the repository root, with the Compose stack already running:

```bash
python3 scripts/seed_history.py
python3 scripts/seed_history.py   # inserted: 0 if no new six-hour interval has arrived
python3 scripts/smoke_stats.py
python3 scripts/smoke_forecast.py # seeded model + bridge, 2-5 exceedances, repeat dedup
```

The history seeder needs only host Python and Docker Compose; it runs Python and
the database drivers inside `api-files`, without rebuilding or restarting it.
It invokes the unchanged `model-ML/filegrid-history-v2/generate.py` in a temporary
directory, then maps synthetic meter profiles to **existing** catalog
meters by their actual region and client type. After reserving distinct profiles,
it deterministically reuses a matching region/type profile if that pool is
exhausted: the model demo has 126 profiles, while the operational topology has
144 meters (eight per geographical subregion). Each target meter still receives
its own real-code keys, UUIDs, stored payloads and complete observation history.
It does not import demo entities
or change client assignments. For meters with no client type, it uses a synthetic
synthetic profile from their actual region and explicitly reports its type in
`syntheticProfileMeters`. This is a simulator parameter, **not an inferred or
assigned client type**. Six original meters remain untyped; the 132 added
synthetic meters have explicitly typed synthetic clients.
All meters with sufficient history get model predictions. Untyped meters use
all-zero client-type indicators with an explicit `clientTypeUnknown` response
flag, without inventing catalog metadata.

By default it loads 730 days plus already-arrived intervals from the current UTC
day, verifying coverage of the latest completed six-hour slot for every meter.
`lastCompleteIntervalEnd` reports that boundary, allowing the generator's maximum
two-minute arrival delay. `--days 28` is the minimum; 730 retains the annual comparison. The forecast
origin is the latest day whose 00:10 UTC cutoff has passed and must be on/after
2026-05-14. Only completed six-hour intervals whose simulated `received_at` is
at/before the invocation time are inserted. Generated arrivals are 1–120 seconds
after interval end, including before the forecast's next-day 00:10 cutoff.
Forecasts themselves are never inserted as observations.

Existing observations are preserved. Where smoke/demo data occupies part of a
six-hour slot, only its uncovered gaps are filled, with generated energy
prorated by duration. Existing intervals are never overlapped or overwritten.
Existing readings received after the model cutoff are reported in `warnings`,
not backdated: they can leave affected meters on the explicit baseline until
their last-seven-day window is complete. In the demo stack, `smoke_stats.py`
creates 18 such historical readings across three meters.
Keys use the real external code and interval start; sequences are seconds since
2020-01-01 UTC. Deterministic UUIDs, interval gap checks, `COPY` staging and
`ON CONFLICT DO NOTHING` make repeats idempotent. The seeder briefly locks
`meter_readings` against concurrent writes while loading.

Each inserted reading has a real JSON payload in `storage-db.file_contents` and
a matching READY `files` row with its checksum and byte count. Synthetic files
are named `synthetic-history-v2-*.json`. As in normal ingest, storage commits
before the catalog; a failed catalog transaction may leave unreferenced bytes
for the existing orphan collector. The temporary generator output is removed.

The seeder also calibrates non-MANUAL per-segment defaults from observed complete
daily totals in the preceding 28 UTC days: p95 x 1.03, minimum 14 complete days.
The summary includes each threshold's value, source and calibration provenance;
existing manual overrides are preserved. Apply migration
`0007_forecast_calibration` before running it.

Tomorrow-origin `/forecast/runs` responses use a documented intraday bridge:
missing slots of today use the per-meter median matching slot from the prior
four same weekdays (minimum two samples). Only private inference state is
filled; no unfinished/future reading is inserted. `bridged` and `bridge` metadata
disclose these estimates separately from `fallbackUsed`. Older gaps still
require baseline/INSUFFICIENT_DATA; see `docs/requests.md`.

Legacy asset forecast responses may remain cached for up to five minutes after seeding.
Verify `status: READY`, numeric `predictedEnergyKwh`, `fallbackUsed: false`, and
`method: hgb_smooth` on a typed meter and its segment, and inspect
<https://localhost/statistics> in API mode. Unknown client-type indicators are explicitly disclosed, never assigned.

Focused seeder tests:

```bash
python3 -m unittest discover -s backend/tests -p test_seed_history.py
```
