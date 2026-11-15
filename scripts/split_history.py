#!/usr/bin/env python3
"""Back up catalog-db, verify each archived batch, then remove only verified history."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4, NAMESPACE_URL, uuid5

from history_common import ROOT, digest_rows, in_container, print_summary, verify_rows, writer_engine


def backup_catalog(directory):
    directory.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("catalog-%Y%m%dT%H%M%S") + f"-{uuid4().hex[:8]}.dump"
    partial = directory / (name + ".partial")
    with partial.open("xb") as output:
        partial.chmod(0o600)
        subprocess.run([
            "docker", "compose", "exec", "-T", "catalog-db", "sh", "-ec",
            'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc',
        ], cwd=ROOT, stdout=output, check=True)
        output.flush()
        import os
        os.fsync(output.fileno())
    with partial.open("rb") as backup:
        subprocess.run(["docker", "compose", "exec", "-T", "catalog-db", "pg_restore", "--list"],
                       cwd=ROOT, stdin=backup, stdout=subprocess.DEVNULL, check=True)
    digest = hashlib.sha256()
    with partial.open("rb") as backup:
        for block in iter(lambda: backup.read(1024 * 1024), b""):
            digest.update(block)
    destination = directory / name
    partial.rename(destination)
    print_summary({"backup": str(destination.resolve()), "bytes": destination.stat().st_size,
                   "sha256": digest.hexdigest(), "pgRestoreList": "PASS"})
    return digest.hexdigest()


def sizes(connection, schema="public"):
    from sqlalchemy import text

    return [dict(row) for row in connection.execute(text("""
        SELECT relname AS table, n_live_tup AS estimated_rows,
               pg_total_relation_size(relid) AS total_bytes,
               pg_relation_size(relid) AS heap_bytes
        FROM pg_stat_user_tables WHERE schemaname=:schema
        ORDER BY pg_total_relation_size(relid) DESC
    """), {"schema": schema}).mappings()]


def counts(connection, history=False):
    from sqlalchemy import text

    tables = ("meter_readings", "files", "historical_issues", "synthetic_cases", "synthetic_clients") if history else (
        "meter_readings", "files", "map_issues", "connection_cases", "clients",
    )
    prefix = "history." if history else ""
    return {table: connection.scalar(text(f"SELECT count(*) FROM {prefix}{table}")) for table in tables}


def archive_metadata(history, table, rows):
    from psycopg.types.json import Jsonb

    cursor = history.connection.driver_connection.cursor()
    cursor.executemany(
        f"INSERT INTO history.{table}(id,metadata) VALUES (%s,%s) ON CONFLICT DO NOTHING",
        [(identity, Jsonb(metadata)) for identity, metadata in rows],
    )
    cursor.execute(f"SELECT id,metadata FROM history.{table} WHERE id=ANY(%s)", ([row[0] for row in rows],))
    destination = cursor.fetchall()
    if table == "files":
        archived = dict(destination)
        for row in rows:
            if archived.get(row[0]) != row[1]:
                # A demo reading can already exist in training history with its
                # generator metadata. Preserve exact catalog versions separately.
                archive_domains(history, f"files_catalog:{digest_rows([row])}", [row])
        verify_rows([(r[0],) for r in rows], [(r[0],) for r in destination])
    else:
        verify_rows(rows, destination)


def journal(history, kind, ids, rows, backup_sha256):
    from sqlalchemy import text

    history.execute(text("""
        INSERT INTO history.split_batches(id,kind,source_ids,row_count,digest,backup_sha256)
        VALUES (:id,:kind,:ids,:count,:digest,:backup)
    """), {"id": uuid4(), "kind": kind, "ids": ids, "count": len(rows),
           "digest": digest_rows(rows), "backup": backup_sha256})


def archive_files(catalog, history, file_ids):
    from sqlalchemy import text
    from app.core.db import get_storage_engine

    file_ids = [UUID(str(file_id)) for file_id in file_ids]
    rows = catalog.execute(text("""
        SELECT f.id,to_jsonb(f) FROM files f WHERE id=ANY(:ids) ORDER BY id FOR UPDATE
    """), {"ids": file_ids}).all()
    archive_metadata(history, "files", rows)
    database_ids = [identity for identity, metadata in rows if metadata["storage_backend"] == "db"]
    if database_ids:
        with get_storage_engine().connect() as storage:
            payloads = storage.execute(text("""
                SELECT file_id,content FROM file_contents WHERE file_id=ANY(:ids)
            """), {"ids": database_ids}).all()
        if len(payloads) != len(database_ids):
            raise ValueError("Missing source payloads; catalog data was NOT deleted")
        metadata = dict(rows)
        cursor = history.connection.driver_connection.cursor()
        for file_id, content in payloads:
            data = bytes(content)
            if (hashlib.sha256(data).hexdigest() != metadata[file_id]["sha256"]
                    or len(data) != metadata[file_id]["size_bytes"]):
                raise ValueError(f"Source payload checksum mismatch: {file_id}; NOT deleted")
        cursor.executemany("""
            INSERT INTO history.file_contents(file_id,content) VALUES (%s,%s)
            ON CONFLICT DO NOTHING
        """, [(file_id, bytes(content)) for file_id, content in payloads])
        cursor.execute("SELECT file_id,content FROM history.file_contents WHERE file_id=ANY(%s)", (database_ids,))
        verify_rows([(i, bytes(b).hex()) for i, b in payloads],
                    [(i, bytes(b).hex()) for i, b in cursor.fetchall()])
    return rows


def remove_unreferenced_files(catalog, file_ids):
    from sqlalchemy import text

    result = catalog.execute(text("""
        DELETE FROM files f WHERE f.id=ANY(:ids)
          AND NOT EXISTS (SELECT 1 FROM meter_readings WHERE file_id=f.id)
          AND NOT EXISTS (SELECT 1 FROM map_issues WHERE file_id=f.id)
          AND NOT EXISTS (SELECT 1 FROM client_documents WHERE file_id=f.id)
          AND NOT EXISTS (SELECT 1 FROM outages WHERE file_id=f.id)
          AND NOT EXISTS (SELECT 1 FROM video_inspections WHERE file_id=f.id)
          AND NOT EXISTS (SELECT 1 FROM upload_sessions WHERE file_id=f.id)
    """), {"ids": file_ids})
    return result.rowcount


def split_history(backup_sha256, batch_size=2000, recent_days=14):
    from sqlalchemy import text
    from app.core.db import get_catalog_engine
    from app.history.readings import COLUMNS

    if len(backup_sha256) != 64 or any(c not in "0123456789abcdef" for c in backup_sha256):
        raise ValueError("A successfully validated pg_dump backup is required")
    engine = writer_engine()
    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=recent_days)
    summary = {"cutoff": cutoff, "backupSha256": backup_sha256, "moved": {}, "filesDeleted": 0}
    try:
        with get_catalog_engine().connect() as catalog:
            catalog.execute(text("SELECT pg_advisory_lock(7346021903)"))
            catalog.commit()
            try:
                with engine.connect() as history:
                    summary["before"] = {"catalog": counts(catalog), "history": counts(history, True),
                                         "catalogSizes": sizes(catalog), "historySizes": sizes(history, "history")}
                print_summary({"before": summary["before"]})
                catalog.commit()
                with catalog.begin(), engine.begin() as history:
                    meters = catalog.execute(text("""
                        SELECT m.id,m.external_code,c.client_type::text,m.subregion_id,
                               m.asset_id,a.region_id,r.code
                        FROM meters m JOIN network_assets a ON a.id=m.asset_id
                        JOIN regions r ON r.id=a.region_id LEFT JOIN clients c ON c.id=m.client_id
                    """)).all()
                    cursor = history.connection.driver_connection.cursor()
                    for row in meters:
                        cursor.execute("""
                            INSERT INTO history.meters VALUES (%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (id) DO NOTHING
                        """, tuple(row))
                    cursor.execute("SELECT * FROM history.meters WHERE id=ANY(%s)", ([r[0] for r in meters],))
                    verify_rows(meters, cursor.fetchall())
                for source, target, predicate in (
                    ("map_issues", "historical_issues", """is_historical OR (
                        type='MISSING_DOCUMENTS' AND case_id IN (
                            SELECT id FROM connection_cases WHERE id=ANY(:fixture_cases)
                            OR client_id IN (SELECT id FROM clients WHERE external_code LIKE 'SYN-%'
                                             OR external_code LIKE 'TRAIN-%')
                        ))"""),
                    ("connection_cases", "synthetic_cases", """(client_id IN (
                        SELECT id FROM clients WHERE external_code LIKE 'SYN-%' OR external_code LIKE 'TRAIN-%'
                    ) OR id=ANY(:fixture_cases)) AND NOT EXISTS (
                        SELECT 1 FROM map_issues WHERE case_id=t.id
                    )"""),
                ):
                    moved = 0
                    while True:
                        with catalog.begin():
                            rows = catalog.execute(text(f"""
                                SELECT t.id,to_jsonb(t) FROM {source} t WHERE {predicate}
                                ORDER BY t.id LIMIT :batch FOR UPDATE
                            """), {"batch": batch_size, "fixture_cases": [
                                uuid5(NAMESPACE_URL, f"filegrid:case-{i}") for i in range(1,7)
                            ]}).all()
                            if not rows:
                                break
                            ids = [r[0] for r in rows]
                            with engine.begin() as history:
                                archive_metadata(history, target, rows)
                                if source == "connection_cases":
                                    documents = catalog.execute(text(
                                        "SELECT id,to_jsonb(d) FROM client_documents d WHERE case_id=ANY(:ids)"
                                    ), {"ids": ids}).all()
                                    archive_files(catalog, history, [d[1]["file_id"] for d in documents])
                                    archive_domains(history, "client_documents", documents)
                                journal(history, source, ids, rows, backup_sha256)
                            if source == "connection_cases":
                                catalog.execute(text("DELETE FROM client_documents WHERE case_id=ANY(:ids)"), {"ids": ids})
                            deleted = catalog.execute(text(f"DELETE FROM {source} WHERE id=ANY(:ids)"), {"ids": ids}).rowcount
                            if deleted != len(rows):
                                raise ValueError("Locked source count changed; deletion rolled back")
                            if source == "connection_cases":
                                summary["filesDeleted"] += remove_unreferenced_files(
                                    catalog, [UUID(d[1]["file_id"]) for d in documents],
                                )
                            moved += deleted
                        print_summary({"batch": source, "verifiedAndDeleted": deleted})
                    summary["moved"][source] = moved
                moved = 0
                while True:
                    with catalog.begin():
                        rows = catalog.execute(text(f"""
                            SELECT {COLUMNS} FROM meter_readings
                            WHERE interval_end<=:cutoff ORDER BY id LIMIT :batch FOR UPDATE
                        """), {"cutoff": cutoff, "batch": batch_size}).all()
                        if not rows:
                            break
                        ids, file_ids = [r[0] for r in rows], [r[7] for r in rows]
                        with engine.begin() as history:
                            archive_files(catalog, history, file_ids)
                            cursor = history.connection.driver_connection.cursor()
                            cursor.executemany(f"""
                                INSERT INTO history.meter_readings({COLUMNS})
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
                            """, [tuple(row) for row in rows])
                            cursor.execute(f"SELECT {COLUMNS} FROM history.meter_readings WHERE id=ANY(%s)", (ids,))
                            verify_rows(rows, cursor.fetchall())
                            journal(history, "meter_readings", ids, rows, backup_sha256)
                        deleted = catalog.execute(text("DELETE FROM meter_readings WHERE id=ANY(:ids)"), {"ids": ids}).rowcount
                        if deleted != len(rows):
                            raise ValueError("Locked source count changed; deletion rolled back")
                        summary["filesDeleted"] += remove_unreferenced_files(catalog, file_ids)
                        moved += deleted
                    if moved % (batch_size * 25) == 0:
                        print_summary({"batch": "meter_readings", "verifiedAndDeleted": moved})
                summary["moved"]["meter_readings"] = moved
                # Archive known synthetic fixtures only; never guess from age or category.
                fixture_ids = [uuid5(NAMESPACE_URL, f"filegrid:{slug}") for slug in (
                    "file-conndoc-1", "file-outage-1", "file-video-1",
                )]
                with catalog.begin():
                    with engine.begin() as history:
                        rows = catalog.execute(text("""
                            SELECT id,to_jsonb(f) FROM files f
                            WHERE (original_name LIKE 'synthetic-training-%' AND category<>'METER_READING')
                               OR id=ANY(:fixtures)
                            FOR UPDATE
                        """), {"fixtures": fixture_ids}).all()
                        file_ids = [r[0] for r in rows]
                        archive_files(catalog, history, file_ids)
                        for table in ("client_documents", "outages", "video_inspections"):
                            domains = catalog.execute(text(
                                f"SELECT id,to_jsonb(t) FROM {table} t WHERE file_id=ANY(:ids)"
                            ), {"ids": file_ids}).all()
                            archive_domains(history, table, domains)
                        journal(history, "synthetic_files", file_ids, rows, backup_sha256)
                    for table in ("client_documents", "outages", "video_inspections"):
                        catalog.execute(text(f"""
                            DELETE FROM {table} t WHERE file_id=ANY(:ids)
                            AND NOT EXISTS (SELECT 1 FROM map_issues i WHERE i.file_id=t.file_id
                              OR i.video_inspection_id=t.id)
                        """), {"ids": file_ids})
                    summary["filesDeleted"] += remove_unreferenced_files(catalog, file_ids)
                with catalog.begin():
                    clients = catalog.execute(text("""
                        SELECT id,to_jsonb(c) FROM clients c
                        WHERE external_code LIKE 'SYN-%' OR external_code LIKE 'TRAIN-%'
                           OR id=ANY(:fixtures)
                        FOR UPDATE
                    """), {"fixtures": [uuid5(NAMESPACE_URL, f"filegrid:client-{i}") for i in range(1,7)]}).all()
                    with engine.begin() as history:
                        archive_metadata(history, "synthetic_clients", clients)
                        journal(history, "synthetic_clients", [r[0] for r in clients], clients, backup_sha256)
                    summary["moved"]["clients"] = catalog.execute(text("""
                        DELETE FROM clients c WHERE id=ANY(:ids)
                        AND NOT EXISTS (SELECT 1 FROM meters WHERE client_id=c.id)
                        AND NOT EXISTS (SELECT 1 FROM connection_cases WHERE client_id=c.id)
                        AND NOT EXISTS (SELECT 1 FROM map_issues WHERE client_id=c.id)
                    """), {"ids": [r[0] for r in clients]}).rowcount
                with engine.connect() as history:
                    summary["after"] = {"catalog": counts(catalog), "history": counts(history, True),
                                        "catalogSizes": sizes(catalog), "historySizes": sizes(history, "history")}
                catalog.commit()
                print_summary({"verifiedCopyAndDelete": summary})
                # Compact only these named demo/history tables, outside transactions.
                # FULL briefly locks them; parallel vacuum exceeds Docker's default /dev/shm.
                catalog.execution_options(isolation_level="AUTOCOMMIT")
                for table in ("meter_readings", "files", "map_issues", "connection_cases", "clients"):
                    catalog.exec_driver_sql(f"VACUUM (FULL, ANALYZE) {table}")
                catalog.commit()
                summary["after"]["catalogSizes"] = sizes(catalog)
            finally:
                if catalog.in_transaction():
                    catalog.rollback()
                catalog.execute(text("SELECT pg_advisory_unlock(7346021903)"))
                catalog.commit()
    finally:
        engine.dispose()
    return summary


def archive_domains(history, kind, rows):
    from psycopg.types.json import Jsonb

    cursor = history.connection.driver_connection.cursor()
    for identity, metadata in rows:
        cursor.execute("""
            INSERT INTO history.domain_metadata(kind,id,metadata) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING
        """, (kind, identity, Jsonb(metadata)))
    cursor.execute("SELECT id,metadata FROM history.domain_metadata WHERE kind=%s AND id=ANY(%s)",
                   (kind, [r[0] for r in rows]))
    verify_rows(rows, cursor.fetchall())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", type=Path, default=ROOT / "backups")
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--recent-days", type=int, default=14)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--backup-sha256", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 10000 or args.recent_days < 14:
        parser.error("batch size must be 1..10000 and recent days at least 14")
    if args.inside:
        print_summary(split_history(args.backup_sha256 or "", args.batch_size, args.recent_days))
    else:
        digest = backup_catalog(args.backup_dir)
        in_container("split_history.py", [
            "--backup-sha256", digest, "--batch-size", str(args.batch_size),
            "--recent-days", str(args.recent_days),
        ])


if __name__ == "__main__":
    main()
