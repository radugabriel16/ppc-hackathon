# Running-stack checks and demo history

From the repository root, with the Compose stack already running:

```bash
python3 scripts/seed_history.py
python3 scripts/seed_history.py   # inserted: 0 if no new six-hour interval has arrived
python3 scripts/smoke_stats.py
```

The history seeder needs only host Python and Docker Compose; it runs Python and
the database drivers inside `api-files`, without rebuilding or restarting it.
It invokes the unchanged `model-ML/filegrid-history-v2/generate.py` in a temporary
directory, then maps distinct synthetic meter profiles to **existing** catalog
meters by their actual region and client type. It does not import demo entities
or change client assignments. For meters with no client type, it uses an unused
synthetic profile from their actual region and explicitly reports its type in
`syntheticProfileMeters`. This is a simulator parameter, **not an inferred or
assigned client type**. The default catalog has six typed and six untyped meters.
Typed meters get model predictions; untyped meters retain the backend's explicit
recent-daily-mean baseline, allowing complete numeric regional charts without
inventing catalog metadata.

By default it loads 730 days plus already-arrived intervals from the current UTC
day. `--days 28` is the minimum; 730 retains the annual comparison. The forecast
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

Live forecast responses may remain cached for up to five minutes after seeding.
Verify `status: READY`, numeric `predictedEnergyKwh`, `fallbackUsed: false`, and
`method: hgb_smooth` on a typed meter and its segment, and inspect
<https://localhost/statistics> in API mode. Regional charts disclose baseline use
when untyped meters contribute; those meters are not made model-ready.

Focused seeder tests:

```bash
python3 -m unittest discover -s backend/tests -p test_seed_history.py
```
