# Customer document intake merge notes

## Integration on integrate-documents

The original branch notes below are historical. The integrated migration is
0010_document_intake, parent 0009_forecast_snapshots; main's migrations are unchanged.
The files conflict keeps main's meter-reading filter and hides unassigned intake files.
History-db and its roles, map/Issues/Cases behavior, and init-generated secrets remain.
Documents is available at /documents with a navigation entry. All 30 DEMO clients
receive fixture-compatible HMAC identities; the first two have missing request/approval
slots. The seed still creates 81 demo files, preserves referenced cases/intake files,
and can be reset repeatedly. Closed cases never create missing-document issues;
successful links update the missing types and resolve completed checklists.

Verified during integration: OpenAPI lint and additive contract keys, npm run gen,
frontend typecheck/build, one Alembic head and upgrade on the existing catalog,
docker compose up -d --build with healthy services, and repeated seed_demo --reset.
One Chrome operator login verified the map (8 meters at segment scope), /documents,
locked client/type prefills, and a 15-file batch: 4 auto-linked, 11 review, 0 failed;
the bottom-right manual queue was visible and linked issues resolved.
No pytest, frontend tests, smoke scripts, performance checks, commit, or volume deletion.

## Scope and contract

Branch: feature/parsare-documente, from main 84ae9d6.
Only contract commit: ee52ddf (`contract: customer document intake`).
Implementation remains uncommitted, as requested. No push or deployment.

The existing /connection-cases listing is extended with customerName (safe existing
client external code), cnpMasked, complete, regionId and required document slots.
New filters: search (existing external code) and complete. Existing pagination is
page/size, not a parallel pageSize convention. Region/segment/subregion filters,
case/list/grid behavior and original endpoints remain available.
New /customer-documents single, batch, review and /customers/lookup routes follow
contracts/openapi.yaml. The original filename is display-only. Detection reads
only the first-page title area, then CNP in the first paragraph, never filenames,
metadata or fixed coordinates. No OCR is enabled.

Required document codes: ID, REQUEST_FORM, CONNECTION_APPROVAL. PROOF_OF_ADDRESS
and its old associations are retained but no longer required. Existing file
upload/encryption/storage/download services are reused. Unassigned intake files
have nullable region_id until a verified association is committed; normal file
lists hide unassigned entries. Only CONNECTION_DOCUMENT can have no region.

Multiple open cases for the same client are intentionally not guessed: the item
stays in CONTENT_MISMATCH review. Current demo clients have one case each. A future
case-selector extension is needed to resolve truly ambiguous multi-case clients.

## Migration and secrets

One migration: 0008_document_intake, parent 0007_forecast_calibration.
Adds HMAC/masked CNP, durable intake tables, superseded_at on client_documents,
nullable region_id for unassigned documents, and the required approval type.
Offline PostgreSQL DDL generation and a single Alembic head were verified.
A real upgrade/downgrade still requires PostgreSQL/PostGIS. Downgrade refuses to
restore NOT NULL while unassigned files exist; never delete them to force it.

New generated secret: /run/secrets/cnp_hmac_key (32 random bytes as hex), created
idempotently by infra/init/init.sh. Rebuild/re-run init before migrated bootstrap.
Do not rotate the secret independently: existing HMACs must be reindexed from a
trusted source when rotating. Raw CNP is never stored in catalog/audit/logs.
Existing clients without a CNP remain valid and need explicit enrollment. The six
CLI-0001..CLI-0006 demo clients receive valid fabricated fixture CNP HMACs only when
their field is missing; no populated database is reset. Their fixture values are
in fixtures/documents/demo-clients.json. Earlier all-zero demo CNPs are invalid.

Optional environment: INTAKE_IDENTITY_MARKERS, a pipe-separated list, defaults to
CARTE DE IDENTITATE|IDENTITY CARD|BULETIN DE IDENTITATE.
One necessary tracing exclusion was added for /customers/lookup because its
specified GET query contains CNP. No observability services/dashboard/ML/map or
simulator implementation was changed. New metric labels use fixed vocabularies.

nginx limits added only on intake routes: 21m single / 201m batch. Application:
20 MiB/file, 50 files/batch, 200 MiB files total; multipart overhead bounded.
Parser: pypdf==5.1.0, bounded threadpool, killable 10s subprocess, 20-page ceiling,
512 MiB address-space ceiling on Linux. Fixture/test generator: reportlab==4.2.5.

## Review behavior

OPERATOR and MANAGER can upload/review with existing sessions and CSRF. Audited
preview reuses /files/{id}/download?inline=true with PDF/image content type.
Confirm requires CNP validation, a unique matching client and a fresh item version;
replace is explicit, preserves superseded files and records old IDs and overrides.
Link, derived checklist update, issue resolution and audit commit together.
Unchanged SHA-256/client/type returns the existing association. Storage errors
leave the checklist unchanged and fail only the relevant item.

A recognized identity-title PDF always goes to IDENTITY. Images or scanned PDFs
cannot be identified without OCR and go to MANUAL/NO_EXTRACTABLE_TEXT; the reviewer
chooses ID explicitly. Unknown files are never assumed to be IDs. For a missing
slot, customer/type are locked; content is still checked. No-text linking needs
the explicit manual-confirmation checkbox. Free-form rejection text is not stored
in an unencrypted column; rejection action, reviewer and item version are audited.
Batch reviewCount preserves initial review classification including later confirmed
or rejected items. The review-panel badge counts only pending review items.

## Demo and real-stack checks still required

1. `docker compose up -d --build` (rebuilds init/backend/frontend and applies 0008).
2. `bash scripts/test_storage.sh` for the full existing test harness. New Compose
   integration tests also drive the existing intake worker job explicitly because
   this harness deliberately stops the persistent worker during tests.
3. Run all scripts/smoke_*.py against the running stack; smoke_auth.py LAST.
4. Open https://localhost/cases as operator or manager. Load the extracted files
   from fixtures/documents/demo-batch.zip, not the ZIP itself. First two clients
   receive request/approval pairs; malformed and unknown inputs stay in review.
5. Open an existing document, load a missing slot, verify content mismatch handling,
   find the client by a valid fixture CNP, confirm an ID, test an explicit replacement
   and stale-version refresh, then observe checklist/issue updates.

Docker executable, running PostgreSQL/S3 and https://localhost are unavailable in
this session. These real-stack checks, actual migration application and browser
verification are NOT claimed as passed. SQLite transaction tests with encrypted
in-memory storage exercise the application flow but do not test PostGIS triggers,
PostgreSQL concurrency or a real S3 deployment.

## Checks actually run

- `python -m pytest backend/tests -m 'not integration' -q -p no:cacheprovider`:
  71 passed, 110 integration tests deselected. Local configuration points to
  config/policies.yaml and task-local generated secrets; no production credentials.
- After final rate-limit/review edits: all 5 transaction/API workflow tests passed;
  all 13 parser tests passed. The tests cover encrypted storage-first behavior,
  idempotency, replacement history, mismatches, identity/manual queues, storage
  failure isolation, checklist-driven issue resolution, audited inline preview,
  case filters, invalid CNP, masked lookup, rate limiting, confirm/reject, stale
  versions, CSRF/auth and explicit manual confirmation.
- Frontend: generated the client with the pinned openapi-ts command used by npm gen,
  then ran Prettier (npm itself is not installed on this host). `tsc --noEmit`,
  `eslint . --max-warnings 0`, `vitest run` (133 tests / 21 files) and `vite build`
  passed. Vite emits the existing large-chunk advisory for the forecast bundle.
- OpenAPI lint: @redocly/cli 1.27.1 passed, with the existing info-license warning.
- Alembic: head is only 0008_document_intake; offline DDL for 0007 -> 0008 generated.
- All 15 fixture files matched expected parsing results (unknown CNP is a service
  lookup outcome). Both previously approved flowing PDF generators were also run
  with a valid synthetic CNP and Unicode name; request and approval parsed correctly.
- `git diff --check` passed. Package-manager scratch/cache files were moved outside
  the repository. No implementation commit, push or deployment was performed.

The transaction/API tests use SQLite plus encrypted memory storage and are explicitly
separate from the two new PostgreSQL/S3 integration tests. They are not evidence of
PostGIS trigger correctness or cross-process advisory-lock behavior on the real stack.

## Changed and added files

- backend/alembic/versions/0008_document_intake.py
- backend/app/core/bootstrap.py
- backend/app/core/metrics.py
- backend/app/core/settings.py
- backend/app/core/tracing.py
- backend/app/document_intake/__init__.py
- backend/app/document_intake/identity.py
- backend/app/document_intake/parser.py
- backend/app/document_intake/pdf_extract.py
- backend/app/document_intake/router.py
- backend/app/document_intake/service.py
- backend/app/documents/checklists.py
- backend/app/documents/router.py
- backend/app/documents/schemas.py
- backend/app/files/router.py
- backend/app/files/schemas.py
- backend/app/files/service.py
- backend/app/jobs/worker.py
- backend/app/main.py
- backend/app/models/__init__.py
- backend/app/models/clients.py
- backend/app/models/document_intake.py
- backend/app/models/files.py
- backend/requirements-test.txt
- backend/requirements.txt
- backend/tests/test_document_intake.py
- backend/tests/test_document_intake_integration.py
- backend/tests/test_document_intake_workflow.py
- contracts/openapi.yaml
- docs/customer-documents-merge-notes.md
- docs/customer-documents-plan.md
- fixtures/document_clients.py
- fixtures/documents/1_aviz.pdf
- fixtures/documents/1_carte_identitate.pdf
- fixtures/documents/2_aviz.pdf
- fixtures/documents/2_carte_identitate.pdf
- fixtures/documents/README.md
- fixtures/documents/both_titles.pdf
- fixtures/documents/corrupt.pdf
- fixtures/documents/demo-batch.zip
- fixtures/documents/demo-clients.json
- fixtures/documents/encrypted.pdf
- fixtures/documents/expected.json
- fixtures/documents/fonts/FONT_LICENSES.txt
- fixtures/documents/fonts/LiberationSerif-Regular.ttf
- fixtures/documents/identity.jpg
- fixtures/documents/identity.pdf
- fixtures/documents/invalid_checksum.pdf
- fixtures/documents/no_title.pdf
- fixtures/documents/request.pdf.txt
- fixtures/documents/scanned.pdf
- fixtures/documents/two_cnps.pdf
- fixtures/documents/unknown_client.pdf
- fixtures/generate_documents.py
- frontend/src/api/gen/sdk.gen.ts
- frontend/src/api/gen/types.gen.ts
- frontend/src/data/api-source.ts
- frontend/src/data/document-intake.ts
- frontend/src/data/models.ts
- frontend/src/data/source.ts
- frontend/src/documents/IntakeWorkspace.test.tsx
- frontend/src/documents/IntakeWorkspace.tsx
- frontend/src/pages/Cases.tsx
- infra/init/init.sh
- infra/nginx/nginx.conf
