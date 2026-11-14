# Track B merge notes

The authorized branch integration is applied in `docker-compose.yml`, `infra/nginx/nginx.conf`, `compose.observability.yml` and `infra/observability/`. Backend application/SDK code, frontend source and contracts were not changed.

## Composition and access

- The root file has `include: [compose.observability.yml]`. Use **`docker compose` only**, without an additional observability `-f` merge. The shared `internal: {internal: true}` network definitions agree. Compose 2.20+ is required for include (validated with the running 2.29.2 CLI).
- APIs and worker expose `/metrics` on **8000** (`backend/Dockerfile`); the admin proxy expects **simulator:8080**. Four A-record DNS discovery jobs refresh every 15 seconds and retain a distinct `instance` per replica. The simulator service is absent from the current base Compose: its track must attach `simulator` to `internal` and expose `/metrics` on 8080. Until then `InstanceDown` reports missing discovery for it.
- Only Mailpit publishes an observability host port: **127.0.0.1:8025**. Mailpit joins both existing networks (`internal`, `edge`), because Docker suppresses host publications on an internal-only bridge. SMTP 1025, Grafana 3000, Prometheus 9090, Alertmanager 9093, Loki 3100, Tempo 3200/4317/4318 and Alloy 12345 remain unpublished. The base nginx HTTPS port 443 is unchanged.
- Grafana generates a random 0600 admin-password secret file once in its persistent volume (`/var/lib/grafana/secrets/admin_password`); `GF_SECURITY_ADMIN_PASSWORD__FILE` reads it. No default password is checked in. An operator can retrieve it with `docker compose exec -T grafana cat /var/lib/grafana/secrets/admin_password` (do not paste it into logs). This is independent of the shared init volume. Back up the Grafana volume; changing the file does not reset an already-created Grafana administrator.
- `GF_SERVER_ROOT_URL` is `https://localhost/grafana/`, with `GF_SERVER_SERVE_FROM_SUB_PATH=true`. Datasource UIDs are `prometheus`, `loki`, `tempo`; dashboards use `prometheus` and their links include `/grafana/`.

## Applied nginx integration

Nginx is attached to both `edge` and `internal`. These locations are installed in its TLS server, with the existing Docker DNS resolver retained. The URI is preserved because Grafana serves its own subpath. Loki/Tempo/Prometheus/Alertmanager are not exposed through nginx.

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

Tempo listens on **0.0.0.0:4317 gRPC** and **0.0.0.0:4318 HTTP** inside `internal`. These env vars are now set on all three backend roles, with `OTEL_SERVICE_NAME` separately set to `api-ingest`, `api-files`, and `worker`. Simulator instrumentation remains on its track:

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

Alloy reads this project's containers through the Docker socket, requiring daemon access; the bind mount is read-only but Docker API access remains privileged. It runs as vendor UID/GID **473:473**, which owns its state directory, with the socket's supplementary group **`${DOCKER_SOCKET_GID:-1001}`**. No capabilities are added; all capabilities remain dropped. On another host, set `DOCKER_SOCKET_GID` to `stat -c %g /var/run/docker.sock`. It uses Alloy, not Promtail. Docker discovery and log delivery now pass the live verifier.

## Verification and remaining runtime checks

Initial native validation covered configuration checks, all 22 promtool scenarios, Alloy graph evaluation, Grafana secret persistence/permissions, provisioned dashboards, log/trace ingestion and synthetic notification delivery. The current branch uses the include-based live Docker stack rather than that temporary smoke deployment.

Grafana 11's Tempo backend returns `plugin.notImplemented` on the generic datasource health API; `verify_runtime.py` uses the datasource's supported proxy `/api/echo` connection test instead. The native smoke substitutes loopback addresses and temporary data directories; it does not validate Docker mounts/networking, real API metrics, backend webhook persistence, or application instrumentation.

Live Docker validation now passes: all 15 long-running services are healthy; init, migrate and s3-init exited 0; nginx syntax is valid; `verify.sh` passes configuration/rule checks and all 22 scenarios, real API/worker target discovery, three Grafana datasource checks, five provisioned dashboards and Alloy log delivery. The simulator target is optional. Automatic backend tracing remains pending the backend owner's SDK/instrumentation; environment variables alone cannot provide application spans.

```sh
docker compose up -d --build
docker compose ps -a
docker compose exec -T nginx nginx -t
sh infra/observability/verify.sh
```

`verify.sh` uses include only, checks all configured service health and successful one-shot completion, rule syntax/unit tests, Alertmanager configuration, datasource health, dashboards and logs, and compares discovered UP target counts to running API/worker replicas. A missing simulator does not fail verification. Existing one-shot services are expected to exit successfully.

Authentication, files and operations regression smokes pass without source edits. This host has no `localhost` resolver entry; the Python files/operations runs used an in-memory `localhost` → `127.0.0.1` resolver shim, preserving the HTTPS URL/Host. No host resolver files were edited.

HTTPS Grafana login, authenticated `/grafana/` HTML and its build asset pass through nginx. All five provisioned dashboards successfully query real API/worker Prometheus metrics; a small real meter sample exercised 201/200/409/422 outcomes. A `TrackBIntegrationTest` alert sent through Alertmanager appears in both the published Mailpit inbox (`127.0.0.1:8025`) and authenticated `GET /api/v1/alerts/recent`. No backend SDK or application source was changed.
