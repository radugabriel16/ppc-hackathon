from sqlalchemy import func, select

from app.models.geography import NetworkAsset, Subregion
from app.models.issues import MapIssue


def point_geojson(column):
    return func.json_build_object(
        "type", "Point", "coordinates", func.json_build_array(func.ST_X(column), func.ST_Y(column)),
    )


def region_filter(model, region_id):
    return (model.region_id == region_id) | (model.subregion_id == region_id)


def issue_region_filter(region_id):
    return (
        MapIssue.subregion_id.in_(select(Subregion.id).where(Subregion.region_id == region_id))
        | (MapIssue.subregion_id == region_id)
        | (MapIssue.subregion_id.is_(None) & (NetworkAsset.region_id == region_id))
    )
