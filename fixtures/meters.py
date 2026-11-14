"""Preserve registered meters and fill each geographical segment to eight."""
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text


def identity(value):
    return uuid5(NAMESPACE_URL, f"filegrid:topology:{value}")


def seed_meters(connection):
    connection.execute(text("LOCK TABLE meters IN SHARE ROW EXCLUSIVE MODE"))
    segments = connection.execute(text("""
        SELECT s.id, s.region_id, s.code, ST_AsEWKT(ST_PointOnSurface(s.geometry)) AS point
        FROM subregions s ORDER BY s.code
    """)).mappings().all()
    for segment in segments:
        params = dict(segment)
        count = connection.scalar(text(
            "SELECT count(*) FROM meters WHERE subregion_id=:id"
        ), params)
        if count > 8:
            raise ValueError(f"{segment['code']} has {count} meters; refusing to remove registered meters")
        asset = connection.scalar(text("""
            SELECT id FROM network_assets WHERE subregion_id=:id ORDER BY code LIMIT 1
        """), params)
        if asset is None:
            asset = identity(f"asset:{segment['code']}")
            connection.execute(text("""
                INSERT INTO network_assets(id,region_id,code,name,type,geometry)
                VALUES (:asset,:region_id,:code || '-GRID',:code || ' distribution segment',
                        'LINE_SEGMENT',ST_GeomFromEWKT(:point)) ON CONFLICT DO NOTHING
            """), {**params, "asset": asset})
        for index in range(8):
            if count == 8:
                break
            code = f"RO-{segment['code']}-{index + 1:03d}"
            if connection.scalar(text("SELECT 1 FROM meters WHERE external_code=:code"), {"code": code}):
                continue
            client = identity(f"client:{code}")
            kind = ("RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL")[index % 3]
            connection.execute(text("""
                INSERT INTO clients(id,region_id,external_code,name_enc,email_enc,location,client_type)
                VALUES (:client,:region_id,:code,:name,:email,ST_GeomFromEWKT(:point),
                        CAST(:kind AS client_type)) ON CONFLICT DO NOTHING
            """), {
                **params, "client": client, "code": f"SYN-{code}",
                "name": b"synthetic-client", "email": b"synthetic@example.invalid", "kind": kind,
            })
            connection.execute(text("""
                INSERT INTO meters(id,external_code,asset_id,client_id,location)
                VALUES (:meter,:code,:asset,:client,ST_GeomFromEWKT(:point))
                ON CONFLICT DO NOTHING
            """), {
                **params, "meter": identity(f"meter:{code}"), "code": code,
                "asset": asset, "client": client,
            })
            count += 1


if __name__ == "__main__":
    from app.core.db import get_catalog_engine

    with get_catalog_engine().begin() as connection:
        seed_meters(connection)
    print("Meter topology seed complete.")
