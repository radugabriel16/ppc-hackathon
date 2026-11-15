#!/usr/bin/env python3
"""Seed training history for registered meters into history-db, never catalog-db."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
from uuid import NAMESPACE_URL, uuid5

UTC = timezone.utc
CLIENT_TYPES = {"RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL"}


def last_complete_interval(now):
    available = now-timedelta(minutes=2)
    return available.replace(hour=available.hour//6*6, minute=0, second=0, microsecond=0)


def match_profiles(meters, profiles):
    used, matches = set(), []
    for meter in sorted(meters, key=lambda m: m["client_type"] is None):
        kind = meter["client_type"]
        if kind is not None and kind not in CLIENT_TYPES:
            raise ValueError(f"Unsupported catalog client type: {kind}")
        candidates = [
            profile for profile in profiles if profile["region"] == meter["region"]
            and (kind is None or profile["client_type"] == kind)
        ]
        source = next((p for p in candidates if p["id"] not in used), None)
        if source is None:
            if not candidates:
                raise ValueError(f"No unused history-v2 profile for {meter['external_code']}")
            index = int(hashlib.sha256(meter["external_code"].encode()).hexdigest(), 16)
            source = candidates[index % len(candidates)]
        used.add(source["id"])
        matches.append((meter, source))
    return matches


def uncovered(start, end, existing):
    position = start
    for left, right in existing:
        if right <= position:
            continue
        if left >= end:
            break
        if left > position:
            yield position, left
        position = max(position, right)
        if position >= end:
            return
    if position < end:
        yield position, end


def reading(meter, start, end, energy, received):
    payload = {
        "meterExternalCode": meter["external_code"],
        "readingKey": f"{meter['external_code']}:{start.isoformat()}",
        "seq": int((start-datetime(2020, 1, 1, tzinfo=UTC)).total_seconds()),
        "intervalStart": start.isoformat(), "intervalEnd": end.isoformat(),
        "energyKwh": round(energy, 6),
    }
    raw = json.dumps(payload, sort_keys=True).encode()
    identity = f"filegrid:seed-history-v2:{meter['id']}:{start.isoformat()}"
    return (
        str(uuid5(NAMESPACE_URL, identity)), meter["id"], payload["readingKey"], payload["seq"],
        start, end, Decimal(str(payload["energyKwh"])), received,
        str(uuid5(NAMESPACE_URL, identity+":file")), meter["region_id"],
        raw, hashlib.sha256(raw).hexdigest(),
    )


def seed_history(generator_source, schema_source, days, seed):
    from psycopg.types.json import Jsonb
    from sqlalchemy import text
    from app.core.db import get_catalog_engine
    from history_common import writer_engine

    now = datetime.now(UTC)
    completed_end = last_complete_interval(now)
    origin = (now-timedelta(minutes=10)).replace(hour=0, minute=0, second=0, microsecond=0)
    start = origin-timedelta(days=days)
    finish = now.replace(hour=0, minute=0, second=0, microsecond=0)+timedelta(days=1)
    if origin.date().isoformat() < "2026-05-14":
        raise ValueError("The live model requires an origin on/after 2026-05-14")
    with get_catalog_engine().connect() as catalog:
        meters = [dict(row) for row in catalog.execute(text("""
            SELECT m.id::text,m.external_code,c.client_type::text,
                   m.subregion_id::text AS segment_id,m.asset_id::text,
                   r.id::text AS region_id,r.code AS region
            FROM meters m JOIN network_assets a ON a.id=m.asset_id
            JOIN regions r ON r.id=a.region_id LEFT JOIN clients c ON c.id=m.client_id
            ORDER BY r.code,m.external_code
        """)).mappings()]
        occupied = defaultdict(list)
        for row in catalog.execute(text("""
            SELECT meter_id::text,interval_start,interval_end FROM meter_readings
            WHERE interval_start<:end AND interval_end>:start ORDER BY meter_id,interval_start
        """), {"start": start, "end": finish}):
            occupied[row[0]].append((row[1], row[2]))
    if not meters:
        raise ValueError("No registered catalog meters")
    summary = {"synthetic": True, "database": "history-db", "meters": len(meters), "inserted": 0}
    engine = writer_engine()
    try:
        with engine.begin() as connection, tempfile.TemporaryDirectory(prefix="filegrid-history-") as directory:
            cursor = connection.connection.driver_connection.cursor()
            cursor.execute("SELECT pg_advisory_xact_lock(7346021903)")
            cursor.execute("""
                SELECT meter_id::text,interval_start,interval_end FROM history.meter_readings
                WHERE interval_start<%s AND interval_end>%s ORDER BY meter_id,interval_start
            """, (finish, start))
            for meter_id, left, right in cursor:
                occupied[meter_id].append((left, right))
            for intervals in occupied.values():
                intervals.sort()
            if all(not list(uncovered(start, completed_end, occupied[meter["id"]])) for meter in meters):
                return summary
            root = Path(directory)
            (root / "generate.py").write_text(generator_source)
            (root / "schema_sqlite.sql").write_text(schema_source)
            spec = importlib.util.spec_from_file_location("history_v2", root / "generate.py")
            generator = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(generator)
            generator.generate(root / "data", seed=seed, start=start.date().isoformat(), end=finish.date().isoformat())
            with sqlite3.connect(root / "data/history.sqlite") as source:
                source.row_factory = sqlite3.Row
                profiles = [dict(row) for row in source.execute("""
                    SELECT c.id,r.code AS region,c.client_type FROM contoare c
                    JOIN segmente s ON s.id=c.segment_id
                    JOIN regiuni r ON r.id=s.region_id ORDER BY c.external_code
                """)]
                for meter, profile in match_profiles(meters, profiles):
                    cursor.execute("""
                        INSERT INTO history.meters VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
                    """, tuple(meter[k] for k in (
                        "id", "external_code", "client_type", "segment_id", "asset_id", "region_id", "region",
                    )))
                    pending = []
                    for interval in source.execute(
                        "SELECT * FROM stats_contor WHERE meter_id=? ORDER BY interval_start", (profile["id"],),
                    ):
                        left, right, received = (
                            datetime.fromisoformat(interval[k])
                            for k in ("interval_start", "interval_end", "received_at")
                        )
                        if right > completed_end or received > now:
                            continue
                        for gap_start, gap_end in uncovered(left, right, occupied[meter["id"]]):
                            pending.append(reading(
                                meter, gap_start, gap_end,
                                interval["energy_kwh"]*((gap_end-gap_start)/(right-left)), received,
                            ))
                    if not pending:
                        continue
                    cursor.executemany("""
                        INSERT INTO history.files(id,metadata) VALUES (%s,%s) ON CONFLICT DO NOTHING
                    """, [(row[8], Jsonb({
                        "id": row[8], "region_id": row[9], "category": "METER_READING",
                        "original_name": f"synthetic-history-v2-{row[8]}.json",
                        "size_bytes": len(row[10]), "sha256": row[11],
                        "storage_backend": "history-db", "synthetic": True,
                    })) for row in pending])
                    cursor.executemany("""
                        INSERT INTO history.file_contents(file_id,content) VALUES (%s,%s) ON CONFLICT DO NOTHING
                    """, [(row[8], row[10]) for row in pending])
                    cursor.executemany("""
                        INSERT INTO history.meter_readings
                        (id,meter_id,reading_key,seq,interval_start,interval_end,energy_kwh,received_at,file_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
                    """, [row[:9] for row in pending])
                    summary["inserted"] += cursor.rowcount
    finally:
        engine.dispose()
    return summary


def main():
    from history_common import ROOT, in_container, print_summary
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.days < 28:
        parser.error("--days must be at least 28")
    if args.inside:
        generator = ROOT / "model-ML/filegrid-history-v2"
        print_summary(seed_history(
            (generator / "generate.py").read_text(), (generator / "schema_sqlite.sql").read_text(),
            args.days, args.seed,
        ))
    else:
        in_container("seed_history.py", ["--days", str(args.days), "--seed", str(args.seed)])


if __name__ == "__main__":
    main()
