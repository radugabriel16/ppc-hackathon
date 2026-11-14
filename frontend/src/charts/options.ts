import type { EChartsOption, LineSeriesOption } from "echarts";
import { theme } from "../theme";
import {
  CATEGORIES,
  STORAGES,
  label,
  type ForecastPoint,
  type MeterConsumption,
  type StorageBenchmark,
} from "../data/models";

export const BENCHMARK_METRICS = {
  p50Ms: "p50 latency (ms)",
  p95Ms: "p95 latency (ms)",
  p99Ms: "p99 latency (ms)",
  throughputMiBps: "Throughput (MiB/s)",
  errorRate: "Error rate (%)",
} as const;
export type BenchmarkMetric = keyof typeof BENCHMARK_METRICS;
const palette = theme.palette;
export const chartDefaults: EChartsOption = {
  animation: false,
  textStyle: {
    fontFamily: theme.typography.fontFamily,
    color: palette.text.primary,
  },
  aria: { enabled: true },
  grid: { left: 65, right: 25, top: 45, bottom: 65 },
  tooltip: { trigger: "axis", renderMode: "richText", confine: true },
};
export function benchmarkOption(
  rows: StorageBenchmark[],
  metric: BenchmarkMetric,
): EChartsOption {
  if (!rows.length) return { ...chartDefaults, series: [] };
  const values = rows.map(
    (row) => row[metric] * (metric === "errorRate" ? 100 : 1),
  );
  return {
    ...chartDefaults,
    grid: { left: 175, right: 35, top: 25, bottom: 75 },
    tooltip: { trigger: "item", renderMode: "richText", confine: true },
    xAxis: {
      type: "category",
      data: STORAGES.map((storage) => storage.toUpperCase()),
      splitArea: { show: true },
    },
    yAxis: {
      type: "category",
      data: CATEGORIES.map(label),
      inverse: true,
      splitArea: { show: true },
    },
    visualMap: {
      min: Math.min(...values),
      max: Math.max(...values),
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      inRange: {
        color:
          metric === "throughputMiBps"
            ? ["#edf4e4", "#70ad81", palette.primary.dark]
            : ["#e6f1eb", "#ecd884", "#d18454", palette.error.main],
      },
    },
    series: [
      {
        name: BENCHMARK_METRICS[metric],
        type: "heatmap",
        data: rows.map((row, i) => [
          STORAGES.indexOf(row.storage),
          CATEGORIES.indexOf(row.category),
          values[i],
        ]),
        label: {
          show: true,
          formatter: (params) =>
            Number((params.value as number[])[2]).toFixed(2),
        },
        itemStyle: { borderWidth: 3, borderColor: "white" },
      },
    ],
  };
}

export function meterOption(meter: MeterConsumption): EChartsOption {
  const anomalies = meter.readings.filter(
    (reading) =>
      reading.kWh !== null &&
      (reading.anomaly === "spike" || reading.anomaly === "zero"),
  );
  return {
    ...chartDefaults,
    legend: { data: ["Consumption", "Spike / zero anomaly"], top: 0 },
    xAxis: { type: "time" },
    yAxis: { type: "value", name: "kWh / interval", min: 0 },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 10 }],
    series: [
      {
        name: "Consumption",
        type: "line",
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color: palette.primary.main, width: 2 },
        itemStyle: { color: palette.primary.main },
        data: meter.readings.map((reading) => [reading.timestamp, reading.kWh]),
        markArea: {
          silent: true,
          itemStyle: { color: "rgba(217,172,64,0.2)" },
          label: { show: true, color: palette.warning.main, fontSize: 10 },
          data: meter.readings
            .filter((reading) => reading.kWh === null)
            .map((reading) => [
              {
                name: "Missing",
                xAxis:
                  Date.parse(reading.timestamp) - meter.intervalMinutes * 30000,
              },
              {
                xAxis:
                  Date.parse(reading.timestamp) + meter.intervalMinutes * 30000,
              },
            ]),
        },
      },
      {
        name: "Spike / zero anomaly",
        type: "scatter",
        symbol: "diamond",
        symbolSize: 13,
        itemStyle: { color: palette.error.main },
        data: anomalies.map((reading) => ({
          value: [reading.timestamp, reading.kWh],
          name: reading.anomaly!,
        })),
        label: { show: true, formatter: "{b}", position: "top", fontSize: 10 },
      },
    ],
  };
}

export function forecastOption(points: ForecastPoint[]): EChartsOption {
  const band = (level: "80" | "95"): LineSeriesOption[] => {
    const lower = level === "80" ? "lower80" : "lower95";
    const upper = level === "80" ? "upper80" : "upper95";
    return [
      {
        name: `${level}% lower offset`,
        type: "line",
        stack: level,
        stackStrategy: "all",
        symbol: "none",
        silent: true,
        lineStyle: { opacity: 0 },
        areaStyle: { opacity: 0 },
        tooltip: { show: false },
        data: points.map((point) => [point.timestamp, point[lower]]),
      },
      {
        name: `${level}% interval`,
        type: "line",
        stack: level,
        stackStrategy: "all",
        symbol: "none",
        silent: true,
        lineStyle: { opacity: 0 },
        areaStyle: {
          color: palette.primary.main,
          opacity: level === "80" ? 0.24 : 0.12,
        },
        tooltip: { show: false },
        data: points.map((point) => [
          point.timestamp,
          point[upper] - point[lower],
        ]),
      },
    ];
  };
  return {
    ...chartDefaults,
    legend: { data: ["Estimate", "80% interval", "95% interval"], top: 0 },
    xAxis: { type: "time" },
    yAxis: { type: "value", name: "kWh", scale: true },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 10 }],
    series: [
      ...band("95"),
      ...band("80"),
      {
        name: "Estimate",
        type: "line",
        showSymbol: false,
        lineStyle: { color: palette.primary.main, width: 2.5 },
        itemStyle: { color: palette.primary.main },
        dimensions: [
          "Time",
          "Estimate (kWh)",
          "80% lower",
          "80% upper",
          "95% lower",
          "95% upper",
        ],
        encode: { x: 0, y: 1, tooltip: [1, 2, 3, 4, 5] },
        data: points.map((point) => [
          point.timestamp,
          point.estimate,
          point.lower80,
          point.upper80,
          point.lower95,
          point.upper95,
        ]),
      },
    ],
  };
}
