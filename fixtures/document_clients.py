"""Idempotent, non-destructive CNP enrichment for the six existing demo clients."""
from sqlalchemy import select
from app.document_intake.identity import demo_cnp, fingerprint, masked
from app.models.clients import Client, DocumentType


def seed_document_clients(db):
    for i in range(1, 7):
        client = db.scalar(select(Client).where(Client.external_code == f'CLI-{i:04d}'))
        if client is not None and client.cnp_hmac is None:
            value = demo_cnp(i)
            client.cnp_hmac, client.cnp_masked = fingerprint(value), masked(value)
    # Keep the old proof-of-address type/history without requiring a fourth file.
    for dt in db.scalars(select(DocumentType).where(DocumentType.code == 'PROOF_OF_ADDRESS')):
        dt.required_for_connection = False
    approval = db.scalar(select(DocumentType).where(DocumentType.code == 'CONNECTION_APPROVAL'))
    if approval is None:
        from uuid import UUID
        db.add(DocumentType(id=UUID('8cd303ee-e638-4f55-b83d-1595f12eaf24'), code='CONNECTION_APPROVAL',
            name='Connection approval', required_for_connection=True))
