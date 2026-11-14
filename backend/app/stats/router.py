from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.api import Pagination
from app.core.db import get_catalog_db

router = APIRouter(
    prefix="/api/v1/stats", tags=["stats"], dependencies=[Depends(get_current_user)],
)


class Window:
    def __init__(
        self,
        from_time: Annotated[AwareDatetime | None, Query(alias="from")] = None,
        to_time: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    ):
        self.end = to_time or datetime.now(timezone.utc)
        self.start = from_time or self.end - timedelta(days=7)
        if not timedelta(0) < self.end - self.start <= timedelta(days=366):
            raise HTTPException(422, "Require from < to and a window of at most 366 days")

    def params(self):
        return {"start": self.start, "end": self.end}


BENCHMARK = """
SELECT o.category, o.storage, coalesce(s.profile, 'normal') AS profile,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY o.duration_ms) AS "p50Ms",
       percentile_cont(0.95) WITHIN GROUP (ORDER BY o.duration_ms) AS "p95Ms",
       percentile_cont(0.99) WITHIN GROUP (ORDER BY o.duration_ms) AS "p99Ms",
       coalesce(sum(o.bytes) FILTER (WHERE o.outcome = 'success'), 0)::float8
           / 1048576 / (sum(o.duration_ms)::float8 / 1000) AS "throughputMiBps",
       count(*) FILTER (WHERE o.outcome <> 'success')::float8 / count(*) AS "errorRate"
FROM storage_operations o LEFT JOIN scenario_runs s ON s.id = o.scenario_run_id
WHERE o.occurred_at >= :start AND o.occurred_at < :end
  AND o.operation IN ('put', 'get', 'upload_part') AND o.duration_ms > 0 AND o.bytes >= 0
  AND (s.id IS NULL OR s.profile IN ('normal', 'peak'))
GROUP BY o.category, o.storage, coalesce(s.profile, 'normal')
"""


def page_query(db, sql, params, pagination, key):
    # Count before LIMIT so empty/out-of-range pages retain correct totals.
    total = db.scalar(text(f"SELECT count(*) FROM ({sql}) AS stats_count"), params)
    rows = db.execute(
        text(sql + " LIMIT :limit OFFSET :offset"),
        {**params, "limit": pagination.size, "offset": pagination.page * pagination.size},
    ).mappings()
    return {
        key: [dict(row) for row in rows], "page": pagination.page, "size": pagination.size,
        "totalElements": total, "totalPages": (total + pagination.size - 1) // pagination.size,
    }


@router.get("/storage-benchmark")
def storage_benchmark(
    window: Window = Depends(), pagination: Pagination = Depends(),
    db: Session = Depends(get_catalog_db),
):
    return page_query(
        db, BENCHMARK + " ORDER BY category, storage, profile",
        window.params(), pagination, "rows",
    )


@router.get("/recommendations")
def recommendations(
    window: Window = Depends(), pagination: Pagination = Depends(),
    db: Session = Depends(get_catalog_db),
):
    return page_query(db, """
        WITH measured AS (""" + BENCHMARK + """),
        ranked AS (
            SELECT *, row_number() OVER (
                PARTITION BY category ORDER BY "errorRate", "p95Ms", "throughputMiBps" DESC,
                storage, profile
            ) AS rank FROM measured
        )
        SELECT category, storage,
               'Observed ' || profile || ' transfers: error rate ' ||
               round(("errorRate" * 100)::numeric, 2) ||
               '%, p95 ' || round("p95Ms"::numeric, 2) ||
               ' ms; ranked by lowest error rate, then p95 latency and throughput.' AS reason
        FROM ranked WHERE rank = 1 ORDER BY category
    """, window.params(), pagination, "items")


@router.get("/meters")
def meters(
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    subregion_id: Annotated[UUID | None, Query(alias="subregionId")] = None,
    window: Window = Depends(), pagination: Pagination = Depends(),
    db: Session = Depends(get_catalog_db),
):
    return page_query(db, """
        WITH daily AS (
            SELECT m.id, m.external_code AS label, r.code AS region,
                   date_trunc('day', mr.interval_start AT TIME ZONE 'UTC')
                       AT TIME ZONE 'UTC' AS day,
                   sum(mr.energy_kwh)::float8 AS energy
            FROM meter_readings mr
            JOIN meters m ON m.id = mr.meter_id
            JOIN network_assets a ON a.id = m.asset_id
            JOIN regions r ON r.id = a.region_id
            WHERE mr.interval_start >= :start AND mr.interval_start < :end
              AND (CAST(:region AS uuid) IS NULL OR r.id = CAST(:region AS uuid)
                   OR m.subregion_id = CAST(:region AS uuid))
              AND (CAST(:subregion AS uuid) IS NULL OR m.subregion_id = CAST(:subregion AS uuid))
            GROUP BY m.id, m.external_code, r.code, day
        )
        SELECT id, label, region AS "regionCode", 1440 AS "intervalMinutes",
               min(day) AS "from", max(day) AS "to",
               jsonb_agg(jsonb_build_object(
                   'timestamp', to_char(day AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
                   'kWh', energy, 'anomaly', CASE WHEN energy = 0 THEN 'zero' ELSE NULL END
               ) ORDER BY day) AS readings
        FROM daily GROUP BY id, label, region ORDER BY region, label, id
    """, {**window.params(), "region": region_id, "subregion": subregion_id}, pagination, "meters")


@router.get("/outages/hotspots")
def hotspots(
    region_id: Annotated[UUID | None, Query(alias="regionId")] = None,
    subregion_id: Annotated[UUID | None, Query(alias="subregionId")] = None,
    window: Window = Depends(), pagination: Pagination = Depends(),
    db: Session = Depends(get_catalog_db),
):
    result = page_query(db, """
        WITH counts AS (
            SELECT o.asset_id, count(*) AS count,
                   sum(greatest(0, extract(epoch FROM (
                       least(coalesce(o.ended_at, :end), :end) -
                       greatest(o.started_at, :start)
                   ))) / 60)::float8 AS minutes
            FROM outages o
            JOIN network_assets a ON a.id = o.asset_id
            WHERE o.started_at < :end AND (o.ended_at IS NULL OR o.ended_at > :start)
              AND (CAST(:region AS uuid) IS NULL OR a.region_id = CAST(:region AS uuid)
                   OR a.subregion_id = CAST(:region AS uuid))
              AND (CAST(:subregion AS uuid) IS NULL OR a.subregion_id = CAST(:subregion AS uuid))
            GROUP BY o.asset_id
        )
        SELECT 'Feature' AS type,
               ST_AsGeoJSON(ST_PointOnSurface(a.geometry))::jsonb AS geometry,
               jsonb_build_object(
                   'id', a.id, 'assetName', a.name, 'regionCode', r.code,
                   'outageCount', c.count, 'durationMinutes', c.minutes
               ) AS properties
        FROM counts c JOIN network_assets a ON a.id = c.asset_id
        JOIN regions r ON r.id = a.region_id
        ORDER BY c.count DESC, a.id
    """, {**window.params(), "region": region_id, "subregion": subregion_id}, pagination, "features")
    return {"type": "FeatureCollection", **result}
