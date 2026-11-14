import { http, HttpResponse, type RequestHandler } from "msw";
import {
  CATEGORIES,
  REGIONS,
  REGION_INFO,
  STORAGES,
  type MeterReading,
  type StorageBenchmark,
} from "../data/models";

// Deterministic synthetic telemetry, never imported by ApiSource. These explicit
// envelopes fill the contract's untyped stats objects; see CONTRACT_ISSUES.md.
export function createStatsFixtures(now = Date.now()) {
  const rows: StorageBenchmark[] = CATEGORIES.flatMap(
    (category, categoryIndex) =>
      STORAGES.flatMap((storage, storageIndex) =>
        (["normal", "peak"] as const).map((profile) => {
          const largeObject = categoryIndex >= 2;
          const baseMs =
            storage === "db"
              ? largeObject
                ? 180 + categoryIndex * 110
                : 7 + categoryIndex * 3
              : storage === "s3"
                ? 38 + categoryIndex * 12
                : 95 + categoryIndex * 22;
          const pressure =
            profile === "peak"
              ? storage === "db"
                ? 3.8
                : storage === "ftp"
                  ? 2.3
                  : 1.35
              : 1;
          const round = (value: number) => Math.round(value * 100) / 100;
          return {
            category,
            storage,
            profile,
            p50Ms: round(baseMs * pressure),
            p95Ms: round(baseMs * pressure * 1.8),
            p99Ms: round(baseMs * pressure * 3.1),
            throughputMiBps: round(
              ([24, 58, 185][storageIndex] + categoryIndex * 7) /
                (profile === "peak" ? (storage === "s3" ? 1.08 : 1.7) : 1),
            ),
            errorRate:
              round(
                (profile === "peak"
                  ? [1.7, 0.9, 0.08][storageIndex]
                  : [0.04, 0.12, 0.02][storageIndex]) *
                  (largeObject && storage === "db" ? 3 : 1),
              ) / 100,
          };
        }),
      ),
  );
  const recommendations = {
    items: [
      {
        category: "METER_READING",
        storage: "db",
        reason:
          "Small, frequent readings benefit from low database latency and indexed time-range queries. Peak latency rises under contention; batch writes and monitor the error budget.",
      },
      {
        category: "OUTAGE_RECORD",
        storage: "db",
        reason:
          "Structured outage events need transactional updates and fast operational lookups. Keep database storage primary and archive older records to object storage.",
      },
      {
        category: "CONNECTION_DOCUMENT",
        storage: "s3",
        reason:
          "Object storage sustains document throughput during peak load with fewer errors than FTP, while metadata and checklist links remain in the database.",
      },
      {
        category: "DRONE_VIDEO",
        storage: "s3",
        reason:
          "Large sequential video objects achieve the highest measured throughput on S3. Resumable multipart uploads avoid database contention and FTP peak-load failures.",
      },
    ],
  };
  const interval = 15 * 60000;
  const end = Math.floor(now / interval) * interval - interval;
  const start = end - 95 * interval;
  const meters = {
    meters: REGIONS.flatMap((regionCode, regionIndex) =>
      Array.from({ length: 3 }, (_, meterIndex) => {
        const readings: MeterReading[] = Array.from(
          { length: 96 },
          (_, i): MeterReading => {
            const hour = new Date(start + i * interval).getUTCHours();
            const dailyLoad =
              0.15 + 0.22 * Math.max(0, Math.cos(((hour - 18) * Math.PI) / 12));
            const kWh = Number(
              (
                dailyLoad * (1 + meterIndex * 0.35 + regionIndex * 0.12) +
                0.025 * Math.sin(i * 1.8)
              ).toFixed(3),
            );
            return {
              timestamp: new Date(start + i * interval).toISOString(),
              kWh:
                i === 58
                  ? Number((kWh * 6).toFixed(3))
                  : i === 62
                    ? 0
                    : i === 77
                      ? null
                      : kWh,
              anomaly:
                i === 58
                  ? "spike"
                  : i === 62
                    ? "zero"
                    : i === 77
                      ? "gap"
                      : null,
            };
          },
        ).filter((_, i) => i !== 34 && i !== 35);
        return {
          id: `${regionCode.slice(0, 3)}-M${meterIndex + 1}`,
          label: `${REGION_INFO[regionCode].name} meter ${meterIndex + 1}`,
          regionCode,
          intervalMinutes: 15,
          from: new Date(start).toISOString(),
          to: new Date(end).toISOString(),
          readings,
        };
      }),
    ),
  };
  const hotspots = {
    type: "FeatureCollection",
    features: REGIONS.flatMap((regionCode, regionIndex) =>
      Array.from({ length: 18 }, (_, index) => {
        const center = REGION_INFO[regionCode].center;
        const angle = index * 2.39996;
        const radius = 0.04 + (index % 6) * 0.055;
        const outageCount = 2 + ((index * 7 + regionIndex * 3) % 23);
        return {
          type: "Feature",
          geometry: {
            type: "Point",
            coordinates: [
              center[0] + Math.cos(angle) * radius * 1.4,
              center[1] + Math.sin(angle) * radius,
            ],
          },
          properties: {
            id: `${regionCode}-HOT-${index + 1}`,
            assetName: `${REGION_INFO[regionCode].name} feeder ${index + 1}`,
            regionCode,
            outageCount,
            durationMinutes: outageCount * (11 + (index % 8)),
          },
        };
      }),
    ),
  };
  const forecast = {
    items: REGIONS.map((region, regionIndex) => ({
      segmentId: `${region}-SEG-1`,
      region,
      units: "kWh/day",
      horizonDays: 3,
      origin: new Date(Math.floor(now / 86400000) * 86400000).toISOString(),
      asOf: new Date(
        Math.floor(now / 86400000) * 86400000 + 600000,
      ).toISOString(),
      modelVersion: "mock-hgb_smooth",
      uncertaintyIntervalsAvailable: false,
      forecasts: Array.from({ length: 3 }, (_, i) => ({
        date: new Date((Math.floor(now / 86400000) + i) * 86400000)
          .toISOString()
          .slice(0, 10),
        horizon: i + 1,
        predictedEnergyKwh:
          [230000, 115000, 90000][regionIndex] * (1 + i * 0.05),
        status: "READY",
        fallbackUsed: false,
      })),
    })),
  };
  return { benchmark: { rows }, recommendations, meters, hotspots, forecast };
}

export function createStatsHandlers(
  base: string,
  guard: (request: Request) => Promise<Response | undefined>,
): RequestHandler[] {
  const fixtures = createStatsFixtures();
  return [
    ["/stats/storage-benchmark", fixtures.benchmark],
    ["/stats/recommendations", fixtures.recommendations],
    ["/stats/meters", fixtures.meters],
    ["/stats/outages/hotspots", fixtures.hotspots],
    ["/stats/forecast", fixtures.forecast],
  ].map(([path, payload]) =>
    http.get(
      `${base}${path}`,
      async ({ request }) =>
        (await guard(request)) ?? HttpResponse.json(payload),
    ),
  );
}
