import type { Map as LibreMap } from "maplibre-gl";
import type { Asset } from "../data/models";

export const ASSET_MARKERS: Record<
  Asset["type"],
  { label: string; color: string; points: [number, number][] }
> = {
  SUBSTATION: {
    label: "Substation",
    color: "#176747",
    points: [
      [6, 6],
      [42, 6],
      [42, 42],
      [6, 42],
    ],
  },
  TRANSFORMER: {
    label: "Transformer",
    color: "#457b9d",
    points: [
      [24, 3],
      [45, 43],
      [3, 43],
    ],
  },
  LINE_SEGMENT: {
    label: "Line segment (point asset)",
    color: "#457b9d",
    points: [
      [24, 3],
      [45, 24],
      [24, 45],
      [3, 24],
    ],
  },
};

export function addStationImages(map: Pick<LibreMap, "addImage">) {
  for (const [type, marker] of Object.entries(ASSET_MARKERS)) {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 48;
    const context = canvas.getContext("2d");
    if (!context) continue;
    context.beginPath();
    marker.points.forEach(([x, y], index) =>
      index === 0 ? context.moveTo(x, y) : context.lineTo(x, y),
    );
    context.closePath();
    context.fillStyle = marker.color;
    context.fill();
    context.lineWidth = 3;
    context.strokeStyle = "#fff";
    context.stroke();
    map.addImage(`station-${type}`, context.getImageData(0, 0, 48, 48), {
      pixelRatio: 2,
    });
  }
}
