# FileGrid NFR demos

Host needs only Docker (+ compose plugin) and the running stack (`docker compose up -d --build`).
Everything runs in a helper container (`filegrid-demo:0.1.0`: python, curl, jq, aws cli, psql, k6, docker CLI)
attached to the `edge` + `internal` networks; it targets `https://nginx` by service name and reads
`/run/secrets` (demo users in `demo-users.txt`, simulator token). One login per script (login is rate-limited:
10/min per peer, so do not run demos more than a few times a minute).

    scripts/demo/run.sh list                 # demo names
    scripts/demo/run.sh <demo>               # one demo        (COMPOSE_PROJECT_NAME=filegrid by default)
    scripts/demo/run.sh all                  # every demo in order, ~10 min
    scripts/demo/run.sh restore              # force the stack back to healthy (also runs automatically at exit)
    scripts/demo/toxics.sh {latency|loss|bandwidth|reset_peer|clear}   # toxiproxy "degraded" :8443 -> nginx:443

Each demo prints `PASS/FAIL <check>: <numbers>`, then `RESULT`. Cleanup is automatic (exit trap + `restore`):
stopped services are restarted, toxics cleared, api-ingest scaled back to 1, demo files deleted.
Tunables: `STORM_DURATION` (60), `SCALE_VUS` (40), `DEGRADE_MIB` (100), `UPLOAD_MIB` (1024), `RSS_LIMIT_MIB` (512),
`BASE_RATE` for `loadtest/ingest.js`.

## Demo order, what to show, expected output

| # | Demo | Grafana dashboard to show | Expected (measured on a 16-core dev laptop) |
|---|------|---------------------------|----------------------------------------------|
| 1 | `kill_storage` (~3.5 min) | **Resilience** (circuit state, fallback), then **Overview** alerts | 12/12 uploads `fallbackUsed=true` on S3, ingest 20/20 `201`, `StorageCircuitOpen` in Prometheus after ~2 min, mailpit + `/alerts/recent`, circuit back to 0 |
| 2 | `kill_storage_db` (~1 min) | **Meter ingestion** | 10/10 `503` + `Retry-After: 1`, no partial rows, 20/20 accepted after restart (~10 s), stored == accepted |
| 3 | `storm` (~2 min) | **Meter ingestion**, **Category x Storage** | ingest x10 (20 req/s) + uploads: Prometheus meter p95 ~11 ms <= 250 ms, METER_READING rejections 0, k6 errors 0 % |
| 4 | `degrade_network` (~1 min) | **Uploads** | 100 MiB via toxiproxy with 150 ms latency, 8 MiB/s cap, connection cuts; resumed after 'crash'; ~5 retries; SHA-256 equal |
| 5 | `corrupt_file` (~2 min) | **Resilience** (integrity), mailpit | S3/FTP/BYTEA: download `409`, status `CORRUPT`, `IntegrityFailure` firing + mail + `/alerts/recent` |
| 6 | `scale_up` (~2 min) | **Overview** (targets, request rate) | 1 -> 3 `api-ingest` replicas, 35 -> ~60 req/s, 0 errors, 3 targets `up` |
| 7 | `upload_1gb` (~1.5 min) | **Uploads** | 1 GiB in 64 parts ~38 MiB/s, READY, `/verify` valid, api-files peak RSS ~155 MiB (bounded) |

Grafana: https://localhost/grafana/ (password: `docker compose exec -T grafana cat /var/lib/grafana/secrets/admin_password`).
Mailpit: http://127.0.0.1:8025.

## 5-minute presentation script

1. (0:00) "Four file categories, four storage policies." Show Overview dashboard, all green. Run `run.sh upload_1gb` in
   a second terminal at the start - it finishes while you talk (shows bounded memory: ~155 MiB RSS for 1 GiB).
2. (0:45) **Storage failure.** `run.sh kill_storage`. While it runs: Resilience dashboard - FTP circuit opens, uploads
   keep succeeding via S3 (`fallbackUsed`), meters unaffected. Mention the alert reaches mailpit ~2 min later.
3. (2:00) **Database failure.** `run.sh kill_storage_db`: honest `503 + Retry-After`, nothing half-written, replay after
   restart gives stored == accepted (idempotent ingest).
4. (3:00) **Integrity.** `run.sh corrupt_file`: one flipped byte in S3 / FTP / Postgres is detected on download, file
   marked CORRUPT, alert in mailpit and in the app's alert feed.
5. (4:00) **Load and network.** `run.sh storm` (meter p95 stays inside the 250 ms SLO, other categories isolated by bulkheads),
   then `run.sh scale_up` or `degrade_network` if time allows (resumable upload survives a bad link, SHA-256 equal).
6. (4:45) Close: show alert history in mailpit and the five dashboards.

Pre-flight: `docker compose ps` all healthy, wait ~1 min between runs that log in. Run `run.sh all` once before the demo.
