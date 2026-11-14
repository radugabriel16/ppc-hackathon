import { describe, expect, it } from "vitest";
import type { LineSeriesOption } from "echarts";
import type { SegmentForecastDay } from "../api/gen/types.gen";
import { init } from "./runtime";
import {
  benchmarkOption,
  forecastOption,
  meterOption,
  scopedForecastOption,
} from "./options";
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
    const day = (horizon: number): SegmentForecastDay => ({
      horizon,
      date: `2026-11-${14 + horizon}`,
      predictedEnergyKwh: horizon === 3 ? null : 120,
      referenceEnergyKwh: 100,
      changeVsReferencePct: horizon === 3 ? null : 20,
      status: horizon === 3 ? "INSUFFICIENT_DATA" : "READY",
      fallbackUsed: false,
      expectedMeters: 8,
      eligibleMeters: horizon === 3 ? 7 : 8,
    });
    const options = [
      benchmarkOption(
        fixtures.benchmark.rows.filter((row) => row.profile === "normal"),
        "p95Ms",
      ),
      meterOption(meterConsumption(fixtures.meters, "MUNTENIA")[0]),
      forecastOption(forecast(fixtures.forecast, "MUNTENIA")),
      scopedForecastOption({
        thresholdKwh: 100,
        forecasts: [day(1), day(2), day(3)],
      }),
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
  it("draws three daily estimates without invented uncertainty bands and preserves missing totals", () => {
    const points = forecast(fixtures.forecast, "MUNTENIA");
    points[1].estimate = null;
    const series = forecastOption(points).series as LineSeriesOption[];
    expect(series).toHaveLength(1);
    expect(series[0].connectNulls).toBe(false);
    expect(series[0].data).toEqual(
      points.map((point) => [point.timestamp, point.estimate]),
    );
    expect(series[0].areaStyle).toBeUndefined();
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
