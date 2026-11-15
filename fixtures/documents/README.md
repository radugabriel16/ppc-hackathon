# Synthetic customer document demo

`demo-batch.zip` contains independent mixed files. Extract it before Load Batch;
the web API accepts a list of files, not a ZIP. `expected.json` records expected
parser outcomes. Four correctly recognized files pair requests/approvals for the
first two existing demo clients. The seed client CNPs are in demo-clients.json.

These CNPs pass structural/checksum validation but are fabricated fixtures;
they are not verified real identities. Existing script examples with all-zero
CNPs intentionally fail the production validation introduced in this feature.

A JPEG identity card has no extractable text and is UNKNOWN/NO_EXTRACTABLE_TEXT
in the MANUAL queue until a reviewer chooses ID; it is never guessed to be an ID.
A text PDF whose title says CARTE DE IDENTITATE goes directly to the IDENTITY queue.

Generate again with the pinned dependencies in backend/requirements-test.txt:
`PYTHONPATH=backend:. python fixtures/generate_documents.py`.
The non-destructive bootstrap adds only missing demo CNP HMACs via
fixtures/document_clients.py; it does not reset a populated catalog.
