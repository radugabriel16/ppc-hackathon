#!/usr/bin/env python3
"""Deterministic, validated small operational demo; --reset removes only owned demo rows."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from history_common import ROOT, in_container, print_summary, writer_engine


def identity(value):
    return uuid5(NAMESPACE_URL, f"filegrid:operational-demo:{value}")


def remember(db, kind, entity_id):
    from sqlalchemy import text
    db.execute(text("""
        INSERT INTO demo_seed_entities(kind,id) VALUES (:kind,:id) ON CONFLICT DO NOTHING
    """), {"kind": kind, "id": entity_id})


def reset_demo(db):
    from sqlalchemy import text
    db.execute(text("""
        DELETE FROM alerts WHERE payload->>'issueId' IN (
            SELECT id::text FROM demo_seed_entities WHERE kind='issue'
        )
    """))
    # Exact ownership is the deletion boundary; unowned operator data is never reset.
    for kind, table in (
        ("issue", "map_issues"), ("reading", "meter_readings"), ("case", "connection_cases"),
    ):
        db.execute(text(f"""
            DELETE FROM {table} WHERE id IN (SELECT id FROM demo_seed_entities WHERE kind=:kind)
        """), {"kind": kind})
    for table in ("client_documents", "outages", "video_inspections"):
        db.execute(text(f"""
            DELETE FROM {table} WHERE file_id IN (
                SELECT id FROM demo_seed_entities WHERE kind='file'
            ) AND NOT EXISTS (SELECT 1 FROM map_issues i WHERE i.file_id={table}.file_id
                              OR i.video_inspection_id={table}.id)
        """))
    from split_history import remove_unreferenced_files
    file_ids = db.scalars(text("SELECT id FROM demo_seed_entities WHERE kind='file'")).all()
    remove_unreferenced_files(db, file_ids)
    db.execute(text("""
        DELETE FROM demo_seed_entities d WHERE
          (kind='issue' AND NOT EXISTS (SELECT 1 FROM map_issues WHERE id=d.id)) OR
          (kind='reading' AND NOT EXISTS (SELECT 1 FROM meter_readings WHERE id=d.id)) OR
          (kind='case' AND NOT EXISTS (SELECT 1 FROM connection_cases WHERE id=d.id)) OR
          (kind='file' AND NOT EXISTS (SELECT 1 FROM files WHERE id=d.id))
    """))
    db.commit()


async def seed_demo(reset=False):
    import anyio
    from sqlalchemy import text
    from app.core.db import get_catalog_engine

    keys = [7346021903] + [
        int.from_bytes(uuid5(NAMESPACE_URL, f"filegrid:job:{name}").bytes[:8], "big", signed=True)
        for name in ("missing_document_issues", "reminders", "daily_forecasts", "orphan_contents")
    ]
    connection = get_catalog_engine().connect().execution_options(isolation_level="AUTOCOMMIT")
    acquired = []
    def acquire():
        connection.execute(text("SET lock_timeout='30s'"))
        for key in keys:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
            acquired.append(key)
    def release():
        try:
            for key in reversed(acquired):
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
        finally:
            connection.close()
    try:
        await anyio.to_thread.run_sync(acquire)
        return await _seed_demo(reset)
    finally:
        await anyio.to_thread.run_sync(release)


async def _seed_demo(reset=False):
    from contextlib import aclosing
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import secrets
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session
    from app.core.db import get_catalog_engine, get_history_engine, get_storage_engine
    from app.core.policy_schema import load_policies
    from app.core.settings import get_settings
    from app.documents.encryption import DocumentKey
    from app.files.multipart import MultipartUpload
    from app.files.schemas import metadata_adapter
    from app.files.service import _store_file, FileReader
    from app.forecast.thresholds import calibrate_threshold
    from app.issues.router import create_validated_issue
    from app.issues.schemas import IssueCreate
    from app.jobs.missing_documents import sync_missing_documents
    from app.models.auth import AppUser
    from app.models.enums import IssueType
    from app.models.files import File
    from app.models.issues import MapIssue
    from app.policies.service import PolicyManager
    from app.storage.registry import create_storages
    from seed_history import seed_history, last_complete_interval

    settings = get_settings()
    manager = PolicyManager(load_policies(settings.policies_path), create_storages(settings))
    key = DocumentKey.load(settings)
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with Session(get_catalog_engine(), expire_on_commit=False) as db:
        if reset:
            reset_demo(db)
        segments = db.execute(text("""
            SELECT s.id,s.region_id,s.code,ST_AsEWKT(ST_PointOnSurface(s.geometry)) AS point,
                   ST_X(ST_PointOnSurface(s.geometry)) AS lon,ST_Y(ST_PointOnSurface(s.geometry)) AS lat,
                   (SELECT id FROM network_assets WHERE subregion_id=s.id ORDER BY code LIMIT 1) AS asset_id
            FROM subregions s ORDER BY s.code
        """)).mappings().all()
        if len(segments) != 18 or db.scalar(text("SELECT count(*) FROM regions")) != 3:
            raise ValueError("Expected the real 3-region / 18-segment topology")
        counts = db.execute(text("SELECT subregion_id,count(*) FROM meters GROUP BY subregion_id")).all()
        if len(counts) != 18 or any(count != 8 for _, count in counts):
            raise ValueError("Expected exactly 8 registered meters per segment; IDs are never replaced")
        actor = db.scalar(select(AppUser).where(AppUser.username == "operator"))
        if actor is None:
            raise ValueError("Demo operator is not initialized")
        actor_id = actor.id
        # Preserve each existing meter's client type, hence the model's calibrated scale.
        original_types = db.execute(text("""
            SELECT m.id,a.region_id,c.client_type::text FROM meters m
            JOIN network_assets a ON a.id=m.asset_id LEFT JOIN clients c ON c.id=m.client_id
        """)).all()
        clients_by_type = {}
        case_ids = []
        region_ids = sorted({s["region_id"] for s in segments}, key=str)
        for region_index, region_id in enumerate(region_ids):
            areas = [s for s in segments if s["region_id"] == region_id]
            for index in range(10):
                area = areas[index % 6]
                client_id = identity(f"client:{region_id}:{index}")
                case_id = identity(f"case:{region_id}:{index}")
                kind = ("RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL")[index % 3]
                def encrypted(value):
                    nonce = secrets.token_bytes(12)
                    return nonce + AESGCM(key.value).encrypt(nonce, value.encode(), client_id.bytes)
                db.execute(text("""
                    INSERT INTO clients(id,region_id,external_code,name_enc,email_enc,location,client_type)
                    VALUES (:id,:region,:code,:name,:email,ST_GeomFromEWKT(:point),CAST(:type AS client_type))
                    ON CONFLICT DO NOTHING
                """), {"id": client_id, "region": region_id, "code": f"DEMO-{region_index+1}-{index+1:02d}",
                       "name": encrypted(f"Synthetic demo client {index+1}"),
                       "email": encrypted(f"demo-{region_index+1}-{index+1}@example.invalid"),
                       "point": area["point"], "type": kind})
                remember(db, "client", client_id)
                clients_by_type.setdefault((region_id, kind), []).append(client_id)
                db.execute(text("""
                    INSERT INTO connection_cases(id,client_id,status,opened_at,due_at)
                    VALUES (:id,:client,CAST(:status AS case_status),:opened,:due) ON CONFLICT DO NOTHING
                """), {"id": case_id, "client": client_id, "status": "OPEN" if index < 7 else "CLOSED",
                       "opened": today-timedelta(days=index+1), "due": today+timedelta(days=10+index)})
                remember(db, "case", case_id)
                case_ids.append((case_id, area, index))
        for index, (meter_id, region_id, kind) in enumerate(original_types):
            if kind is not None:
                candidates = clients_by_type[(region_id, kind)]
                db.execute(text("UPDATE meters SET client_id=:client WHERE id=:id"),
                           {"client": candidates[index % len(candidates)], "id": meter_id})
        # Old topology clients were already verified by split_history. Remove only
        # archived, unreferenced synthetic clients, never real clients or cases.
        with get_history_engine().connect() as history:
            archived_clients = history.scalars(text("SELECT id FROM history.synthetic_clients")).all()
        db.execute(text("""
            DELETE FROM clients c WHERE id=ANY(:ids)
            AND NOT EXISTS (SELECT 1 FROM meters WHERE client_id=c.id)
            AND NOT EXISTS (SELECT 1 FROM connection_cases WHERE client_id=c.id)
            AND NOT EXISTS (SELECT 1 FROM map_issues WHERE client_id=c.id)
        """), {"ids": archived_clients})
        db.commit()
        generator = ROOT / "model-ML/filegrid-history-v2"
        # Fill missing training coverage on a fresh stack, without adding catalog files.
        history_summary = seed_history(
            (generator / "generate.py").read_text(), (generator / "schema_sqlite.sql").read_text(), 730, 42,
        )
        with get_history_engine().connect() as history:
            recent = history.execute(text("""
                SELECT mr.*,fc.content FROM history.meter_readings mr
                JOIN history.file_contents fc ON fc.file_id=mr.file_id
                WHERE interval_start>=:start AND interval_end<=:end
                ORDER BY meter_id,interval_start
            """), {"start": today-timedelta(days=14), "end": last_complete_interval(now)}).mappings().all()
        readings_inserted = 0
        for row in recent:
            if db.scalar(text("""
                SELECT 1 FROM meter_readings WHERE meter_id=:meter AND reading_key=:key
                   OR meter_id=:meter AND interval_start<:end AND interval_end>:start
            """), {"meter": row["meter_id"], "key": row["reading_key"],
                   "start": row["interval_start"], "end": row["interval_end"]}):
                continue
            raw = bytes(row["content"])
            from app.metering.schemas import MeterReadingIngest
            MeterReadingIngest.model_validate_json(raw)
            with get_storage_engine().begin() as storage:
                storage.execute(text("""
                    INSERT INTO file_contents(file_id,content) VALUES (:id,:content) ON CONFLICT DO NOTHING
                """), {"id": row["file_id"], "content": raw})
                stored = bytes(storage.scalar(text("SELECT content FROM file_contents WHERE file_id=:id"),
                                              {"id": row["file_id"]}))
                if stored != raw:
                    raise ValueError("Recent demo reading payload verification failed")
            db.execute(text("""
                INSERT INTO files(id,region_id,category,original_name,media_type,size_bytes,sha256,
                                  storage_backend,storage_locator,status,fallback_used,encrypted,created_at,ready_at)
                SELECT :id,a.region_id,'METER_READING',:name,'application/json',:size,:sha,
                       'db',CAST(:id AS text),'READY',false,false,:received,:received
                FROM meters m JOIN network_assets a ON a.id=m.asset_id WHERE m.id=:meter
                ON CONFLICT DO NOTHING
            """), {"id": row["file_id"], "name": f"demo-reading-{row['file_id']}.json", "size": len(raw),
                   "sha": hashlib.sha256(raw).hexdigest(), "meter": row["meter_id"], "received": row["received_at"]})
            db.execute(text("""
                INSERT INTO meter_readings(id,meter_id,reading_key,seq,interval_start,interval_end,
                                           energy_kwh,file_id,received_at)
                VALUES (:id,:meter_id,:reading_key,:seq,:interval_start,:interval_end,
                        :energy_kwh,:file_id,:received_at) ON CONFLICT DO NOTHING
            """), dict(row))
            remember(db, "reading", row["id"])
            remember(db, "file", row["file_id"])
            readings_inserted += 1
        db.commit()
        document_types = db.scalars(text("""
            SELECT id FROM document_types WHERE required_for_connection ORDER BY code
        """)).all()
        if len(document_types) != 3:
            raise ValueError("Expected the three real required document types")
        files_created = 0
        video_files = {}
        specs = []
        for region_index, region_id in enumerate(region_ids):
            areas = [s for s in segments if s["region_id"] == region_id]
            region_cases = [(c, s, i) for c, s, i in case_ids if s["region_id"] == region_id]
            for case_id, area, index in region_cases:
                if index < (9 if region_index == 0 else 8):
                    for document_type in document_types:
                        specs.append((f"form:{case_id}:{document_type}",
                            small_pdf(), "application/pdf", {
                                "category": "CONNECTION_DOCUMENT", "caseId": str(case_id),
                                "documentTypeId": str(document_type), "regionId": str(region_id),
                            }))
            for index in range(1):
                area = areas[index]
                content = json.dumps({"demo": True, "assetId": str(area["asset_id"]),
                                      "outage": index+1}).encode()
                specs.append((f"outage:{area['id']}", content, "application/json", {
                    "category": "OUTAGE_RECORD", "assetId": str(area["asset_id"]), "regionId": str(region_id),
                    "startedAt": (today-timedelta(hours=index+1)).isoformat(),
                    "severity": "MEDIUM", "description": "Demo operational interruption",
                }))
            for index in range(1):
                area = areas[index]
                # A tiny AVI with one uncompressed 1x1 frame, not a missing placeholder.
                content = tiny_avi()
                specs.append((f"video:{area['id']}", content, "video/x-msvideo", {
                    "category": "DRONE_VIDEO", "assetId": str(area["asset_id"]), "regionId": str(region_id),
                    "recordedAt": (today-timedelta(hours=index+1)).isoformat(),
                }))
        for slug, content, media_type, metadata in specs:
            file_id = identity(slug)
            file = db.get(File, file_id)
            if file is None:
                upload = MultipartUpload(manager.config)
                try:
                    upload.metadata = metadata_adapter.validate_python(metadata)
                    upload.filename = f"demo-{slug.replace(':','-')}.{'avi' if media_type.startswith('video') else 'pdf' if media_type=='application/pdf' else 'json'}"
                    upload.media_type = media_type
                    upload.stream.write(content)
                    upload.stream.seek(0)
                    upload.size = len(content)
                    upload.sha256.update(content)
                    from app.uploads.locking import upload_lock
                    async with upload_lock(file_id):
                        await _store_file(upload, manager, key, db, actor_id, file_id)
                    files_created += 1
                finally:
                    upload.stream.close()
                file = db.get(File, file_id)
            if file.sha256 != hashlib.sha256(content).hexdigest():
                raise ValueError(f"Demo identity has different bytes: {file_id}")
            db.commit()
            reader = FileReader(file, manager, key, actor_id, None)
            async with aclosing(reader.chunks()) as chunks:
                downloaded = b"".join([chunk async for chunk in chunks])
            if downloaded != content:
                raise ValueError(f"Demo file round-trip failed: {file_id}")
            remember(db, "file", file_id)
            if metadata["category"] == "DRONE_VIDEO":
                video_files[metadata["assetId"]] = file_id
            db.commit()
        # Five incomplete checklists; required types and worker semantics are unchanged.
        sync_missing_documents(db, lambda case_id: identity(f"missing:{case_id}"))
        for issue in db.scalars(select(MapIssue).where(
            MapIssue.type == IssueType.MISSING_DOCUMENTS,
            MapIssue.case_id.in_([c for c, _, _ in case_ids]),
        )):
            remember(db, "issue", issue.id)
        db.commit()
        selected_areas = [
            area for region in region_ids
            for area in [s for s in segments if s["region_id"] == region][:2]
        ]
        for index, area in enumerate(selected_areas):
            kind = ("OUTAGE_REPORT", "OUTAGE_VIDEO", "DRONE_DETECTED")[index % 3]
            file_id = next(
                (identity(f"video:{s['id']}") for s in segments
                 if s["region_id"] == area["region_id"] and str(s["asset_id"]) in video_files),
                None,
            )
            slug = f"issue:{area['id']}"
            issue_id = identity(slug)
            if db.get(MapIssue, issue_id) is None:
                body = IssueCreate.model_validate({
                    "assetId": str(area["asset_id"]), "type": kind,
                    "regionId": str(area["region_id"]), "segmentId": str(area["id"]),
                    "fileId": str(file_id) if kind != "OUTAGE_REPORT" else None,
                    "location": {"type": "Point", "coordinates": [area["lon"], area["lat"]]},
                    "severity": ("LOW", "MEDIUM", "HIGH", "CRITICAL")[index % 4],
                    "description": "Operational demo inspection",
                })
                user = db.get(AppUser, actor_id)
                create_validated_issue(body, user, db, issue_id)
            remember(db, "issue", issue_id)
            db.commit()
        for area in segments:
            calibrate_threshold(db, area["id"], now)
        db.commit()
        from app.forecast.runs import exceedance_issue
        from app.forecast.service import ForecastRuntime
        from app.models.forecast import SegmentThreshold
        from app.models.geography import Subregion
        runtime = ForecastRuntime()
        origin = (now-timedelta(minutes=10)).date()
        db.execute(text("DELETE FROM forecast_snapshots"))
        db.commit()
        for asset_id in db.scalars(text("""
            SELECT id FROM network_assets a WHERE EXISTS (SELECT 1 FROM meters WHERE asset_id=a.id)
        """)).all():
            result = runtime.get(db, str(asset_id), origin)
            from psycopg.types.json import Jsonb
            db.connection().connection.driver_connection.execute("""
                INSERT INTO forecast_snapshots(asset_id,origin,result) VALUES (%s,%s,%s)
                ON CONFLICT (asset_id,origin) DO UPDATE SET result=excluded.result
            """, (asset_id, origin, Jsonb(result)))
        db.commit()
        for area in segments:
            result = runtime.get_subregion(db, str(area["id"]), today.date()+timedelta(days=1))
            if result["fallbackUsed"] or result["method"] != "hgb_smooth":
                raise ValueError(f"Demo forecast must use the real model: {area['code']}")
            threshold = float(db.get(SegmentThreshold, area["id"]).daily_energy_kwh)
            for point in result["forecasts"]:
                if point["status"] == "READY" and point["predictedEnergyKwh"] > threshold:
                    issue = exceedance_issue(
                        db, db.get(Subregion, area["id"]), point, threshold, actor_id, now,
                        identity(f"forecast:{area['id']}:{point['date']}"),
                    )
                    if issue:
                        from uuid import UUID
                        remember(db, "issue", UUID(issue["id"]))
        db.commit()
        return {
            "history": history_summary, "readingsInserted": readings_inserted, "filesCreated": files_created,
            "counts": {table: db.scalar(text(f"SELECT count(*) FROM {table}")) for table in (
                "regions", "subregions", "meters", "clients", "connection_cases", "files", "meter_readings", "map_issues",
            )},
            "historicalIssues": db.scalar(text("SELECT count(*) FROM map_issues WHERE is_historical")),
        }


def tiny_avi():
    import struct
    def chunk(kind, data):
        return kind + struct.pack("<I", len(data)) + data + (b"\0" if len(data) % 2 else b"")
    def group(kind, data):
        return chunk(b"LIST", kind + data)
    header = struct.pack("<14I", 1000000, 4, 0, 0x10, 1, 0, 1, 4, 1, 1, 0, 0, 0, 0)
    stream = struct.pack("<4s4sIHH8I4h", b"vids", b"DIB ", 0, 0, 0, 0, 1, 1, 0, 1, 4, 0xffffffff, 0, 0, 0, 1, 1)
    bitmap = struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 24, 0, 4, 0, 0, 0, 0)
    body = b"AVI " + group(b"hdrl", chunk(b"avih", header) + group(
        b"strl", chunk(b"strh", stream) + chunk(b"strf", bitmap),
    )) + group(b"movi", chunk(b"00db", b"\x40\x80\x40\0")) + chunk(
        b"idx1", struct.pack("<4sIII", b"00db", 0x10, 4, 4),
    )
    return chunk(b"RIFF", body)


def small_pdf():
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << >> /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(content))
        content.extend(f"{number} 0 obj\n".encode()+body+b"\nendobj\n")
    xref = len(content)
    content.extend(b"xref\n0 5\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside:
        import asyncio
        print_summary(asyncio.run(seed_demo(args.reset)))
    else:
        in_container("seed_demo.py", ["--reset"] if args.reset else [])


if __name__ == "__main__":
    main()
