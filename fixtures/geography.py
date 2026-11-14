"""Idempotent offline geometry seed, shared by Alembic and bootstrap."""
import json
import uuid
from pathlib import Path

from sqlalchemy import text

SQUARES = {
    "MUNTENIA": (24.5, 43.65, 27.5, 45.55),
    "BANAT": (20.25, 44.6, 22.7, 46.25),
    "DOBROGEA": (27.5, 43.7, 29.75, 45.5),
}


def seed_geography(connection):
    border = json.loads(Path(__file__).with_name("romania.geojson").read_text())
    connection.execute(text("""
        INSERT INTO national_boundaries (code, geometry)
        VALUES ('RO', ST_Multi(ST_CollectionExtract(ST_MakeValid(
            ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)), 3)))
        ON CONFLICT (code) DO UPDATE SET geometry = excluded.geometry
    """), {"geometry": json.dumps(border["geometry"])})
    for code, (west, south, east, north) in SQUARES.items():
        region_id = connection.scalar(text("""
            UPDATE regions SET geometry = ST_Multi(ST_CollectionExtract(ST_MakeValid(
                ST_Intersection(ST_MakeEnvelope(:w,:s,:e,:n,4326),
                    (SELECT geometry FROM national_boundaries WHERE code='RO'))),3))
            WHERE code=:code RETURNING id
        """), {"code": code, "w": west, "s": south, "e": east, "n": north})
        if region_id is None:
            continue
        parts = connection.scalars(text("""
            SELECT ST_AsEWKT(g) FROM (
                SELECT ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Intersection(
                    r.geometry, ST_MakeEnvelope(
                        :w + x * (:e - :w)/2, :s + y * (:n - :s)/3,
                        :w + (x+1) * (:e - :w)/2, :s + (y+1) * (:n - :s)/3,4326)
                )),3)) AS g
                FROM regions r CROSS JOIN generate_series(0,1) x
                CROSS JOIN generate_series(0,2) y WHERE r.id=:id
                ORDER BY x,y
            ) cells WHERE NOT ST_IsEmpty(g) AND ST_Area(g)>0
        """), {"id": region_id, "w": west, "s": south, "e": east, "n": north}).all()
        while len(parts) < 6:
            index = max(range(len(parts)), key=lambda i: connection.scalar(
                text("SELECT ST_Area(ST_GeomFromEWKT(:g))"), {"g": parts[i]},
            ))
            split = connection.scalars(text("""
                WITH shape AS (SELECT ST_GeomFromEWKT(:g) g),
                box AS (SELECT g, ST_XMin(g) w, ST_XMax(g) e,
                        ST_YMin(g) s, ST_YMax(g) n FROM shape)
                SELECT ST_AsEWKT(ST_Multi(ST_CollectionExtract(ST_MakeValid(
                    ST_Intersection(g, CASE WHEN e-w >= n-s THEN
                        ST_MakeEnvelope(w+i*(e-w)/2,s,w+(i+1)*(e-w)/2,n,4326)
                    ELSE ST_MakeEnvelope(w,s+i*(n-s)/2,e,s+(i+1)*(n-s)/2,4326)
                    END)),3)))
                FROM box CROSS JOIN generate_series(0,1) i ORDER BY i
            """), {"g": parts[index]}).all()
            parts[index:index + 1] = split
        for number, geometry in enumerate(parts, 1):
            subcode = f"{code}-{number}"
            connection.execute(text("""
                INSERT INTO subregions(id,region_id,code,name,geometry)
                VALUES (:id,:parent,:code,:name,ST_GeomFromEWKT(:g))
                ON CONFLICT (code) DO UPDATE SET
                    region_id=excluded.region_id, name=excluded.name, geometry=excluded.geometry
            """), {
                "id": uuid.uuid5(uuid.NAMESPACE_URL, f"filegrid:subregion:{subcode}"),
                "parent": region_id, "code": subcode, "name": f"{code.title()} {number}",
                "g": geometry,
            })
    connection.execute(text("""
        UPDATE regions SET bounds=jsonb_build_object(
            'minLon',ST_XMin(geometry),'minLat',ST_YMin(geometry),
            'maxLon',ST_XMax(geometry),'maxLat',ST_YMax(geometry))
        WHERE geometry IS NOT NULL
    """))
    # The original synthetic Dobrogea offsets put four fixture assets in the sea.
    for number in range(1, 6):
        connection.execute(text("""
            UPDATE network_assets a SET geometry=ST_PointOnSurface(ST_Intersection(
                r.geometry, ST_Buffer(ST_ClosestPoint(r.geometry,a.geometry),0.01)))
            FROM regions r WHERE r.id=a.region_id AND a.id=:id
                AND NOT ST_Covers(r.geometry,a.geometry)
        """), {"id": uuid.uuid5(uuid.NAMESPACE_URL, f"filegrid:asset-dobrogea-{number}")})
    connection.execute(text("UPDATE network_assets SET geometry=geometry"))
    connection.execute(text("UPDATE meters SET asset_id=asset_id"))
    connection.execute(text("UPDATE map_issues SET location=location"))
    connection.execute(text("UPDATE files SET region_id=region_id"))
    for table in ("meter_readings", "outages", "video_inspections", "client_documents"):
        connection.execute(text(f"SELECT assign_linked_file('{table}', NULL)"))


if __name__ == "__main__":
    from app.core.db import get_catalog_engine

    with get_catalog_engine().begin() as connection:
        seed_geography(connection)
    print("Geography seed complete.")
