import type { FeatureCollection, MultiPolygon } from "geojson";
import type { GeographicArea } from "../data/models";

export function areaFeatures(
  areas: GeographicArea[],
): FeatureCollection<MultiPolygon> {
  return {
    type: "FeatureCollection",
    features: areas.map((area) => ({
      type: "Feature",
      id: area.id,
      geometry: area.geometry,
      properties: {
        id: area.id,
        name: area.name,
        parentId: area.parentId ?? "",
        meterCount: area.meterCount,
      },
    })),
  };
}

export function areaBounds(
  areas: GeographicArea[],
): [[number, number], [number, number]] {
  const positions = areas.flatMap((area) => area.geometry.coordinates.flat(2));
  return positions.reduce<[[number, number], [number, number]]>(
    (bounds, [lon, lat]) => [
      [Math.min(bounds[0][0], lon), Math.min(bounds[0][1], lat)],
      [Math.max(bounds[1][0], lon), Math.max(bounds[1][1], lat)],
    ],
    [
      [Infinity, Infinity],
      [-Infinity, -Infinity],
    ],
  );
}
