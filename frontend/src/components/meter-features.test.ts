import { expect, it } from "vitest";
import { meterFeatures } from "./meter-features";
import type { MeterMarker } from "../data/models";

it("keeps all eight co-located meter tooltips accessible without inventing geographic locations", () => {
  const meters: MeterMarker[] = Array.from({ length: 8 }, (_, index) => ({
    id: `m-${index}`,
    assetId: "station",
    code: `M-${index}`,
    coordinates: [22.1, 44.9],
    clientType: "RESIDENTIAL",
    lastReading: { kWh: index, timestamp: "2026-11-14T20:00:00Z" },
  }));
  const features = meterFeatures(meters).features;
  expect(
    new Set(features.map((f) => JSON.stringify(f.properties?.markerOffset)))
      .size,
  ).toBe(8);
  expect(
    features.every(
      (f) =>
        f.geometry.coordinates[0] === 22.1 &&
        f.geometry.coordinates[1] === 44.9,
    ),
  ).toBe(true);
  expect(features[0].properties?.lastReading).toContain("0 kWh");
  expect(
    meterFeatures([meters[0]]).features[0].properties?.markerOffset,
  ).toEqual([0, 0]);
});
