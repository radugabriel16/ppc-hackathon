#!/usr/bin/env python3
"""Seed synthetic history for existing meters through the running Compose stack."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from uuid import NAMESPACE_URL, uuid5

UTC = timezone.utc
CLIENT_TYPES = {"RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL"}


def match_profiles(meters, profiles):
    """Reserve matching typed profiles first; never assign types to catalog meters."""
    used = set()
    matches = []
    for meter in sorted(meters, key=lambda m: m["client_type"] is None):
        kind = meter["client_type"]
        if kind is not None and kind not in CLIENT_TYPES:
            raise ValueError(f"Unsupported catalog client type: {kind}")
        source = next((
            profile for profile in profiles
            if profile["id"] not in used and profile["region"] == meter["region"]
            and (kind is None or profile["client_type"] == kind)
        ), None)
        if source is None:
            raise ValueError(f"No unused history-v2 profile for {meter['external_code']}")
        used.add(source["id"])
        matches.append((meter, source))
    return matches


def uncovered(start, end, existing):
    """Keep existing observations; fill only gaps, including partial six-hour slots."""
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
    from decimal import Decimal

    key = f"{meter['external_code']}:{start.isoformat()}"
    payload = {
        "meterExternalCode": meter["external_code"], "readingKey": key,
        "seq": int((start - datetime(2020, 1, 1, tzinfo=UTC)).total_seconds()),
        "intervalStart": start.isoformat(), "intervalEnd": end.isoformat(),
        "energyKwh": round(energy, 6),
    }
    raw = json.dumps(payload, sort_keys=True).encode()
    identity = f"filegrid:seed-history-v2:{meter['id']}:{start.isoformat()}"
    return (
        str(uuid5(NAMESPACE_URL, identity)), meter["id"], key, payload["seq"],
        start, end, Decimal(str(payload["energyKwh"])), received,
        str(uuid5(NAMESPACE_URL, identity + ":file")), meter["region_id"],
        raw, hashlib.sha256(raw).hexdigest(),
    )


def seed_history(generator_source, schema_source, days, seed):
    from psycopg.rows import dict_row
    from app.core.db import get_catalog_engine, get_storage_engine

    now = datetime.now(UTC)
    origin = (now - timedelta(minutes=10)).replace(hour=0, minute=0, second=0, microsecond=0)
    if origin.date().isoformat() < "2026-05-14":
        raise ValueError("The live model requires an origin on/after 2026-05-14")
    start = origin - timedelta(days=days)
    finish = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    summary = {
        "synthetic": True, "generator": "filegrid-history-v2", "seed": seed,
        "start": start.isoformat(), "asOf": now.isoformat(),
        "origin": origin.date().isoformat(), "days": days,
    }
    with get_catalog_engine().begin() as connection:
        db = connection.connection.driver_connection
        with db.cursor(row_factory=dict_row) as cursor:
            # Serialize seeders and ingest while checking interval gaps and inserting.
            cursor.execute("LOCK TABLE meter_readings IN SHARE ROW EXCLUSIVE MODE")
            cursor.execute("""
                SELECT m.id::text, m.external_code, c.client_type::text,
                       a.id::text AS segment_id, r.id::text AS region_id, r.code AS region
                FROM meters m JOIN network_assets a ON a.id = m.asset_id
                JOIN regions r ON r.id = a.region_id
                LEFT JOIN clients c ON c.id = m.client_id
                ORDER BY r.code, m.external_code
            """)
            catalog = cursor.fetchall()
            if not catalog:
                raise ValueError("No existing catalog meters")
            summary["meters"] = len(catalog)
            cursor.execute("""
                SELECT meter_id::text, interval_start, interval_end, received_at
                FROM meter_readings
                WHERE interval_start < %s AND interval_end > %s
                ORDER BY meter_id, interval_start, interval_end
            """, (finish, start))
            occupied = defaultdict(list)
            late = 0
            for row in cursor:
                occupied[row["meter_id"]].append((row["interval_start"], row["interval_end"]))
                if row["interval_start"] < origin and row["received_at"] > origin + timedelta(minutes=10):
                    late += 1
            summary["warnings"] = [{
                "code": "LATE_EXISTING_READINGS", "count": late,
                "message": "Existing arrivals after the model cutoff are preserved; affected meters may use a baseline.",
            }] if late else []
            pending = []
            with tempfile.TemporaryDirectory(prefix="filegrid-history-") as directory:
                root = Path(directory)
                (root / "generate.py").write_text(generator_source)
                (root / "schema_sqlite.sql").write_text(schema_source)
                spec = importlib.util.spec_from_file_location("history_v2", root / "generate.py")
                generator = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(generator)
                generator.generate(
                    root / "data", seed=seed, start=start.date().isoformat(),
                    end=finish.date().isoformat(),
                )
                with sqlite3.connect(root / "data/history.sqlite") as history:
                    history.row_factory = sqlite3.Row
                    profiles = [dict(row) for row in history.execute("""
                        SELECT c.id, r.code AS region, c.client_type FROM contoare c
                        JOIN segmente s ON s.id = c.segment_id
                        JOIN regiuni r ON r.id = s.region_id ORDER BY c.external_code
                    """)]
                    summary["profiles"] = {}
                    summary["syntheticProfileMeters"] = []
                    for meter, profile in match_profiles(catalog, profiles):
                        source = profile["id"]
                        summary["profiles"][meter["external_code"]] = source
                        if meter["client_type"] is None:
                            summary["syntheticProfileMeters"].append({
                                "meter": meter["external_code"],
                                "reason": "MISSING_CLIENT_TYPE",
                                "syntheticProfileType": profile["client_type"],
                                "catalogClientTypeChanged": False,
                            })
                        intervals = occupied[meter["id"]]
                        for row in history.execute("""
                            SELECT * FROM stats_contor WHERE meter_id = ? ORDER BY interval_start
                        """, (source,)):
                            left = datetime.fromisoformat(row["interval_start"])
                            right = datetime.fromisoformat(row["interval_end"])
                            received = datetime.fromisoformat(row["received_at"])
                            # Do not backdate availability or write unfinished/future readings.
                            if received > now:
                                continue
                            for gap_start, gap_end in uncovered(left, right, intervals):
                                energy = row["energy_kwh"] * ((gap_end - gap_start) / (right - left))
                                pending.append(reading(
                                    meter, gap_start, gap_end, energy, received,
                                ))
            summary["candidates"] = len(pending)
            if not pending:
                return {**summary, "inserted": 0, "filesInserted": 0, "payloadsInserted": 0}
            cursor.execute("""
                CREATE TEMP TABLE seed_history_readings (
                    id uuid, meter_id uuid, reading_key text, seq integer,
                    interval_start timestamptz, interval_end timestamptz,
                    energy_kwh numeric, received_at timestamptz, file_id uuid,
                    region_id uuid, content bytea, sha256 text
                ) ON COMMIT DROP
            """)
            with cursor.copy("COPY seed_history_readings FROM STDIN") as copy:
                for row in pending:
                    copy.write_row(row)
            # As with ingest, durable bytes precede READY catalog rows. On a catalog
            # failure the normal orphan collector can reclaim unreferenced payloads.
            with get_storage_engine().begin() as storage_connection:
                storage = storage_connection.connection.driver_connection
                with storage.cursor() as storage_cursor:
                    storage_cursor.execute("""
                        CREATE TEMP TABLE seed_history_contents (
                            file_id uuid, content bytea
                        ) ON COMMIT DROP
                    """)
                    with storage_cursor.copy("COPY seed_history_contents FROM STDIN") as copy:
                        for row in pending:
                            copy.write_row((row[8], row[10]))
                    storage_cursor.execute("""
                        INSERT INTO file_contents (file_id, content)
                        SELECT file_id, content FROM seed_history_contents
                        ON CONFLICT DO NOTHING
                    """)
                    summary["payloadsInserted"] = storage_cursor.rowcount
            cursor.execute("""
                INSERT INTO files (
                    id, region_id, category, original_name, media_type, size_bytes,
                    sha256, storage_backend, storage_locator, fallback_used, encrypted,
                    status, created_at, ready_at
                )
                SELECT file_id, region_id, 'METER_READING',
                       'synthetic-history-v2-' || file_id::text || '.json',
                       'application/json', octet_length(content), sha256, 'db',
                       file_id::text, false, false, 'READY', received_at, received_at
                FROM seed_history_readings ON CONFLICT DO NOTHING
            """)
            summary["filesInserted"] = cursor.rowcount
            cursor.execute("""
                INSERT INTO meter_readings (
                    id, meter_id, reading_key, seq, interval_start, interval_end,
                    energy_kwh, received_at, file_id
                )
                SELECT id, meter_id, reading_key, seq, interval_start, interval_end,
                       energy_kwh, received_at, file_id
                FROM seed_history_readings ON CONFLICT DO NOTHING
            """)
            summary["inserted"] = cursor.rowcount
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=730, help="Complete UTC days (minimum 28)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.days < 28:
        parser.error("--days must be at least 28")
    root = Path(__file__).resolve().parents[1]
    generator = root / "model-ML/filegrid-history-v2"
    payload = {
        "script": Path(__file__).read_text(),
        "generator_source": (generator / "generate.py").read_text(),
        "schema_source": (generator / "schema_sqlite.sql").read_text(),
        "days": args.days, "seed": args.seed,
    }
    worker = """
import json, sys
data = json.load(sys.stdin)
scope = {"__name__": "seed_history"}
exec(compile(data.pop("script"), "scripts/seed_history.py", "exec"), scope)
print(json.dumps(scope["seed_history"](**data), indent=2))
"""
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "api-files", "python", "-c", worker],
        cwd=root, input=json.dumps(payload), text=True, check=False,
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
