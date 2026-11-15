"""Union archived and live observations before validating complete six-hour slots."""
import logging

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_history_engine

logger = logging.getLogger(__name__)
COLUMNS = (
    "id,meter_id,reading_key,seq,interval_start,interval_end,"
    "energy_kwh,file_id,received_at"
)


def unavailable(exc):
    logger.error("Training history database unavailable: %s", type(exc).__name__)
    return HTTPException(
        503, {"code": "HISTORY_UNAVAILABLE", "message": "Forecast requires history-db; training history is unavailable"},
        headers={"Retry-After": "5"},
    )


def check_history():
    try:
        with get_history_engine().connect() as history:
            history.execute(text("SELECT 1 FROM history.meter_readings LIMIT 1"))
    except (SQLAlchemyError, OSError, ValueError) as exc:
        raise unavailable(exc) from exc


def complete_readings(db, segment, start, end, cutoff, *, subregion=False):
    from app.forecast.service import READINGS

    column = "subregion_id" if subregion else "asset_id"
    meter_ids = db.scalars(text(f"SELECT id FROM meters WHERE {column}=:segment"),
                          {"segment": segment}).all()
    cursor = db.connection().connection.driver_connection.cursor()
    cursor.execute("""
        CREATE TEMP TABLE IF NOT EXISTS forecast_history (
            id uuid, meter_id uuid, reading_key text, seq integer,
            interval_start timestamptz, interval_end timestamptz,
            energy_kwh numeric, file_id uuid, received_at timestamptz
        ) ON COMMIT DROP
    """)
    cursor.execute("TRUNCATE forecast_history")
    # Capture live rows before reading history: the splitter commits its archive
    # before deleting catalog rows, so this order cannot lose an in-flight batch.
    cursor.execute(f"""
        CREATE TEMP TABLE IF NOT EXISTS forecast_live ON COMMIT DROP
        AS SELECT {COLUMNS} FROM meter_readings WHERE false
    """)
    cursor.execute("TRUNCATE forecast_live")
    cursor.execute(f"""
        INSERT INTO forecast_live SELECT {COLUMNS} FROM meter_readings
        WHERE meter_id=ANY(%s) AND interval_start>=%s AND interval_start<%s
    """, (meter_ids, start, end))
    try:
        with get_history_engine().connect() as history:
            rows = history.execute(text(f"""
                SELECT {COLUMNS} FROM history.meter_readings
                WHERE meter_id=ANY(:meters) AND interval_start>=:start AND interval_start<:end
            """), {"meters": meter_ids, "start": start, "end": end}).yield_per(2000)
            with cursor.copy(f"COPY forecast_history ({COLUMNS}) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row(tuple(row))
    except (SQLAlchemyError, OSError, ValueError) as exc:
        raise unavailable(exc) from exc
    sql = READINGS.replace("FROM meter_readings mr", f"""FROM (
        SELECT {COLUMNS} FROM forecast_live
        UNION ALL
        SELECT {','.join('h.' + name for name in COLUMNS.split(','))}
        FROM forecast_history h WHERE NOT EXISTS (
            SELECT 1 FROM forecast_live live
            WHERE live.meter_id=h.meter_id AND live.reading_key=h.reading_key
        )
    ) mr""")
    if subregion:
        sql = sql.replace("m.asset_id = :segment", "m.subregion_id = :segment")
    return db.execute(text(sql), {
        "segment": segment, "start": start, "end": end, "cutoff": cutoff,
    }).mappings().all()
