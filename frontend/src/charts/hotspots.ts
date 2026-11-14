import type { FeatureCollection, Point } from "geojson";
import type { LayerSpecification } from "maplibre-gl";
import type { OutageHotspot } from "../data/models";

export type HotspotMode = "heat" | "clusters";
export function hotspotCollection(
  rows: OutageHotspot[],
): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: rows.map((row) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: row.coordinates },
      properties: {
        id: row.id,
        assetName: row.assetName,
        outageCount: row.outageCount,
        durationMinutes: row.durationMinutes,
      },
    })),
  };
}
export const hotspotLayers: LayerSpecification[] = [
  {
    id: "hotspot-heat",
    source: "hotspots",
    type: "heatmap",
    paint: {
      "heatmap-weight": ["get", "outageCount"],
      "heatmap-intensity": 0.08,
      "heatmap-opacity": 0.8,
      "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 5, 20, 12, 55],
      "heatmap-color": [
        "interpolate",
        ["linear"],
        ["heatmap-density"],
        0,
        "rgba(23,103,71,0)",
        0.2,
        "#70ad81",
        0.45,
        "#e9d17c",
        0.7,
        "#e59654",
        1,
        "#c64046",
      ],
    },
  },
  {
    id: "hotspot-heat-points",
    source: "hotspots",
    type: "circle",
    minzoom: 10,
    paint: {
      "circle-radius": 5,
      "circle-color": "#c64046",
      "circle-stroke-color": "white",
      "circle-stroke-width": 1.5,
    },
  },
  {
    id: "hotspot-clusters",
    source: "hotspots-clustered",
    type: "circle",
    filter: ["has", "point_count"],
    paint: {
      "circle-radius": ["step", ["get", "outageCount"], 20, 100, 28, 250, 36],
      "circle-color": [
        "step",
        ["get", "outageCount"],
        "#e9d17c",
        100,
        "#e59654",
        250,
        "#c64046",
      ],
      "circle-opacity": 0.9,
      "circle-stroke-color": "white",
      "circle-stroke-width": 2,
    },
  },
  {
    id: "hotspot-cluster-labels",
    source: "hotspots-clustered",
    type: "symbol",
    filter: ["has", "point_count"],
    layout: {
      "text-field": ["to-string", ["get", "outageCount"]],
      "text-size": 12,
    },
    paint: { "text-color": "#102d24" },
  },
  {
    id: "hotspot-points",
    source: "hotspots-clustered",
    type: "circle",
    filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-radius": 7,
      "circle-color": "#c64046",
      "circle-stroke-width": 2,
      "circle-stroke-color": "white",
    },
  },
];
export function visibleHotspotLayers(mode: HotspotMode) {
  return mode === "heat"
    ? ["hotspot-heat", "hotspot-heat-points"]
    : ["hotspot-clusters", "hotspot-cluster-labels", "hotspot-points"];
}
