import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
} from "vitest";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { ApiSource } from "./api-source";
import { createMockApi } from "../mocks/handlers";
import { MemoryDemoStore } from "../upload/fake-transport";
import { createStatsFixtures } from "../mocks/stats";
import { mockRegions } from "../mocks/fixtures";
import {
  forecast,
  meterConsumption,
  outageHotspots,
  storageBenchmark,
  storageRecommendations,
} from "./stats-mapping";

const mock = createMockApi({ store: new MemoryDemoStore() });
const server = setupServer(...mock.handlers);
const base = "http://127.0.0.1/api/v1";
const paths = [
  "storage-benchmark",
  "recommendations",
  "meters",
  "outages/hotspots",
  "forecast",
];
let source: ApiSource;
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());
afterEach(() => {
  server.resetHandlers();
  server.events.removeAllListeners("request:start");
});
beforeEach(async () => {
  await mock.reset();
  source = new ApiSource(base, "mock");
  await source.login({
    name: "operator",
    password: "operator",
    role: "OPERATOR",
  });
});
const allStats = () =>
  Promise.all([
    source.getStorageBenchmark(),
    source.getStorageRecommendations(),
    source.getMeterConsumption("MUNTENIA"),
    source.getOutageHotspots("MUNTENIA"),
    source.getForecast("MUNTENIA"),
  ]);
describe("statistics HTTP operations and strict mappings", () => {
  it("uses the stats endpoints through the generated client, without operational list aggregation", async () => {
    const requests: Request[] = [];
    server.events.on("request:start", ({ request }) => {
      requests.push(request);
    });
    const [benchmark, recommendations, meters, hotspots, predictions] =
      await allStats();
    expect(
      requests.map((request) => new URL(request.url).pathname).sort(),
    ).toEqual(
      [
        "/api/v1/regions",
        ...paths.map((path) => `/api/v1/stats/${path}`),
      ].sort(),
    );
    expect(
      requests.every(
        (request) =>
          request.method === "GET" && request.credentials === "include",
      ),
    ).toBe(true);
    expect(benchmark).toHaveLength(24);
    expect(benchmark.filter((row) => row.profile === "normal")).toHaveLength(
      12,
    );
    expect(benchmark.filter((row) => row.profile === "peak")).toHaveLength(12);
    expect(
      benchmark.find(
        (row) =>
          row.category === "METER_READING" &&
          row.storage === "db" &&
          row.profile === "peak",
      )!.p95Ms,
    ).toBeGreaterThan(
      benchmark.find(
        (row) =>
          row.category === "METER_READING" &&
          row.storage === "db" &&
          row.profile === "normal",
      )!.p95Ms,
    );
    expect(recommendations).toHaveLength(4);
    expect(recommendations.every((row) => row.reason.length > 50)).toBe(true);
    expect(meters).toHaveLength(3);
    expect(meters.every((meter) => meter.region === "MUNTENIA")).toBe(true);
    expect(meters[0].readings).toHaveLength(96);
    expect(
      meters[0].readings.filter((reading) => reading.kWh === null),
    ).toHaveLength(3);
    expect(
      meters[0].readings.find((reading) => reading.anomaly === "zero")?.kWh,
    ).toBe(0);
    expect(hotspots).toHaveLength(18);
    expect(hotspots.every((row) => row.region === "MUNTENIA")).toBe(true);
    expect(hotspots[0].outageCount).toBeGreaterThanOrEqual(
      hotspots[17].outageCount,
    );
    expect(predictions).toHaveLength(3);
    expect(
      predictions.every(
        (point) =>
          point.status === "READY" &&
          point.estimate !== null &&
          !point.fallbackUsed &&
          point.asOf.length > 0,
      ),
    ).toBe(true);
  });
  it("sends documented region filters for meter/forecast/hotspot responses", async () => {
    server.events.on("request:start", ({ request }) => {
      const url = new URL(request.url);
      if (url.pathname.endsWith("/regions")) {
        expect(url.search).toBe("?page=0&size=100");
      } else {
        expect(mockRegions.map((region) => region.id)).toContain(
          url.searchParams.get("regionId"),
        );
        expect(url.searchParams.has("subregionId")).toBe(false);
      }
    });
    expect((await source.getMeterConsumption("BANAT"))[0].id).toBe("BAN-M1");
    expect((await source.getOutageHotspots("DOBROGEA"))[0].region).toBe(
      "DOBROGEA",
    );
    const muntenia = await source.getForecast("MUNTENIA");
    const banat = await source.getForecast("BANAT");
    expect(muntenia[0].estimate).toBeGreaterThan(banat[0].estimate!);
  });
  it("requires authentication for every stats endpoint, including the mock forecast extension", async () => {
    await source.logout();
    for (const path of paths)
      expect((await fetch(`${base}/stats/${path}`)).status).toBe(401);
  });
  it("returns no measurements for empty API responses and never falls back to fixtures", async () => {
    source = new ApiSource(base, "api");
    server.use(
      http.get(`${base}/stats/*`, ({ request }) =>
        HttpResponse.json(
          new URL(request.url).pathname.endsWith("/forecast")
            ? { items: [] }
            : {},
        ),
      ),
    );
    expect(await allStats()).toEqual([[], [], [], [], []]);
    server.use(
      http.get(`${base}/stats/storage-benchmark`, () =>
        HttpResponse.json({ rows: [] }),
      ),
      http.get(`${base}/stats/recommendations`, () =>
        HttpResponse.json({ items: [] }),
      ),
      http.get(`${base}/stats/meters`, () => HttpResponse.json({ meters: [] })),
      http.get(`${base}/stats/outages/hotspots`, () =>
        HttpResponse.json({ type: "FeatureCollection", features: [] }),
      ),
      http.get(`${base}/stats/forecast`, () =>
        HttpResponse.json({ items: [] }),
      ),
    );
    expect(await allStats()).toEqual([[], [], [], [], []]);
  });
  it("surfaces a missing forecast operation and server failures with request IDs in API mode", async () => {
    source = new ApiSource(base, "api");
    server.use(
      http.get(`${base}/stats/forecast`, () =>
        HttpResponse.json(
          {
            code: "NOT_FOUND",
            message: "Forecast endpoint unavailable",
            requestId: "forecast-404",
          },
          { status: 404 },
        ),
      ),
      http.get(`${base}/stats/meters`, () =>
        HttpResponse.json(
          {
            code: "DOWN",
            message: "Meter statistics unavailable",
            requestId: "meters-503",
          },
          { status: 503 },
        ),
      ),
    );
    await expect(source.getForecast("MUNTENIA")).rejects.toMatchObject({
      status: 404,
      body: {
        message: "Forecast endpoint unavailable",
        requestId: "forecast-404",
      },
    });
    await expect(source.getMeterConsumption("MUNTENIA")).rejects.toMatchObject({
      status: 503,
      body: { requestId: "meters-503" },
    });
    expect(await source.getStorageRecommendations()).toHaveLength(4);
  });
  it("rejects nonempty unrecognized shapes and missing metrics instead of inventing numbers", async () => {
    source = new ApiSource(base, "api");
    server.use(
      http.get(`${base}/stats/storage-benchmark`, () =>
        HttpResponse.json({ latency: 12 }),
      ),
    );
    await expect(source.getStorageBenchmark()).rejects.toMatchObject({
      body: { code: "CONTRACT_MISMATCH" },
    });
    const fixtures = createStatsFixtures();
    const { p50Ms: _, ...missing } = fixtures.benchmark.rows[0];
    void _;
    expect(() => storageBenchmark({ rows: [missing] })).toThrow(/p50Ms/);
    expect(() =>
      storageBenchmark({
        rows: [{ ...fixtures.benchmark.rows[0], errorRate: 2 }],
      }),
    ).toThrow(/errorRate/);
    expect(() =>
      storageRecommendations({
        items: [{ category: "DRONE_VIDEO", storage: "s3" }],
      }),
    ).toThrow(/reason/);
  });
  it("expands only the reported meter window and preserves missing versus measured zero", () => {
    const payload = {
      meters: [
        {
          id: "meter-1",
          label: "Meter 1",
          regionCode: "MUNTENIA",
          intervalMinutes: 15,
          from: "2026-11-14T00:00:00Z",
          to: "2026-11-14T01:00:00Z",
          readings: [
            { timestamp: "2026-11-14T00:15:00Z", kWh: 0, anomaly: "zero" },
            { timestamp: "2026-11-14T00:45:00Z", kWh: 0.8 },
          ],
        },
      ],
    };
    const result = meterConsumption(payload, "MUNTENIA")[0];
    expect(result.readings.map((row) => row.kWh)).toEqual([
      null,
      0,
      null,
      0.8,
      null,
    ]);
    expect(result.readings.map((row) => row.anomaly)).toEqual([
      "gap",
      "zero",
      "gap",
      null,
      "gap",
    ]);
    payload.meters[0].readings = [];
    expect(meterConsumption(payload, "MUNTENIA")[0].readings).toEqual([]);
  });
  it("rejects impossible windows, duplicate timestamps, invalid coordinates and invalid forecast horizons", () => {
    const fixtures = createStatsFixtures();
    const meter = fixtures.meters.meters[0];
    expect(() =>
      meterConsumption(
        { meters: [{ ...meter, intervalMinutes: 0 }] },
        "MUNTENIA",
      ),
    ).toThrow(/interval/);
    expect(() =>
      meterConsumption(
        {
          meters: [
            { ...meter, readings: [meter.readings[0], meter.readings[0]] },
          ],
        },
        "MUNTENIA",
      ),
    ).toThrow(/duplicate/);
    const feature = fixtures.hotspots.features[0];
    expect(() =>
      outageHotspots(
        {
          type: "FeatureCollection",
          features: [
            { ...feature, geometry: { type: "Point", coordinates: [200, 44] } },
          ],
        },
        "MUNTENIA",
      ),
    ).toThrow(/coordinates/);
    const series = fixtures.forecast.items[0];
    expect(() =>
      forecast(
        {
          items: [
            {
              ...series,
              forecasts: [
                { ...series.forecasts[0], horizon: 2 },
                ...series.forecasts.slice(1),
              ],
            },
          ],
        },
        "MUNTENIA",
      ),
    ).toThrow(/horizon/);
  });

  it("never reports partial regional totals and flags baseline estimates", () => {
    const fixtures = createStatsFixtures();
    const first = fixtures.forecast.items[0];
    const missing = {
      ...first,
      segmentId: "second",
      forecasts: first.forecasts.map((point) => ({
        ...point,
        predictedEnergyKwh: null,
        status: "INSUFFICIENT_DATA",
        fallbackUsed: true,
      })),
    };
    const points = forecast({ items: [first, missing] }, "MUNTENIA");
    expect(points).toHaveLength(3);
    expect(
      points.every((point) => point.estimate === null && point.fallbackUsed),
    ).toBe(true);
    const baseline = {
      ...missing,
      forecasts: missing.forecasts.map((point) => ({
        ...point,
        predictedEnergyKwh: 10,
        status: "READY",
      })),
    };
    expect(forecast({ items: [first, baseline] }, "MUNTENIA")[0]).toMatchObject(
      {
        estimate: first.forecasts[0].predictedEnergyKwh + 10,
        fallbackUsed: true,
      },
    );
  });

  it("fetches every forecast page before aggregating a region", async () => {
    const item = createStatsFixtures().forecast.items[0];
    server.use(
      http.get(`${base}/stats/forecast`, ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page"));
        return HttpResponse.json({
          items: [{ ...item, segmentId: `segment-${page}` }],
          page,
          size: 100,
          totalElements: 2,
          totalPages: 2,
        });
      }),
    );
    const points = await source.getForecast("MUNTENIA");
    expect(points[0].estimate).toBe(item.forecasts[0].predictedEnergyKwh * 2);
  });
});
