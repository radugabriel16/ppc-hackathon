"""Versioned history schema and least-privilege roles; invoked only by migrate."""
from pathlib import Path

from psycopg import sql
from sqlalchemy import create_engine

from app.core.settings import get_settings


def migrate_history():
    settings = get_settings()
    engine = create_engine(settings.history_db_url("admin"))
    try:
        with engine.begin() as connection:
            cursor = connection.connection.driver_connection.cursor()
            cursor.execute("SELECT pg_advisory_xact_lock(7346021902)")
            for role in ("reader", "writer"):
                name = f"filegrid_history_{role}"
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (name,))
                if not cursor.fetchone():
                    cursor.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(name),
                        sql.Literal(settings.storage_secret(f"history_db_{role}_password")),
                    ))
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS public.history_migrations (
                    version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now()
                )
            """)
            for migration in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
                cursor.execute("SELECT 1 FROM public.history_migrations WHERE version=%s", (migration.stem,))
                if not cursor.fetchone():
                    cursor.execute(migration.read_text())
                    cursor.execute("INSERT INTO public.history_migrations(version) VALUES (%s)", (migration.stem,))
            cursor.execute("""
                REVOKE CREATE ON SCHEMA public FROM PUBLIC;
                REVOKE ALL ON SCHEMA history FROM PUBLIC;
                GRANT USAGE ON SCHEMA history TO filegrid_history_reader, filegrid_history_writer;
                GRANT SELECT ON ALL TABLES IN SCHEMA history TO filegrid_history_reader;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA history
                    TO filegrid_history_writer;
                ALTER DEFAULT PRIVILEGES IN SCHEMA history GRANT SELECT ON TABLES
                    TO filegrid_history_reader;
                ALTER DEFAULT PRIVILEGES IN SCHEMA history GRANT SELECT, INSERT, UPDATE, DELETE
                    ON TABLES TO filegrid_history_writer;
                ALTER ROLE filegrid_history_reader SET default_transaction_read_only=on;
            """)
    finally:
        engine.dispose()
