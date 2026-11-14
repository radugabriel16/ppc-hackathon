# Track B merge notes

Owned paths: `compose.observability.yml` and `infra/observability/` only. No shared application, contract, nginx, init or README changes were made.

## Composition and access

- Both `docker compose -f docker-compose.yml -f compose.observability.yml ...` and root `include: [compose.observability.yml]` are supported. Use one integration method; the shared `internal: {internal: true}` network definitions agree. Compose 2.20+ is required for include (validated with 2.32.4).
- APIs and worker expose `/metrics` on **8000** (`backend/Dockerfile`); the admin proxy expects **simulator:8080**. Four A-record DNS discovery jobs refresh every 15 seconds and retain a distinct `instance` per replica. The simulator service is absent from the current base Compose: its track must attach `simulator` to `internal` and expose `/metrics` on 8080. Until then `InstanceDown` reports missing discovery for it.
- Only Mailpit publishes a host port: **127.0.0.1:8025**. SMTP 1025, Grafana 3000, Prometheus 9090, Alertmanager 9093, Loki 3100, Tempo 3200/4317/4318 and Alloy 12345 stay internal.
- Grafana generates a random 0600 admin-password secret file once in its persistent volume (`/var/lib/grafana/secrets/admin_password`); `GF_SECURITY_ADMIN_PASSWORD__FILE` reads it. No default password is checked in. An operator can retrieve it with `docker compose exec -T grafana cat /var/lib/grafana/secrets/admin_password` (do not paste it into logs). This is independent of the shared init volume. Back up the Grafana volume; changing the file does not reset an already-created Grafana administrator.
- `GRAFANA_ROOT_URL` defaults to `https://localhost/grafana/`; set it to the actual external origin, keeping `/grafana/`. Datasource UIDs are `prometheus`, `loki`, `tempo`; dashboards use `prometheus` and their links include `/grafana/`.

## Required nginx integration (Track A)

The current nginx is on `edge` only. Attach it to **internal as well**, keeping `edge`. Add these locations to its TLS server; keep the existing Docker DNS resolver. The URI is preserved because Grafana serves its own subpath. Do not expose Loki/Tempo/Prometheus/Alertmanager through this block.

```nginx
location = /grafana { return 301 /grafana/; }
location ^~ /grafana/ {
    set $grafana_backend grafana:3000;
    proxy_pass http://$grafana_backend;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 300s;
}
```

The existing nginx deny rule for `/api/v1/alerts/webhook` must remain. The backend endpoint is **POST http://api-files:8000/api/v1/alerts/webhook**, OpenAPI `security: []`, and is explicitly exempt from CSRF/Origin checks. Alertmanager sends its normal v4 payload directly over `internal`, with no cookie, CSRF or simulator token. Both firing and resolved messages are sent to this endpoint and Mailpit; webhook groups are capped at the backend's 1000-alert limit. HTTP redirects are disabled.

## Missing metrics / blocked alerts

`backend/app/core/metrics.py` and the producers were checked. Eight named alerts are active and unit tested. Two requested alerts are **not fabricated**:

- **MeterReadingsMissing**: no expected-arrival/missing-interval metric or cadence/active-meter input exists. A proposed low-cardinality gauge such as `filegrid_meter_readings_missing{region}` must be implemented by the metering/simulator track, with semantics for idle/stopped simulation. An aggregate ingest counter or absence of its increments cannot measure missing readings.
- **DocumentAccessAnomaly**: document downloads are audited, but no document-access/denied-access metric exists. Generic HTTP metrics have no file category; storage `get` counts include verification/worker reads and cannot establish a user-access anomaly. Agree and add a low-cardinality instrument such as `filegrid_document_access_total{action,outcome}` and a detection threshold. Do not use customer/file/user IDs as labels.

These proposed names occur only in merge notes, not active queries. Once instruments and semantics are agreed, add both alert definitions and positive/negative/recovery unit tests. A declaration without an executing producer is insufficient.

## Current rule semantics

Demo thresholds are explicit configuration, not agreed production SLOs:

- `MeterIngestErrors`: any `error|unavailable` increase in 5m, held 2m. Actual router outcomes are `created`, `duplicate`, `conflict`, `error`, `unavailable`, `invalid`; invalid input is excluded from operational errors.
- `MeterConflicts`: conflict increase in 5m, held 1m; identical duplicates are excluded.
- `OutageNotAvailable`: OUTAGE_RECORD availability p95 > **5s**, held 2m. Completed observations only; never-ready files are invisible to this histogram.
- `StorageCircuitOpen`: **raw gauge == 2**, held 1m, independently per exporter/storage. Confirmed backend mapping is 0 closed / 1 half-open / 2 open; dashboards now use it.
- `IntegrityFailure`: any counter increase in 5m, immediate; reset-aware.
- `VideoUploadsStalled`: worker stalled gauge > 0, held 2m. The worker currently marks sessions stalled after **10m** without progress; upload creation accepts only DRONE_VIDEO. Revisit the alert's category annotation if resumable support expands.
- `CategoryLatencySLO`: operation p95 per category > **0.25s meter / 1s outage / 2.5s document / 5s video**, held 2m. Uses bucket-rate aggregation before `histogram_quantile`; operations/outcomes/storages combine within each category.
- `InstanceDown`: `up == 0` for the four discovered jobs, held 2m; also detects DNS removing all targets for a job, which otherwise produces no `up` series.

All current metric families and labels exist in backend/app. Prometheus's generated `up` and standard histogram `_bucket`/`_count` series are the only additions. Missing/uninitialized data stays missing, not a synthetic healthy zero.

## Backend tracing integration (Track A)

Tempo listens on **0.0.0.0:4317 gRPC** and **0.0.0.0:4318 HTTP** inside `internal`. Add these env vars to each instrumented backend role, with `OTEL_SERVICE_NAME` set separately to `api-ingest`, `api-files`, `worker` (and simulator on its track):

```yaml
OTEL_SERVICE_NAME: api-files
OTEL_RESOURCE_ATTRIBUTES: service.namespace=filegrid,deployment.environment=demo
OTEL_TRACES_EXPORTER: otlp
OTEL_METRICS_EXPORTER: none
OTEL_LOGS_EXPORTER: none
OTEL_EXPORTER_OTLP_PROTOCOL: grpc
OTEL_EXPORTER_OTLP_ENDPOINT: http://tempo:4317
OTEL_EXPORTER_OTLP_INSECURE: "true"
OTEL_PYTHON_LOG_CORRELATION: "true"
```

Env vars alone do not instrument this backend: its current requirements contain no OpenTelemetry SDK/exporter/instrumentors. Track A must pin and install them, instrument FastAPI/HTTP/DB/worker spans, and propagate context (or launch through `opentelemetry-instrument`). Add `traceId` or `trace_id` to the existing JSON formatter to enable the provisioned Loki → Tempo links. The existing `requestId` is parsed by Alloy and stored as structured metadata, **never an indexed label**; the full JSON line is retained for `| json` field queries.

Alloy reads this project's containers through the Docker socket, requiring daemon access; the bind mount is read-only but Docker API access remains privileged. It uses Alloy, not Promtail. Compose must provide a Docker socket and JSON-readable container logs. Native host validation cannot prove Docker discovery/log delivery.

## Verification and remaining runtime checks

Completed with pinned native Linux tools matching the configured versions: Compose `-f` merge and `include` validation; Prometheus/Alertmanager/Loki/Tempo configuration checks; all 22 promtool scenarios; Alloy formatting and full graph evaluation/readiness; Grafana secret generation/persistence/permissions; and dashboard JSON validation. A temporary loopback smoke deployment verified Grafana 11.6.1 at `/grafana/`, Prometheus/Loki datasource health, Tempo's proxied `/api/echo`, all five provisioned dashboard APIs, a Loki JSON/requestId roundtrip with no requestId stream label, OTLP/HTTP trace ingestion and lookup, and Alertmanager SMTP plus v4 webhook delivery to a synthetic receiver. All temporary processes were stopped.

Grafana 11's Tempo backend returns `plugin.notImplemented` on the generic datasource health API; `verify_runtime.py` uses the datasource's supported proxy `/api/echo` connection test instead. The native smoke substitutes loopback addresses and temporary data directories; it does not validate Docker mounts/networking, real API metrics, backend webhook persistence, or application instrumentation.

Docker's CLI in this WSL distro currently reports that Docker Desktop WSL integration is disabled. Therefore Compose startup/health, real API/worker target UP status, container healthcheck executables, Grafana proxy access and end-to-end backend trace/log delivery must be checked once Docker is available.

```sh
docker compose -f docker-compose.yml -f compose.observability.yml up -d
docker compose -f docker-compose.yml -f compose.observability.yml ps
sh infra/observability/verify.sh
```

`verify.sh` checks merged configuration, rule syntax and all rule unit tests, Alertmanager routing, provisioned datasource health and dashboard availability, and compares discovered UP target counts to running API/worker replicas. The simulator is checked when its service has been integrated. Existing one-shot init/migrate services are not expected to remain running.
