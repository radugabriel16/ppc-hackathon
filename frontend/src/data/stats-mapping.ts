import { contractError } from "./api-client";
import {
  CATEGORIES,
  REGIONS,
  STORAGES,
  type BenchmarkProfile,
  type ForecastPoint,
  type MeterAnomaly,
  type MeterConsumption,
  type OutageHotspot,
  type Region,
  type StorageBenchmark,
  type StorageRecommendation,
} from "./models";

// Provisional wire shapes are documented in CONTRACT_ISSUES.md. The contract's
// stats schemas are opaque objects: validate at this boundary, never guess data.
function invalid(field: string): never {
  throw contractError(`Unsupported statistics response: ${field}.`);
}
function object(value: unknown, field: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return invalid(field);
  return value as Record<string, unknown>;
}
function rows(value: unknown, key: string): unknown[] {
  if (value == null || (Array.isArray(value) && value.length === 0)) return [];
  const root = object(value, key);
  if (Object.keys(root).length === 0) return [];
  if (!Array.isArray(root[key])) return invalid(key);
  return root[key];
}
function text(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim()) return invalid(field);
  return value;
}
function number(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0)
    return invalid(field);
  return value;
}
function member<T extends string>(
  value: unknown,
  choices: readonly T[],
  field: string,
): T {
  if (!choices.includes(value as T)) return invalid(field);
  return value as T;
}
function timestamp(value: unknown): string {
  const time = text(value, "timestamp");
  // Require an offset to avoid interpreting API timestamps in the browser timezone.
  if (!/(Z|[+-]\d{2}:\d{2})$/i.test(time) || !Number.isFinite(Date.parse(time)))
    return invalid("timestamp (ISO date-time with offset)");
  return new Date(time).toISOString();
}
function unique(values: string[], field: string) {
  if (new Set(values).size !== values.length) invalid(`duplicate ${field}`);
}
export function storageBenchmark(value: unknown): StorageBenchmark[] {
  const result = rows(value, "rows").map((row): StorageBenchmark => {
    const dto = object(row, "benchmark row");
    const result = {
      category: member(dto.category, CATEGORIES, "category"),
      storage: member(dto.storage, STORAGES, "storage"),
      profile: member<BenchmarkProfile>(
        dto.profile,
        ["normal", "peak"],
        "profile",
      ),
      p50Ms: number(dto.p50Ms, "p50Ms"),
      p95Ms: number(dto.p95Ms, "p95Ms"),
      p99Ms: number(dto.p99Ms, "p99Ms"),
      throughputMiBps: number(dto.throughputMiBps, "throughputMiBps"),
      errorRate: number(dto.errorRate, "errorRate"),
    };
    if (
      result.p50Ms > result.p95Ms ||
      result.p95Ms > result.p99Ms ||
      result.errorRate > 1
    )
      invalid("latency quantile order or errorRate outside [0,1]");
    return result;
  });
  unique(
    result.map((x) => `${x.category}:${x.storage}:${x.profile}`),
    "benchmark cell",
  );
  return result;
}
export function storageRecommendations(
  value: unknown,
): StorageRecommendation[] {
  const result = rows(value, "items").map((row) => {
    const dto = object(row, "recommendation");
    return {
      category: member(dto.category, CATEGORIES, "category"),
      storage: member(dto.storage, STORAGES, "storage"),
      reason: text(dto.reason, "recommendation.reason"),
    };
  });
  unique(
    result.map((x) => x.category),
    "recommendation category",
  );
  return result;
}
export function meterConsumption(
  value: unknown,
  region: Region,
): MeterConsumption[] {
  const meters = rows(value, "meters").map((row): MeterConsumption => {
    const dto = object(row, "meter");
    const code = member(dto.regionCode, REGIONS, "meter.regionCode");
    const intervalMinutes = number(dto.intervalMinutes, "intervalMinutes");
    if (intervalMinutes <= 0) invalid("intervalMinutes must be positive");
    const from = Date.parse(timestamp(dto.from));
    const to = Date.parse(timestamp(dto.to));
    const step = intervalMinutes * 60000;
    const count = (to - from) / step + 1;
    if (!Number.isSafeInteger(count) || count < 1 || count > 10000)
      invalid("meter window (maximum 10000 aligned intervals)");
    if (!Array.isArray(dto.readings)) invalid("meter.readings");
    const readings = dto.readings.map((row) => {
      const reading = object(row, "reading");
      const time = timestamp(reading.timestamp);
      if (
        Date.parse(time) < from ||
        Date.parse(time) > to ||
        (Date.parse(time) - from) % step !== 0
      )
        invalid("reading outside or misaligned with meter window");
      const kWh =
        reading.kWh === null ? null : number(reading.kWh, "reading.kWh");
      const anomaly =
        reading.anomaly == null
          ? null
          : member<MeterAnomaly>(
              reading.anomaly,
              ["spike", "zero", "gap"],
              "reading.anomaly",
            );
      if (anomaly === "gap" && kWh !== null)
        invalid("gap with a measured value");
      return {
        timestamp: time,
        kWh,
        anomaly: kWh === null ? ("gap" as const) : anomaly,
      };
    });
    unique(
      readings.map((x) => x.timestamp),
      "reading timestamp",
    );
    const byTime = new Map(readings.map((x) => [x.timestamp, x]));
    return {
      id: text(dto.id, "meter.id"),
      label: text(dto.label, "meter.label"),
      region: code,
      intervalMinutes,
      // Null marks an explicitly expected but absent interval; never impute kWh.
      readings:
        readings.length === 0
          ? []
          : Array.from({ length: count }, (_, index) => {
              const time = new Date(from + index * step).toISOString();
              return (
                byTime.get(time) ?? {
                  timestamp: time,
                  kWh: null,
                  anomaly: "gap" as const,
                }
              );
            }),
    };
  });
  unique(
    meters.map((x) => x.id),
    "meter ID",
  );
  return meters.filter((x) => x.region === region);
}
export function outageHotspots(
  value: unknown,
  region: Region,
): OutageHotspot[] {
  const features = rows(value, "features");
  if (features.length && object(value, "hotspots").type !== "FeatureCollection")
    invalid("hotspots.type");
  const result = features.map((row): OutageHotspot => {
    const dto = object(row, "hotspot feature");
    const geometry = object(dto.geometry, "hotspot.geometry");
    const props = object(dto.properties, "hotspot.properties");
    if (
      dto.type !== "Feature" ||
      geometry.type !== "Point" ||
      !Array.isArray(geometry.coordinates) ||
      geometry.coordinates.length !== 2
    )
      invalid("hotspot Point geometry");
    const [lon, lat] = geometry.coordinates as unknown[];
    if (
      typeof lon !== "number" ||
      typeof lat !== "number" ||
      !Number.isFinite(lon) ||
      !Number.isFinite(lat) ||
      Math.abs(lon) > 180 ||
      Math.abs(lat) > 90
    )
      invalid("hotspot coordinates [lon,lat]");
    const outageCount = number(props.outageCount, "outageCount");
    if (!Number.isSafeInteger(outageCount)) invalid("outageCount integer");
    return {
      id: text(props.id, "hotspot.id"),
      assetName: text(props.assetName, "hotspot.assetName"),
      region: member(props.regionCode, REGIONS, "hotspot.regionCode"),
      coordinates: [lon as number, lat as number],
      outageCount,
      durationMinutes: number(props.durationMinutes, "durationMinutes"),
    };
  });
  unique(
    result.map((x) => x.id),
    "hotspot ID",
  );
  return result
    .filter((x) => x.region === region)
    .sort((a, b) => b.outageCount - a.outageCount);
}
export function forecast(value: unknown, region: Region): ForecastPoint[] {
  const series = rows(value, "series").map((row) => {
    const dto = object(row, "forecast series");
    const code = member(dto.regionCode, REGIONS, "forecast.regionCode");
    if (dto.unit !== "kWh" || !Array.isArray(dto.points))
      invalid("forecast.unit/points");
    const points = dto.points
      .map((row): ForecastPoint => {
        const point = object(row, "forecast point");
        const result = {
          timestamp: timestamp(point.timestamp),
          estimate: number(point.estimate, "estimate"),
          lower80: number(point.lower80, "lower80"),
          upper80: number(point.upper80, "upper80"),
          lower95: number(point.lower95, "lower95"),
          upper95: number(point.upper95, "upper95"),
        };
        if (
          !(
            result.lower95 <= result.lower80 &&
            result.lower80 <= result.estimate &&
            result.estimate <= result.upper80 &&
            result.upper80 <= result.upper95
          )
        )
          invalid("forecast bands must enclose estimate and be nested");
        return result;
      })
      .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    unique(
      points.map((x) => x.timestamp),
      "forecast timestamp",
    );
    return { region: code, points };
  });
  unique(
    series.map((x) => x.region),
    "forecast region",
  );
  return series.find((x) => x.region === region)?.points ?? [];
}
