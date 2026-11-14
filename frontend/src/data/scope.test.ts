import { describe, expect, it } from "vitest";
import { forecastRunInput, readScope, selectScope } from "./scope";
import {
  areaContains,
  areaFeatures,
  reportArea,
} from "../components/map-geography";
import type { GeographicArea } from "./models";

const region: GeographicArea = {
  id: "region",
  code: "BANAT",
  name: "Banat",
  region: "BANAT",
  parentId: null,
  meterCount: 16,
  geometry: {
    type: "MultiPolygon",
    coordinates: [
      [
        [
          [20, 44],
          [22, 44],
          [22, 46],
          [20, 46],
          [20, 44],
        ],
      ],
    ],
  },
};
const west: GeographicArea = {
  ...region,
  id: "west",
  parentId: region.id,
  meterCount: 8,
  geometry: {
    type: "MultiPolygon",
    coordinates: [
      [
        [
          [20, 44],
          [21, 44],
          [21, 46],
          [20, 46],
          [20, 44],
        ],
      ],
    ],
  },
};
const east: GeographicArea = {
  ...region,
  id: "east",
  parentId: region.id,
  meterCount: 8,
  geometry: {
    type: "MultiPolygon",
    coordinates: [
      [
        [
          [21, 44],
          [22, 44],
          [22, 46],
          [21, 46],
          [21, 44],
        ],
      ],
    ],
  },
};
const other: GeographicArea = {
  ...region,
  id: "other",
  code: "MUNTENIA",
  region: "MUNTENIA",
  geometry: {
    type: "MultiPolygon",
    coordinates: [
      [
        [
          [24, 44],
          [26, 44],
          [26, 46],
          [24, 46],
          [24, 44],
        ],
      ],
    ],
  },
};
const areas = [region, west, east, other];

describe("shared Romania > region > segment selection", () => {
  it("roundtrips URL scope and preserves unrelated filters while clearing dependent selections", () => {
    const start = new URLSearchParams(
      "region=BANAT&segment=west&issue=old&run=previous&filter=OPEN",
    );
    expect(readScope(start)).toMatchObject({
      selectedRegion: "BANAT",
      subregionId: "west",
    });
    const next = selectScope(start, "MUNTENIA");
    expect(next.toString()).toBe("region=MUNTENIA&filter=OPEN");
    expect(readScope(selectScope(next, null))).toMatchObject({
      selectedRegion: null,
      subregionId: undefined,
    });
    expect(
      readScope(new URLSearchParams("region=invalid&segment=west"))
        .selectedRegion,
    ).toBeNull();
    expect(start.get("segment")).toBe("west");
  });
  it("highlights all regions for Romania, then only the selected region or segment", () => {
    const highlighted = (id?: string) =>
      areaFeatures(areas, id)
        .features.filter((f) => f.properties?.highlighted)
        .map((f) => f.id);
    expect(highlighted()).toEqual(["region", "other"]);
    expect(highlighted("region")).toEqual(["region"]);
    expect(highlighted("west")).toEqual(["west"]);
  });
  it("accepts right-click points only in the selected scope, not a neighbour or outside Romania", () => {
    expect(reportArea(areas, undefined, [20.4, 45])?.id).toBe("west");
    expect(reportArea(areas, region.id, [21.5, 45])?.id).toBe("east");
    expect(reportArea(areas, west.id, [20.4, 45])?.id).toBe("west");
    expect(reportArea(areas, west.id, [21.5, 45])).toBeUndefined();
    expect(reportArea(areas, region.id, [25, 45])).toBeUndefined();
    expect(reportArea(areas, undefined, [19, 43])).toBeUndefined();
    expect(reportArea(areas, "invalid", [20.4, 45])).toBeUndefined();
    expect(reportArea(areas, west.id, [21, 45])?.id).toBe("west");
  });
  it("handles holes and disjoint polygon islands without accepting a bounding box", () => {
    const area: GeographicArea = {
      ...region,
      geometry: {
        type: "MultiPolygon",
        coordinates: [
          [
            region.geometry.coordinates[0][0],
            [
              [20.2, 44.2],
              [20.8, 44.2],
              [20.8, 44.8],
              [20.2, 44.8],
              [20.2, 44.2],
            ],
          ],
          [
            [
              [23, 45],
              [23.5, 45],
              [23.5, 45.5],
              [23, 45.5],
              [23, 45],
            ],
          ],
        ],
      },
    };
    expect(areaContains(area, [20.5, 44.5])).toBe(false);
    expect(areaContains(area, [20.2, 44.5])).toBe(true);
    expect(areaContains(area, [23.2, 45.2])).toBe(true);
    expect(areaContains(area, [22.5, 45.2])).toBe(false);
  });
  it("builds forecast scopes with geographic segment IDs and no country IDs", () => {
    expect(forecastRunInput()).toEqual({ scope: "country" });
    expect(forecastRunInput("region")).toEqual({
      scope: "region",
      regionId: "region",
    });
    expect(forecastRunInput("region", "west")).toEqual({
      scope: "segment",
      regionId: "region",
      segmentId: "west",
    });
  });
});
