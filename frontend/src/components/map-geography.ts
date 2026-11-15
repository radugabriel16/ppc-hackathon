import type { FeatureCollection, MultiPolygon } from "geojson";
import type { GeographicArea } from "../data/models";

export function areaFeatures(
  areas: GeographicArea[],
  selectedId?: string,
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
        highlighted: isAreaHighlighted(area, selectedId),
      },
    })),
  };
}

export function isAreaHighlighted(area: GeographicArea, selectedId?: string) {
  return selectedId ? area.id === selectedId : !area.parentId;
}

function ringContains(ring: number[][], [x, y]: [number, number]) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const cross = (x - xi) * (yj - yi) - (y - yi) * (xj - xi);
    if (
      Math.abs(cross) < 1e-10 &&
      x >= Math.min(xi, xj) &&
      x <= Math.max(xi, xj) &&
      y >= Math.min(yi, yj) &&
      y <= Math.max(yi, yj)
    )
      return "boundary";
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi)
      inside = !inside;
  }
  return inside ? "inside" : "outside";
}

export function areaContains(area: GeographicArea, point: [number, number]) {
  return geometryContains(area.geometry, point);
}

export function geometryContains(geometry: MultiPolygon, point: [number, number]) {
  return geometry.coordinates.some(([outer, ...holes]) => {
    const boundary = ringContains(outer, point);
    if (boundary === "boundary") return true;
    return (
      boundary === "inside" &&
      !holes.some((hole) => ringContains(hole, point) === "inside")
    );
  });
}

export function reportArea(
  areas: GeographicArea[],
  selectedId: string | undefined,
  point: [number, number],
) {
  const selected = areas.find((area) => area.id === selectedId);
  if (selectedId && !selected) return undefined;
  if (selected && !areaContains(selected, point)) return undefined;
  if (selected?.parentId) return selected;
  const region =
    selected ??
    areas.find((area) => !area.parentId && areaContains(area, point));
  if (!region) return undefined;
  return areas.find(
    (area) => area.parentId === region.id && areaContains(area, point),
  );
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
