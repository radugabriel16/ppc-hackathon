import type { FeatureCollection, Point } from "geojson";
import type { MeterMarker } from "../data/models";

export function meterFeatures(meters: MeterMarker[]): FeatureCollection<Point> {
  const groups = new Map<string, MeterMarker[]>();
  for (const meter of meters) {
    const key = meter.coordinates.join(",");
    groups.set(key, [...(groups.get(key) ?? []), meter]);
  }
  return {
    type: "FeatureCollection",
    features: [...groups.values()].flatMap((group) =>
      group.map((meter, index) => {
        const angle = (2 * Math.PI * index) / group.length;
        return {
          type: "Feature",
          id: meter.id,
          geometry: { type: "Point", coordinates: meter.coordinates },
          properties: {
            id: meter.id,
            code: meter.code,
            markerOffset:
              group.length === 1
                ? [0, 0]
                : [Math.cos(angle) * 26, Math.sin(angle) * 26],
            clientType: meter.clientType ?? "Unknown client type",
            lastReading: meter.lastReading
              ? `${meter.lastReading.kWh} kWh · ${new Date(meter.lastReading.timestamp).toLocaleString()}`
              : "No readings",
          },
        };
      }),
    ),
  };
}
