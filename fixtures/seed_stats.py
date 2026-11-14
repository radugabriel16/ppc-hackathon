"""Add bounded, idempotent demo observations without resetting the catalog."""
import asyncio
import hashlib
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.core.policy_schema import load_policies
from app.core.settings import get_settings
from app.metering.schemas import MeterReadingIngest
from app.metering.service import ingest_reading
from app.models.enums import FileCategory, FileStatus
from app.models.files import File
from app.models.geography import NetworkAsset, Region
from app.models.metering import Meter
from app.models.outages import Outage
from app.policies.service import PolicyManager
from app.storage.registry import create_storages


async def seed_demo():
    settings = get_settings()
    manager = PolicyManager(load_policies(settings.policies_path), create_storages(settings))
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    with Session(get_catalog_engine()) as db:
        rows = db.execute(
            select(Meter.external_code, NetworkAsset.id, NetworkAsset.region_id, Region.code)
            .join(NetworkAsset, NetworkAsset.id == Meter.asset_id)
            .join(Region, Region.id == NetworkAsset.region_id)
            .order_by(Region.code, Meter.external_code)
        ).all()
    selected = {row.code: row for row in reversed(rows)}
    if set(selected) != {"MUNTENIA", "BANAT", "DOBROGEA"}:
        raise RuntimeError("Seed the three demo regions and their meters first")
    for index, row in enumerate(selected.values(), 1):
        for day in range(1, 4):
            for hour in (8, 16):
                start = today - timedelta(days=day) + timedelta(hours=hour)
                payload = {
                    "meterExternalCode": row.external_code,
                    "readingKey": f"{row.external_code}:{start.isoformat()}",
                    "seq": day * 24 + hour, "intervalStart": start.isoformat(),
                    "intervalEnd": (start + timedelta(minutes=15)).isoformat(),
                    "energyKwh": index * day + hour / 4,
                }
                raw = json.dumps(payload, sort_keys=True).encode()
                with Session(get_catalog_engine()) as db:
                    await ingest_reading(
                        MeterReadingIngest.model_validate(payload), raw,
                        hashlib.sha256(raw).hexdigest(), manager, db,
                    )
        # Stable per-day identifiers keep repeat smoke runs from duplicating outages.
        file_id = uuid.uuid5(uuid.NAMESPACE_URL, f"filegrid:stats-demo:{row.code}:{today.date()}")
        with Session(get_catalog_engine()) as db:
            if db.get(File, file_id) is not None:
                continue
        start = today - timedelta(days=1, hours=index)
        raw = json.dumps({"demo": True, "assetId": str(row.id), "startedAt": start.isoformat()}).encode()
        write = await manager.put(
            FileCategory.OUTAGE_RECORD, str(file_id), io.BytesIO(raw), len(raw),
        )
        with Session(get_catalog_engine()) as db:
            db.add(File(
                id=file_id, region_id=row.region_id, category=FileCategory.OUTAGE_RECORD,
                original_name=f"stats-demo-{row.code}.json", media_type="application/json",
                size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                storage_backend=write.backend, storage_locator=write.stored.locator,
                fallback_used=write.fallback_used, status=FileStatus.READY,
                created_at=start, ready_at=start,
            ))
            db.flush()
            db.add(Outage(
                asset_id=row.id, file_id=file_id, started_at=start,
                ended_at=start + timedelta(minutes=30 * index), severity="LOW",
                description="Seeded statistics demo observation",
            ))
            db.commit()
    return {"meters": len(selected), "days": 3}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(seed_demo())))
