# FileGrid — Phase 1 build prompt (API budget: $60, model: Sonnet 5.5)

Save this file in the repo root as `PHASE1.md`. Each step runs in a fresh Claude Code session:
`/clear` → "Read PHASE1.md and execute Step N only."

---------------------------------------------------------------------

## 0. Hard rules for this phase (read first, obey always)

BUDGET
- This phase has a hard total budget of **$60** on Sonnet 5.5 via API. Tokens are money. Work lean.
- Execute **exactly one step per session**, then STOP and print the report (section 9). Do not start the next step on your own.
- Default reasoning effort: medium. Use deep reasoning only where a step says "HIGH".
- If the same fix fails twice, STOP and report the error. Do not loop.
- If a step is growing beyond its scope, stop at a working, committed-quality checkpoint and report what is left.

TOKEN DISCIPLINE
- Do not read files you do not need. Never read `node_modules/`, `.venv/`, lock files, generated client code or binary files.
- Edit files with targeted edits. Never rewrite an entire existing file to change a few lines.
- Keep command output short: quiet flags, `| tail -n 30`, `--quiet`, `-q`. Never print full Docker build logs; on failure show only the last 40 lines.
- Do not run `docker compose up --build` for the whole stack more than needed. Rebuild only the service you changed.
- No web searches unless an API/config is genuinely uncertain. Pin versions you already know to be stable.
- Do not write long explanations, comments, or docs beyond what each step requires.

SCOPE
- Build ONLY the steps below. Do NOT build in this phase: Grafana/Loki/Tempo/Alertmanager/Toxiproxy setup, dashboards, alert rules, simulator, map UI, statistics, demo scripts, reminders, emails.
- Do NOT add: Kafka, Redis, Elasticsearch, Kubernetes, extra microservices, vector DBs, AI/LLM services.
- One stack only: Python/FastAPI backend, React/TS frontend. No Java, no Angular, no Flyway.
- Pin all dependency and image versions. No `latest`, no beta.
- Do not push, do not deploy, do not commit unless asked.
- One person runs this phase, so the team ownership rules do not apply yet. Keep the repo layout exactly as in section 2 so the team can split later.

---------------------------------------------------------------------

## 1. Product context (short)

FileGrid is a file-ingestion and storage platform for an electricity distribution operator (hackathon PPC / Rețele Electrice România). It ingests four file categories and routes each to a configurable storage backend, guarantees integrity, and survives storage failures. Later phases add a map UI, observability, simulator and statistics.

| Category | Size | Storage | Key requirement |
|---|---|---|---|
| METER_READING | ~1 KB JSON, very high volume | DB (BYTEA, separate Postgres) | idempotent, no loss |
| OUTAGE_RECORD | ≤ 10 MB | FTP, fallback S3 | fast availability |
| CONNECTION_DOCUMENT | ≤ 20 MB, PII | S3, AES-256-GCM encrypted | confidentiality, audit |
| DRONE_VIDEO | ≤ 5 GB | S3 multipart, resumable | resumes on unstable networks |

---------------------------------------------------------------------

## 2. Stack and repo layout

Backend: Python 3.12, FastAPI, Uvicorn (one process per container), Pydantic v2, pydantic-settings (`secrets_dir=/run/secrets`), SQLAlchemy 2 + psycopg 3, GeoAlchemy2, Alembic, boto3, ftplib, `cryptography`, pwdlib[argon2], prometheus-client. One image, three roles selected by env `ROLE=ingest|files|worker`.

Frontend: React + TypeScript + Vite, MUI, React Router, TanStack Query, `@hey-api/openapi-ts` (generated client), MSW (mocks).

Infra: Docker Compose; nginx (TLS, the only published port 443); `catalog-db` (PostgreSQL + PostGIS); `storage-db` (separate PostgreSQL, only BYTEA content); SeaweedFS (S3 API); pyftpdlib FTP; `init` one-shot container for secrets and TLS cert.

```
contracts/openapi.yaml
contracts/examples/
config/policies.yaml
backend/
  alembic/
  app/core/  auth/  storage/  files/  uploads/  documents/  outages/
      inspections/  issues/  policies/  metering/  geography/  jobs/
frontend/
infra/nginx/  infra/init/  infra/ftp/
fixtures/
docs/requests.md
docker-compose.yml
.env.example
README.md
```

---------------------------------------------------------------------

## 3. Data model (catalog-db, one initial Alembic migration with ALL tables)

UUID ids, TIMESTAMPTZ (UTC; ISO 8601 in API), NUMERIC for energy, snake_case SQL, camelCase JSON. Real FKs, UNIQUE constraints, indexes on filtered FKs, GiST on geometries.

- `regions`: id, code UNIQUE, name, center Point 4326, bounds JSONB.
- `network_assets`: id, region_id, code UNIQUE, name, type (SUBSTATION|TRANSFORMER|LINE_SEGMENT), geometry 4326, rated_capacity_kw nullable > 0.
- `clients`: id, region_id, external_code UNIQUE, name_enc, email_enc (encrypted columns), location Point 4326 nullable, client_type (RESIDENTIAL|COMMERCIAL|INDUSTRIAL).
- `connection_cases`: id, client_id, status (OPEN|CLOSED), opened_at, due_at.
- `document_types`: id, code UNIQUE, name, required_for_connection.
- `files`: id, region_id, category, original_name, media_type, size_bytes BIGINT, sha256, storage_backend (db|ftp|s3), storage_locator, fallback_used, status (STAGING|VERIFYING|READY|FAILED|CORRUPT), encrypted, encryption_key_id, uploaded_by, created_at, ready_at, last_verified_at.
- `client_documents`: id, case_id, document_type_id, file_id UNIQUE, uploaded_at.
- `meters`: id, external_code UNIQUE, asset_id, client_id nullable.
- `meter_readings`: id, meter_id, reading_key, seq, interval_start, interval_end, energy_kwh, file_id UNIQUE, received_at; UNIQUE(meter_id, reading_key); CHECK interval_end > interval_start AND energy_kwh >= 0; index (meter_id, interval_end).
- `outages`: id, asset_id, file_id UNIQUE, started_at, ended_at, severity, description.
- `video_inspections`: id, asset_id, file_id UNIQUE, recorded_at.
- `map_issues`: id, asset_id, video_inspection_id nullable, video_offset_seconds nullable, location Point 4326, description, severity, status (OPEN|IN_PROGRESS|RESOLVED), assigned_team_label, created_by, created_at, resolved_at, version.
- `app_users`: id, username UNIQUE, password_hash, role (OPERATOR|MANAGER).
- `user_sessions`: id, user_id, csrf_token, created_at, expires_at.
- `audit_events`: id, actor_id, action, entity_type, entity_id, occurred_at, request_id, details JSONB.
- `upload_sessions`: id, category, file_name, size_bytes, chunk_size, total_parts, s3_upload_id, file_id, status, metadata JSONB, created_by, created_at, updated_at, expires_at.
- `upload_parts`: upload_id, part_number, sha256, etag, size_bytes, received_at; PK(upload_id, part_number).
- `storage_operations`: id, category, storage, operation, bytes, duration_ms, outcome, scenario_run_id nullable, occurred_at.
- `scenario_runs`: id, kind, profile, started_at, ended_at, counters JSONB.
- `reminders`: id, case_id, sent_at, missing_types JSONB.

storage-db (separate Alembic env or plain SQL init): `file_contents(file_id UUID PK, content BYTEA)`.

Rule: a file's region must match the region of its linked entity, validated in the backend.

---------------------------------------------------------------------

## 4. Storage, policies, integrity

Storage interface (sync clients wrapped in `anyio.to_thread.run_sync` with a `CapacityLimiter` per storage):
```
put(key, stream, size) -> StoredObject(locator, size)
get(key) -> iterator[bytes]
delete(key)
health() -> ok|degraded|down
S3 only: create_multipart / upload_part / complete_multipart / abort_multipart
```
Adapters: DbStorage (storage-db), FtpStorage (passive, binary), S3Storage (boto3, configurable endpoint). Every adapter is wrapped with: per-operation timeout, circuit breaker per storage (closed/open/half-open), Prometheus histogram per operation.

`config/policies.yaml` (validated by Pydantic at startup and on reload):
```yaml
categories:
  METER_READING:       {backend: db,  maxSizeBytes: 51200,      maxConcurrency: 200}
  OUTAGE_RECORD:       {backend: ftp, fallback: s3, maxSizeBytes: 10485760, maxConcurrency: 32}
  CONNECTION_DOCUMENT: {backend: s3,  encryption: aes-256-gcm,  maxSizeBytes: 20971520, maxConcurrency: 16}
  DRONE_VIDEO:         {backend: s3,  resumable: true, chunkSizeBytes: 16777216, maxSizeBytes: 5368709120, maxConcurrency: 4}
```
Validation: `resumable` only with s3; `db` only if maxSizeBytes ≤ 1 MiB; `fallback != backend`. `GET /api/v1/admin/policies`, `POST /api/v1/admin/policies/reload` (MANAGER, audited). Each file records the storage it was actually written to.

Bulkhead: one semaphore per category; when full → 503 + `Retry-After`, metric `filegrid_requests_rejected_total{category,reason}`.
Fallback: OUTAGE_RECORD with FTP down / circuit open → write to S3, `fallback_used=true`, metric `filegrid_storage_fallback_total{category,from,to}`.

Integrity:
- SHA-256 of original plaintext bytes computed while streaming. Keep exact original bytes.
- Never hold a SQL transaction open during an FTP/S3 transfer. STAGING → READY only after content stored and domain row saved.
- Download always verifies: ≤ 10 MB read fully and checked before sending; larger files hashed while streaming, connection aborted on mismatch. Mismatch → status CORRUPT, `filegrid_integrity_failures_total{category,storage}`, audit event.
- `GET /files/{id}/verify` re-reads, decrypts if needed, returns `{valid, expectedSha256, actualSha256, checkedAt}`. Never `valid:true` without re-reading. S3 ETag is not SHA-256.
- CONNECTION_DOCUMENT: AES-256-GCM segmented (1 MiB segments; nonce = random 8-byte per-file prefix + 4-byte counter; last-segment flag in AAD), key from secret, `encryption_key_id` in metadata. Tampered content must fail decryption.
- Bounded memory everywhere (streaming, `SpooledTemporaryFile` with size cap). Storage keys from UUIDs, never original filenames.

Metrics to expose on `/metrics` (low-cardinality labels, no IDs):
`filegrid_request_duration_seconds{route,method,status_class}`, `filegrid_storage_operation_duration_seconds{category,storage,operation,outcome}`, `filegrid_storage_bytes_total{category,storage,operation}`, `filegrid_requests_rejected_total`, `filegrid_meter_ingest_total{result}`, `filegrid_integrity_failures_total`, `filegrid_circuit_state{storage}`, `filegrid_storage_fallback_total`, `filegrid_file_time_to_available_seconds{category}`, `filegrid_upload_sessions_active`, `filegrid_upload_sessions_stalled`.

---------------------------------------------------------------------

## 5. API (OpenAPI 3.0.x, `contracts/openapi.yaml`, prefix `/api/v1`)

Conventions: pagination `{items, page, size, totalElements, totalPages}` (server caps size); errors `{code, message, fieldErrors, requestId}`; status codes 400/401/403/404/409/413/422/503; GeoJSON `[lon, lat]`; map endpoints never expose client name/email.

Endpoints (all must be in the contract; implementation scope is defined per step):
```
POST /auth/login | POST /auth/logout | GET /auth/me
GET  /regions | GET /assets?regionId= | GET /meters?regionId=
GET  /map/features?regionId=&layer=ASSETS|ISSUES|OUTAGES
GET  /clients?regionId=&page=&size=
GET  /connection-cases?regionId=&page=&size=
GET  /connection-cases/{id}/documents
GET  /document-types
POST /files   (multipart: file + metadata JSON, oneOf by category: CONNECTION_DOCUMENT{caseId,documentTypeId}, OUTAGE_RECORD{assetId,startedAt,severity,description}, DRONE_VIDEO{assetId,recordedAt} only if ≤ chunk size; never METER_READING)
GET  /files?regionId=&category=&status=&page=&size=
GET  /files/{id} | GET /files/{id}/download | GET /files/{id}/verify
POST /uploads | PUT /uploads/{id}/parts/{n} | GET /uploads/{id} | POST /uploads/{id}/complete | DELETE /uploads/{id}
POST /meter-readings/ingest
GET  /meter-readings?meterId=&from=&to=&page=&size=
POST /map-issues | PATCH /map-issues/{id}/status
GET  /stats/storage-benchmark | GET /stats/recommendations | GET /stats/meters | GET /stats/outages/hotspots
GET  /admin/policies | POST /admin/policies/reload
GET|POST /admin/simulator/{status|start|stop|backfill}
GET  /admin/scenario-runs | GET /alerts/recent
```

Resumable protocol:
```
POST   /uploads                {category, fileName, sizeBytes, sha256?, metadata} → 201 {uploadId, chunkSize, totalParts, expiresAt}
PUT    /uploads/{id}/parts/{n} raw bytes + header X-Part-SHA256 → 200 {partNumber, etag}  (idempotent; mismatch → 422)
GET    /uploads/{id}           → {status, receivedParts[], totalParts}
POST   /uploads/{id}/complete  {sha256} → 202 {fileId, status: VERIFYING}
DELETE /uploads/{id}           → abort + S3 abort_multipart
```

Meter ingest:
```
POST /meter-readings/ingest  (Authorization: Bearer <simulator token from secret>; only this endpoint accepts it)
{meterExternalCode, readingKey, seq, intervalStart, intervalEnd, energyKwh}
readingKey = "<meterExternalCode>:<intervalStart ISO>"
201 new | 200 same key + same SHA-256 | 409 same key, different payload | 503 + Retry-After storage-db down or bulkhead full | 413/422 invalid
```
Concurrency via UNIQUE(meter_id, reading_key): catch UniqueViolation, re-read, decide 200/409.

---------------------------------------------------------------------

## 6. Security

- Cookie session (HttpOnly, Secure, SameSite=Lax) in `user_sessions`; CSRF double-submit header `X-CSRF-Token` + `Origin` check on mutating requests. No tokens in localStorage.
- argon2 via pwdlib. Users `operator` (OPERATOR) and `manager` (MANAGER) seeded with passwords from generated secrets.
- OPERATOR: upload/read files, create/claim issues. MANAGER: also resolve issues, reload policies, admin endpoints.
- CONNECTION_DOCUMENT downloads are audited. No PII, passwords, keys or file content in logs.
- `.env.example` with placeholders only; `.env`, secrets, certs in `.gitignore`.
- Login rate limiting (simple in-process limiter is fine for now).

---------------------------------------------------------------------

## 7. Infra details

- `init` container (alpine + openssl inside the image, NOT on host): creates missing secrets into a named volume `secrets` (DB passwords, S3 keys, FTP password, AES key + key id, session secret, simulator token, demo user passwords) and a self-signed TLS cert. Idempotent: never overwrites existing secrets. Writes demo user passwords to `secrets/demo-users.txt`.
- All services depend on `init` completing; secrets mounted at `/run/secrets`.
- Networks: `edge` (nginx ↔ apis) and `internal: true` (apis ↔ catalog-db, storage-db, seaweedfs, ftp). No published ports except nginx 443. Compose profile `debug` may bind storages to 127.0.0.1 only.
- nginx: TLS; `/api/v1/meter-readings/` → `api-ingest`; `/api/v1/` → `api-files`; `/` → frontend static build; `resolver 127.0.0.11 valid=10s`; `client_max_body_size` small for ingest, 20m for `/files`, chunk size + 1m for upload parts; `proxy_request_buffering off` for `/files` and `/uploads`.
- Health: `/health/live` (process), `/health/ready` (catalog-db ONLY, never storages).
- Healthchecks and persistent named volumes for every stateful service. SeaweedFS bucket created automatically on start.
- Services: init, nginx, api-ingest, api-files, worker, catalog-db, storage-db, seaweedfs, ftp. (Observability services are added in a later phase.)

---------------------------------------------------------------------

## 8. Steps (one per session)

Approximate budget per step is given so the operator can track `/cost`. If cumulative spend reaches **$48 before Step 8**, skip Step 8 (it moves to the Pro phase).

### Step 1 — Contract, config, schema, backend skeleton (~$8–10)
- Repo layout (section 2), `.gitignore`, `.env.example`, empty `docs/requests.md`.
- `contracts/openapi.yaml` with ALL endpoints from section 5, schemas, enums, errors, pagination, security schemes; example JSON in `contracts/examples/` for regions, assets, map features, files, cases/checklist, upload session, ingest.
- `config/policies.yaml` + Pydantic model + validation rules (section 4).
- FastAPI app with ROLE switch (ingest mounts metering router; files mounts the rest; worker runs a loop), settings, JSON logging with requestId, error handler, `/health/live`, `/health/ready`, `/metrics`.
- Initial Alembic migration with ALL catalog-db tables (section 3) + storage-db `file_contents`.
- Deterministic seed script in `fixtures/`: 3 regions (Muntenia, Banat, Dobrogea, labeled demo), ~5 assets per region, 12 meters, 6 clients with cases, document types (3 required), 4 map issues. Same UUIDs as in `contracts/examples/`.
- Verify: openapi lints (e.g. `npx @redocly/cli lint` quietly), `alembic upgrade head` against a throwaway PostGIS container, app imports and starts.

### Step 2 — Docker Compose infrastructure (~$5–7)
- `docker-compose.yml`, `infra/init/`, `infra/nginx/`, `infra/ftp/` per section 7. Backend Dockerfile (multi-stage, non-root). Frontend Dockerfile placeholder serving a static page through nginx.
- Migrations + seed run automatically once on startup (a one-shot `migrate` service or entrypoint guarded by advisory lock).
- Verify: from clean state `docker compose up -d --build`, all services healthy, `curl -k https://localhost/health/ready` OK, `docker compose ps` shows no published ports except 443.

### Step 3 — Frontend skeleton (~$3–4)
- Vite + React + TS + MUI + Router + TanStack Query in `frontend/`.
- `npm run gen` generates the client from `contracts/openapi.yaml` via `@hey-api/openapi-ts`.
- MSW handlers serving `contracts/examples/`; `VITE_API_MODE=mock|api`; visible "MOCK DATA" banner in mock mode; no silent fallback to mocks in api mode.
- Pages as empty shells with nav: Login, Map, Files, Cases, Uploads, Statistics, Admin. Login page functional against the API contract (CSRF header on mutations).
- Production build served by nginx.
- Verify: `npm run typecheck`, `npm run build` pass; site loads over https.

### Step 4 — Authentication (~$3–4)
- `auth/`: login/logout/me, sessions table, CSRF double-submit + Origin check middleware, role dependency, login rate limit, seeded users from secrets, audit on login.
- Verify with curl: login → me → CSRF-protected POST without token fails (403), with token works; OPERATOR blocked from MANAGER endpoint.

### Step 5 — Storage layer (~$8–10)
- `storage/`: interface, DbStorage, FtpStorage, S3Storage, timeout wrapper, circuit breaker, CapacityLimiter per storage, metrics per operation, `filegrid_circuit_state`.
- `policies/`: load/validate/reload endpoint, per-category bulkhead semaphores (503 + Retry-After), storage resolution with FTP → S3 fallback.
- Integration tests (pytest) against the real compose containers: put/get/delete roundtrip for each storage with SHA-256 compare; FTP stopped → circuit opens → fallback chosen.
- Verify: tests pass; report test command and result.

### Step 6 — Files flow + encryption (~$10–12, HIGH)
- `files/`: `POST /files` streaming multipart, SHA-256 while streaming, size limit per policy, STAGING → READY, region validation, domain linking via `documents/`, `outages/`, `inspections/` (create domain row).
- List/get with filters and pagination, download with integrity verification (small vs large rule), `/verify`, CORRUPT handling + metric + audit.
- `documents/`: segmented AES-256-GCM encrypt on write / decrypt on read; checklist endpoint `GET /connection-cases/{id}/documents` with `missingDocumentTypes`; audited downloads.
- Read-only endpoints needed by the UI: regions, assets, meters, clients, connection-cases, document-types, map features (GeoJSON, no PII).
- Verify (script `scripts/smoke_files.sh` or `.py`): for OUTAGE_RECORD, CONNECTION_DOCUMENT, small DRONE_VIDEO: upload → list → download → SHA-256 equal; show the document bytes in S3 are NOT plaintext; flip one byte in the stored object → download refuses, status CORRUPT.

### Step 7 — Meter ingest (~$4–6)
- `metering/`: ingest endpoint (section 5) in ROLE=ingest; simulator bearer token; content to storage-db BYTEA first, then catalog rows in one transaction; idempotency 201/200/409; storage-db down → 503 + Retry-After; `filegrid_meter_ingest_total{result}`; `GET /meter-readings`.
- Verify (script): new → 201, same → 200, changed payload → 409, 20 concurrent identical requests → exactly one row; stop storage-db → 503 with Retry-After; restart → 201 again.

### Step 8 — Resumable upload + worker (~$8–10, HIGH; skip if spend ≥ $48)
- `uploads/`: full protocol (section 5) on S3 multipart; sessions/parts in catalog-db; part buffered in capped SpooledTemporaryFile, X-Part-SHA256 check; idempotent re-send.
- `jobs/` in worker: VERIFYING → re-read full object, SHA-256 → READY or CORRUPT, record `filegrid_file_time_to_available_seconds`; abort expired sessions; update `filegrid_upload_sessions_active/stalled`.
- Verify (Python script `scripts/smoke_resumable.py`): 200 MB random file, upload half the parts, "crash", query `GET /uploads/{id}`, send only missing parts (including one duplicate), complete → becomes READY, downloaded SHA-256 matches; report api-files peak memory (`docker stats --no-stream`).

---------------------------------------------------------------------

## 9. Report format (end of every step, then STOP)

```
STEP: <n> — DONE | PARTIAL
DONE: <what works>
RAN: <exact commands + one-line result each>
NOT VERIFIED: <what and why>
FILES: <created/changed paths>
NEXT: <what the next step needs from this one>
```
