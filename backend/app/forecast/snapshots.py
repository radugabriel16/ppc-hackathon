"""Daily observed-only model snapshots shared by the worker and seed scripts."""
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb
from sqlalchemy import text


def refresh_snapshots(db, runtime):
    origin = (datetime.now(timezone.utc)-timedelta(minutes=10)).date()
    assets = db.scalars(text("""
        SELECT a.id FROM network_assets a
        WHERE EXISTS (SELECT 1 FROM meters WHERE asset_id=a.id)
          AND NOT EXISTS (
              SELECT 1 FROM forecast_snapshots WHERE asset_id=a.id AND origin=:origin
          ) ORDER BY a.id
    """), {"origin": origin}).all()
    for asset in assets:
        result = runtime.get(db, str(asset), origin)
        db.connection().connection.driver_connection.execute("""
            INSERT INTO forecast_snapshots(asset_id,origin,result) VALUES (%s,%s,%s)
            ON CONFLICT DO NOTHING
        """, (asset, origin, Jsonb(result)))
        db.commit()
    db.execute(text("DELETE FROM forecast_snapshots WHERE origin<:old"),
               {"old": origin-timedelta(days=7)})
    db.commit()
    return len(assets)
