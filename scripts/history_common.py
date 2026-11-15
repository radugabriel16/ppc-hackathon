"""Shared host/container entry point and strict archive verification."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def in_container(script, arguments):
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "api-files", "python",
         f"/app/scripts/{script}", "--inside", *arguments],
        cwd=ROOT, check=False,
    )
    if result.returncode:
        raise SystemExit(result.returncode)


def writer_engine():
    from sqlalchemy import create_engine
    from app.core.settings import get_settings

    return create_engine(get_settings().history_db_url("writer"), pool_pre_ping=True,
                         connect_args={"connect_timeout": 5})


def digest_rows(rows):
    serialized = [json.dumps(list(row), sort_keys=True, default=str, separators=(",", ":"))
                  for row in rows]
    return hashlib.sha256("\n".join(sorted(serialized)).encode()).hexdigest()


def verify_rows(source, destination):
    if len(source) != len(destination) or digest_rows(source) != digest_rows(destination):
        raise ValueError(
            f"Archive verification failed: source={len(source)}, destination={len(destination)}; "
            "catalog data was NOT deleted"
        )


def print_summary(summary):
    print(json.dumps(summary, indent=2, default=str))
