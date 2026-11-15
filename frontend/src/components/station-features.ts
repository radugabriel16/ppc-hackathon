import type { FeatureCollection, LineString, Point } from "geojson";

export function stationFeatures(
  assets: FeatureCollection<Point | LineString>,
): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: assets.features.flatMap((feature) =>
      feature.geometry.type === "Point"
        ? [
            {
              ...feature,
              geometry: feature.geometry,
              properties: { ...feature.properties, kind: "STATION" },
            },
          ]
        : [],
    ),
  };
}
