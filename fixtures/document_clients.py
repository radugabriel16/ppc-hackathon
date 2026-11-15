"""Idempotent, non-destructive CNP enrichment for existing demo clients."""
from sqlalchemy import select
from app.document_intake.identity import demo_cnp, fingerprint, masked, encrypt_customer_value
from app.models.clients import Client, DocumentType


def seed_document_clients(db):
    demo_clients = [
        (db.scalar(select(Client).where(
            Client.external_code == f'DEMO-{region}-{index:02d}'
        )), (region - 1) * 10 + index)
        for region in range(1, 4) for index in range(1, 11)
    ]
    if not any(client is not None for client, _ in demo_clients):
        demo_clients = [
            (db.scalar(select(Client).where(Client.external_code == f'CLI-{i:04d}')), i)
            for i in range(1, 7)
        ]
    for client, i in demo_clients:
        if client is not None:
            value = demo_cnp(i)
            digest = fingerprint(value)
            if client.cnp_hmac is None:
                client.cnp_hmac, client.cnp_masked = digest, masked(value)
            if client.cnp_enc is None and client.cnp_hmac == digest:
                client.cnp_enc = encrypt_customer_value(value, client.id, field='cnp')
    # Keep the old proof-of-address type/history without requiring a fourth file.
    for dt in db.scalars(select(DocumentType).where(DocumentType.code == 'PROOF_OF_ADDRESS')):
        dt.required_for_connection = False
    approval = db.scalar(select(DocumentType).where(DocumentType.code == 'CONNECTION_APPROVAL'))
    if approval is None:
        from uuid import UUID
        db.add(DocumentType(id=UUID('8cd303ee-e638-4f55-b83d-1595f12eaf24'), code='CONNECTION_APPROVAL',
            name='Connection approval', required_for_connection=True))
