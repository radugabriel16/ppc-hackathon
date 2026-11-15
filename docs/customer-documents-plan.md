# Customer document intake plan and findings

Branch: feature/parsare-documente, created from main (84ae9d6), as requested.
The attached specification's branch name is superseded by the user's branch choice.

## Verified existing behavior

- Domain: clients (UUID id), connection_cases (UUID id, client_id), document_types
  (UUID id/code), client_documents (UUID id, case_id, document_type_id, unique file_id).
  Checklist is derived from required document_types and READY files, not a stored flag.
- Three existing required codes: ID, PROOF_OF_ADDRESS, REQUEST_FORM. Reuse ID and
  REQUEST_FORM. Add CONNECTION_APPROVAL; retain PROOF_OF_ADDRESS and its historical
  associations but make it optional, so the required checklist still has three types.
- Client has no CNP. Add unique/indexed cnp_hmac and cnp_masked only; never plaintext.
  Existing demo name_enc/email_enc contain placeholder bytes. UI uses external_code
  as safe customerName rather than pretending to decrypt them.
- Upload: files.service.store_file -> category policy -> encrypted AES-256-GCM
  segmented upload -> SHA-256 catalog -> READY. Downloads use FileReader with hash
  verification, decryption and audited DOCUMENT_DOWNLOAD_REQUESTED.
- Unknown documents need storage before a case is known. Extend this SAME pipeline
  for unassigned CONNECTION_DOCUMENT files (nullable region until linking); do not
  introduce another adapter, bucket or unencrypted queue. Ordinary file lists hide
  unassigned files; intake/review APIs expose them to authenticated operators.
- missing_documents.sync_missing_documents derives checklist gaps and resolves
  MISSING_DOCUMENTS issues automatically. Linking closes the relevant existing issue
  in the same transaction when the required checklist becomes complete.
- Alembic head 0007_forecast_calibration; one new revision 0008_document_intake.
- Worker uses job_run with advisory locks, separate sessions, 5-second poll. Queue
  work in catalog rows, consume with the same worker mechanism; no BackgroundTasks.
- nginx general API limit is 1m, /files 21m. Add specific intake limits 21m single
  and 201m batch; application bounds 20 MiB/file, 50 files, 200 MiB batch total.
- No PDF/text library exists in requirements. Add pinned pypdf and fixture-only
  reportlab. Extraction runs off-event-loop in a bounded threadpool; its underlying
  parsing subprocess is terminated after 10 seconds to avoid runaway PDF tasks.
- scripts/seed_demo.py does not exist. Existing fixtures/seed.py resets demo data;
  bootstrap preserves populated catalogs. Add a separate idempotent demo CNP seed,
  never run the destructive full seed against populated catalogs.

## Implementation

1. Extend OpenAPI first and lint; commit ONLY contracts/openapi.yaml as required.
2. Add HMAC-only identity, durable batches/items and superseded associations.
3. Store first through existing pipeline, verify stored bytes, parse title area and
   first-paragraph CNP; independent per-file processing. No filename heuristics/OCR.
4. Atomic link/checklist/audit, idempotency, optimistic review/replace/reject,
   audited/rate-limited CNP lookup. Reviewer choices are explicit and versioned.
5. Extend Cases with status fields/filters and Manage Customer Documents controls;
   preserve list/grid/scope and add docked manual/identity queues and safe preview.
6. Generate varied synthetic fixtures and test parser, workflow and UI. Run all
   available checks; record Docker/browser or storage checks that cannot run here.

## Environment

No Docker executable or PostgreSQL server found on this host. Real migration,
full-stack smoke scripts and https://localhost UI verification may need a Docker
host. Do not claim these checks passed unless they actually run.

## Implementation details and security adjustments

- First contract-only commit: ee52ddf. No implementation commit is authorized.
- Exclude /customers/lookup from tracing: the prescribed GET API carries CNP in
  query parameters. This one URL exclusion prevents PII entering OTEL spans;
  observability services, dashboards and instrumentation behavior are unchanged.
- Actual PDF parser handles bounded subprocesses (512 MiB address space on Linux),
  a hard 10-second deadline, maximum 20 pages and 250k characters of first-page text.
- CNP validation also accepts county sequence 70 used by SIIEASC. Source:
  https://www.mai.gov.ro/precizari-in-ceea-ce-priveste-generarea-codului-numeric-personal/
  First digits 7–9 do not unambiguously encode a century; calendar validity is
  checked for 1900/2000. This is structural validation, not identity verification.
- JPEG/PNG with no OCR are NO_EXTRACTABLE_TEXT in MANUAL, never guessed as IDENTITY.
  PDFs explicitly titled with an identity marker go to IDENTITY.
- Batch counters report initial auto-link/review/failure classification; confirmed
  and rejected review items remain counted in reviewCount, not autoLinkedCount.
- Rejection text is accepted but not stored unencrypted: audit records the reject
  action and actor/version. No raw CNP or extracted text is written to audit logs.
