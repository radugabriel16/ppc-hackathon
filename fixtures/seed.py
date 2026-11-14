#!/usr/bin/env python3
"""Deterministic fixture seed for catalog-db (PHASE1.md Step 1).

Same UUIDs as contracts/examples/*.json, derived from `uuid5(NAMESPACE_URL,
"filegrid:<slug>")` so re-running this script is idempotent and reproducible
across machines.

Usage:
    ALEMBIC_DATABASE_URL=postgresql+psycopg://... python fixtures/seed.py
(falls back to the app's own Settings-derived DSN if that env var is unset)
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from geoalchemy2.elements import WKTElement  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.settings import get_settings  # noqa: E402
from app.models import (  # noqa: E402
    Client,
    ClientDocument,
    ConnectionCase,
    DocumentType,
    File,
    MapIssue,
    Meter,
    NetworkAsset,
    Region,
)
from app.models.enums import (  # noqa: E402
    AssetType,
    CaseStatus,
    ClientType,
    FileCategory,
    FileStatus,
    IssueSeverity,
    IssueStatus,
    StorageBackend,
)

NOW = datetime(2026, 1, 10, 8, 0, 0, tzinfo=timezone.utc)


def uid(slug: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"filegrid:{slug}")


def point(lon: float, lat: float) -> WKTElement:
    return WKTElement(f"POINT({lon} {lat})", srid=4326)


REGIONS = [
    {"slug": "region-muntenia", "code": "MUNTENIA", "name": "Muntenia", "center": (26.1025, 44.4268)},
    {"slug": "region-banat", "code": "BANAT", "name": "Banat", "center": (21.2087, 45.7489)},
    {"slug": "region-dobrogea", "code": "DOBROGEA", "name": "Dobrogea", "center": (28.6500, 44.1800)},
]

ASSET_TYPES = [AssetType.SUBSTATION, AssetType.TRANSFORMER, AssetType.LINE_SEGMENT]
ASSETS_PER_REGION = 5

DOCUMENT_TYPES = [
    {"slug": "doctype-id", "code": "ID", "name": "Identity document"},
    {"slug": "doctype-proof-address", "code": "PROOF_OF_ADDRESS", "name": "Proof of address"},
    {"slug": "doctype-request-form", "code": "REQUEST_FORM", "name": "Connection request form"},
]

CLIENT_COUNT = 6
METER_COUNT = 12


def build_session() -> Session:
    dsn = os.environ.get("ALEMBIC_DATABASE_URL") or get_settings().catalog_db_dsn
    engine = create_engine(dsn)
    return Session(bind=engine)


def reset_tables(session: Session) -> None:
    session.execute(
        text(
            "TRUNCATE map_issues, meters, client_documents, connection_cases, clients, "
            "files, network_assets, regions, document_types RESTART IDENTITY CASCADE"
        )
    )


def seed(session: Session) -> None:
    reset_tables(session)

    # --- regions -----------------------------------------------------------
    regions = []
    for r in REGIONS:
        region = Region(
            id=uid(r["slug"]),
            code=r["code"],
            name=r["name"],
            center=point(*r["center"]),
            bounds={
                "minLon": r["center"][0] - 2,
                "minLat": r["center"][1] - 1,
                "maxLon": r["center"][0] + 2,
                "maxLat": r["center"][1] + 1,
            },
        )
        session.add(region)
        regions.append(region)
    session.flush()

    # --- network assets (~5 per region) ------------------------------------
    assets: list[NetworkAsset] = []
    for region, r in zip(regions, REGIONS):
        prefix = r["code"][:3]
        for i in range(1, ASSETS_PER_REGION + 1):
            asset_type = ASSET_TYPES[(i - 1) % len(ASSET_TYPES)]
            lon, lat = r["center"][0] + 0.01 * i, r["center"][1] + 0.01 * i
            asset = NetworkAsset(
                id=uid(f"asset-{r['code'].lower()}-{i}"),
                region_id=region.id,
                code=f"{prefix}-{asset_type.value[:3]}-{i:03d}",
                name=f"{r['name']} {asset_type.value.title()} {i}",
                type=asset_type,
                geometry=point(lon, lat),
                rated_capacity_kw=1000 * i if asset_type != AssetType.LINE_SEGMENT else None,
            )
            session.add(asset)
            assets.append(asset)
    session.flush()

    # --- document types ------------------------------------------------------
    doc_types = []
    for dt in DOCUMENT_TYPES:
        doc_type = DocumentType(
            id=uid(dt["slug"]), code=dt["code"], name=dt["name"], required_for_connection=True
        )
        session.add(doc_type)
        doc_types.append(doc_type)
    session.flush()

    # --- clients + connection cases ------------------------------------------
    clients: list[Client] = []
    cases: list[ConnectionCase] = []
    client_types = [ClientType.RESIDENTIAL, ClientType.COMMERCIAL, ClientType.INDUSTRIAL]
    for i in range(1, CLIENT_COUNT + 1):
        region = regions[(i - 1) % len(regions)]
        client = Client(
            id=uid(f"client-{i}"),
            region_id=region.id,
            external_code=f"CLI-{i:04d}",
            name_enc=f"demo-client-{i}".encode(),
            email_enc=f"demo-client-{i}@example.invalid".encode(),
            location=None,
            client_type=client_types[(i - 1) % len(client_types)],
        )
        session.add(client)
        clients.append(client)
        case = ConnectionCase(
            id=uid(f"case-{i}"),
            client_id=client.id,
            status=CaseStatus.OPEN if i % 2 else CaseStatus.CLOSED,
            opened_at=NOW - timedelta(days=5 * i),
            due_at=NOW + timedelta(days=30 - i),
        )
        session.add(case)
        cases.append(case)
    session.flush()

    # --- one demo CONNECTION_DOCUMENT file + checklist entry -----------------
    conndoc_file = File(
        id=uid("file-conndoc-1"),
        region_id=regions[0].id,
        category=FileCategory.CONNECTION_DOCUMENT,
        original_name="id-card.pdf",
        media_type="application/pdf",
        size_bytes=204800,
        sha256="e" * 64,
        storage_backend=StorageBackend.s3,
        storage_locator=f"connection-document/{uid('file-conndoc-1')}",
        status=FileStatus.READY,
        encrypted=True,
        encryption_key_id="demo-key-1",
        created_at=NOW,
        ready_at=NOW,
        last_verified_at=NOW,
    )
    session.add(conndoc_file)
    session.flush()
    session.add(
        ClientDocument(
            id=uuid.UUID("11111111-1111-5111-9111-111111111111"),
            case_id=cases[0].id,
            document_type_id=doc_types[0].id,
            file_id=conndoc_file.id,
            uploaded_at=NOW,
        )
    )

    # --- one demo OUTAGE_RECORD file -----------------------------------------
    outage_file = File(
        id=uid("file-outage-1"),
        region_id=regions[0].id,
        category=FileCategory.OUTAGE_RECORD,
        original_name="outage-2026-01-10.json",
        media_type="application/json",
        size_bytes=4096,
        sha256="d" * 64,
        storage_backend=StorageBackend.ftp,
        storage_locator=f"outage-record/{uid('file-outage-1')}",
        status=FileStatus.READY,
        created_at=NOW,
        ready_at=NOW + timedelta(seconds=2),
        last_verified_at=NOW + timedelta(seconds=2),
    )
    session.add(outage_file)
    session.flush()

    # --- meters (12, spread across assets and a few clients) ----------------
    for i in range(1, METER_COUNT + 1):
        asset = assets[(i - 1) % len(assets)]
        client = clients[(i - 1) % len(clients)] if i % 2 == 0 else None
        session.add(
            Meter(
                id=uid(f"meter-{i}"),
                external_code=f"MTR-{i:04d}",
                asset_id=asset.id,
                client_id=client.id if client else None,
            )
        )

    # --- map issues (4) -------------------------------------------------------
    severities = [IssueSeverity.HIGH, IssueSeverity.MEDIUM, IssueSeverity.LOW, IssueSeverity.CRITICAL]
    for i in range(1, 5):
        asset = assets[(i - 1) * 3 % len(assets)]
        session.add(
            MapIssue(
                id=uid(f"issue-{i}"),
                asset_id=asset.id,
                location=point(26.11 + 0.01 * i, 44.43 + 0.01 * i),
                description=f"Demo issue {i}",
                severity=severities[i - 1],
                status=IssueStatus.OPEN,
                created_at=NOW - timedelta(days=i),
                version=1,
            )
        )

    session.flush()
    from fixtures.geography import seed_geography
    seed_geography(session)
    session.commit()


def main() -> None:
    session = build_session()
    try:
        seed(session)
        print("Seed complete.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
