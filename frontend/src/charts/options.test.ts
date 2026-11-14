import { describe, expect, it } from "vitest";
import type { LineSeriesOption } from "echarts";
import { init } from "./runtime";
import { benchmarkOption, forecastOption, meterOption } from "./options";
import {
  hotspotCollection,
  hotspotLayers,
  visibleHotspotLayers,
} from "./hotspots";
import { createStatsFixtures } from "../mocks/stats";
import {
  forecast,
  meterConsumption,
  outageHotspots,
} from "../data/stats-mapping";

const fixtures = createStatsFixtures(Date.parse("2026-11-14T12:00:00Z"));
describe("statistics visualization semantics", () => {
  it("renders heatmap, consumption and forecast as real ECharts SVG artifacts", () => {
    const options = [
      benchmarkOption(
        fixtures.benchmark.rows.filter((row) => row.profile === "normal"),
        "p95Ms",
      ),
      meterOption(meterConsumption(fixtures.meters, "MUNTENIA")[0]),
      forecastOption(forecast(fixtures.forecast, "MUNTENIA")),
    ];
    for (const option of options) {
      const chart = init(null, undefined, {
        renderer: "svg",
        ssr: true,
        width: 1000,
        height: 360,
      });
      try {
        chart.setOption(option);
        const svg = chart.renderToSVGString();
        expect(svg).toContain("<svg");
        expect(svg).toContain("<path");
        expect(svg).not.toMatch(/NaN|undefined|Infinity/);
      } finally {
        chart.dispose();
      }
    }
  });
  it("leaves consumption gaps disconnected, highlights missing intervals and marks measured zero anomalies", () => {
    const option = meterOption(
      meterConsumption(fixtures.meters, "MUNTENIA")[0],
    );
    const series = option.series as LineSeriesOption[];
    expect(series[0].connectNulls).toBe(false);
    expect(
      (series[0].data as unknown[][]).filter((row) => row[1] === null),
    ).toHaveLength(3);
    expect(series[0].markArea?.data).toHaveLength(3);
    const anomalies = series[1].data as { name: string; value: unknown[] }[];
    expect(anomalies.find((point) => point.name === "zero")?.value[1]).toBe(0);
    expect(anomalies.find((point) => point.name === "spike")).toBeTruthy();
  });
  it("draws both forecast bands at their returned lower/upper bounds, not from zero", () => {
    const points = forecast(fixtures.forecast, "MUNTENIA");
    const series = forecastOption(points).series as LineSeriesOption[];
    for (const level of ["80", "95"] as const) {
      const base = series.find((row) => row.name === `${level}% lower offset`)!;
      const band = series.find((row) => row.name === `${level}% interval`)!;
      const baseData = base.data as [string, number][];
      const bandData = band.data as [string, number][];
      expect(base.stack).toBe(level);
      expect(band.stack).toBe(level);
      for (const [i, point] of points.entries()) {
        expect(baseData[i][1]).toBe(
          level === "80" ? point.lower80 : point.lower95,
        );
        expect(baseData[i][1] + bandData[i][1]).toBe(
          level === "80" ? point.upper80 : point.upper95,
        );
      }
    }
    expect(
      (
        series.find((row) => row.name === "Estimate")!.data as unknown[][]
      )[0].slice(1),
    ).toEqual([
      points[0].estimate,
      points[0].lower80,
      points[0].upper80,
      points[0].lower95,
      points[0].upper95,
    ]);
  });
  it("creates only operational hotspot properties and enables distinct weighted heat and cluster layers", () => {
    const rows = outageHotspots(fixtures.hotspots, "MUNTENIA");
    const collection = hotspotCollection(rows);
    expect(collection.features[0].geometry.coordinates).toEqual(
      rows[0].coordinates,
    );
    expect(Object.keys(collection.features[0].properties!)).toEqual([
      "id",
      "assetName",
      "outageCount",
      "durationMinutes",
    ]);
    const heat = hotspotLayers.find((layer) => layer.type === "heatmap")!;
    expect(heat.paint?.["heatmap-weight"]).toEqual(["get", "outageCount"]);
    expect(visibleHotspotLayers("heat")).toContain("hotspot-heat");
    expect(visibleHotspotLayers("clusters")).toContain(
      "hotspot-cluster-labels",
    );
    expect(visibleHotspotLayers("clusters")).not.toContain("hotspot-heat");
  });
});
