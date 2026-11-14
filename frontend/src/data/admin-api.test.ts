import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
} from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ApiSource } from "./api-source";
import { createMockApi } from "../mocks/handlers";
import { MemoryDemoStore } from "../upload/fake-transport";

const mock = createMockApi({ store: new MemoryDemoStore() });
const server = setupServer(...mock.handlers);
const base = "http://127.0.0.1/api/v1";
let source: ApiSource;
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());
afterEach(() => server.resetHandlers());
beforeEach(async () => {
  await mock.reset();
  source = new ApiSource(base, "mock");
  await source.login({ name: "manager", password: "manager", role: "MANAGER" });
});
const adminRequests = [
  ["GET", "/admin/policies"],
  ["POST", "/admin/policies/reload"],
  ["GET", "/admin/simulator/status"],
  ["POST", "/admin/simulator/start"],
  ["POST", "/admin/simulator/stop"],
  ["POST", "/admin/simulator/backfill"],
  ["GET", "/admin/scenario-runs"],
] as const;
describe("Admin generated client and schema-based MSW handlers", () => {
  it("maps every policy field and returns the revalidated configuration on reload", async () => {
    const policies = await source.getPolicies();
    expect(policies).toHaveLength(4);
    expect(policies.find((row) => row.category === "DRONE_VIDEO")).toEqual({
      category: "DRONE_VIDEO",
      backend: "s3",
      fallback: "ftp",
      maxSizeBytes: 10737418240,
      maxConcurrency: 3,
      encryption: "AES-256",
      resumable: true,
      chunkSizeBytes: 16777216,
    });
    expect(
      policies.find((row) => row.category === "METER_READING"),
    ).toMatchObject({ resumable: false, chunkSizeBytes: null });
    expect(await source.reloadPolicies()).toEqual(policies);
  });
  it("starts/stops the simulator, persists state through source reload and pages run history", async () => {
    expect(await source.getSimulatorStatus()).toEqual({
      running: false,
      profile: null,
      readingsPerSecond: null,
    });
    for (const profile of ["normal", "peak", "storm"] as const) {
      expect(
        await source.startSimulator({ profile, readingsPerSecond: 12.5 }),
      ).toEqual({ running: true, profile, readingsPerSecond: 12.5 });
    }
    const reloaded = new ApiSource(base, "mock");
    await reloaded.getSession();
    expect(await reloaded.getSimulatorStatus()).toMatchObject({
      running: true,
      profile: "storm",
    });
    const first = await source.getScenarioRuns(0, 2);
    expect(first).toMatchObject({
      page: 0,
      size: 2,
      totalElements: 3,
      totalPages: 2,
    });
    expect(first.items).toHaveLength(2);
    expect(first.items[0]).toMatchObject({
      kind: "SIMULATOR",
      profile: "storm",
      endedAt: null,
      counters: { readings: 0 },
    });
    expect(first.items[1].endedAt).toEqual(expect.any(String));
    expect((await source.getScenarioRuns(1, 2)).items).toHaveLength(1);
    expect(await reloaded.stopSimulator()).toEqual({
      running: false,
      profile: null,
      readingsPerSecond: null,
    });
    expect((await source.getScenarioRuns(0, 2)).items[0].endedAt).toEqual(
      expect.any(String),
    );
  });
  it.each(["spike", "zero", "gap"] as const)(
    "maps %s to the backfill profile without inventing a request field",
    async (anomaly) => {
      const input = {
        anomaly,
        from: "2026-11-01T00:00:00.000Z",
        to: "2026-11-02T00:00:00.000Z",
      };
      let body: unknown;
      let csrf: string | null = null;
      // Observe the actual generated HTTP request while allowing the real handler to run.
      server.events.on("request:start", async ({ request }) => {
        if (request.url.endsWith("/admin/simulator/backfill")) {
          body = await request.clone().json();
          csrf = request.headers.get("X-CSRF-Token");
        }
      });
      try {
        const run = await source.backfillSimulator(input);
        expect(body).toEqual({
          profile: anomaly,
          from: input.from,
          to: input.to,
        });
        expect(csrf).toBeTruthy();
        expect(run).toMatchObject({
          kind: "BACKFILL",
          profile: anomaly,
          counters: { anomalies: 1 },
        });
        expect((await source.getScenarioRuns(0, 10)).items[0]).toEqual(run);
        expect((await source.getRecentAlerts())[0]).toMatchObject({
          severity: "WARNING",
          message: expect.stringContaining(anomaly),
          occurredAt: expect.any(String),
        });
      } finally {
        server.events.removeAllListeners("request:start");
      }
    },
  );
  it("requires manager permissions and CSRF for admin operations, and authentication for alerts", async () => {
    const manager = (await source.getSession())!;
    for (const [method, path] of adminRequests.filter(
      ([method]) => method === "POST",
    )) {
      expect((await fetch(base + path, { method })).status).toBe(403);
    }
    const operator = await source.login({
      name: "operator",
      password: "operator",
      role: "MANAGER",
    });
    for (const [method, path] of adminRequests) {
      const response = await fetch(base + path, {
        method,
        headers: { "X-CSRF-Token": operator.csrfToken },
      });
      expect(response.status, path).toBe(403);
    }
    // /alerts/recent is authenticated, but not role-restricted in the contract.
    expect((await source.getRecentAlerts()).length).toBeGreaterThan(0);
    await source.logout();
    for (const [method, path] of [
      ...adminRequests,
      ["GET", "/alerts/recent"],
    ] as const) {
      expect(
        (
          await fetch(base + path, {
            method,
            headers: { "X-CSRF-Token": manager.csrfToken },
          })
        ).status,
      ).toBe(401);
    }
  });
  it("rejects invalid profiles/rates and invalid backfill intervals", async () => {
    for (const readingsPerSecond of [0, -1, Infinity]) {
      await expect(
        source.startSimulator({ profile: "normal", readingsPerSecond }),
      ).rejects.toMatchObject({ status: 422 });
    }
    const { csrfToken } = (await source.getSession())!;
    expect(
      (
        await fetch(`${base}/admin/simulator/start`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
          },
          body: JSON.stringify({
            profile: "unsupported",
            readingsPerSecond: 10,
          }),
        })
      ).status,
    ).toBe(422);
    await expect(
      source.backfillSimulator({
        anomaly: "gap",
        from: "2026-11-02T00:00:00Z",
        to: "2026-11-01T00:00:00Z",
      }),
    ).rejects.toMatchObject({ status: 422 });
    expect((await source.getScenarioRuns(0, 5)).items).toEqual([]);
  });
  it("surfaces reload validation errors and preserves the effective policy", async () => {
    const original = await source.getPolicies();
    server.use(
      http.post(`${base}/admin/policies/reload`, () =>
        HttpResponse.json(
          {
            code: "POLICY_INVALID",
            message: "New policy failed validation; old policy kept active.",
            requestId: "policy-422",
          },
          { status: 422 },
        ),
      ),
    );
    await expect(source.reloadPolicies()).rejects.toMatchObject({
      status: 422,
      body: {
        message: expect.stringContaining("old policy kept active"),
        requestId: "policy-422",
      },
    });
    expect(await source.getPolicies()).toEqual(original);
  });
  it("represents optional fields as unknown and fails on missing essential response fields", async () => {
    server.use(
      http.get(`${base}/admin/policies`, () =>
        HttpResponse.json({ categories: { OTHER: {} } }),
      ),
      http.get(`${base}/admin/simulator/status`, () =>
        HttpResponse.json({ running: false }),
      ),
      http.get(`${base}/admin/scenario-runs`, () =>
        HttpResponse.json({
          items: [{ id: "a" }],
          page: 0,
          size: 5,
          totalElements: 1,
          totalPages: 1,
        }),
      ),
    );
    expect((await source.getPolicies())[0]).toMatchObject({
      category: "OTHER",
      resumable: null,
      maxSizeBytes: null,
    });
    expect(await source.getSimulatorStatus()).toEqual({
      running: false,
      profile: null,
      readingsPerSecond: null,
    });
    expect((await source.getScenarioRuns(0, 5)).items[0]).toEqual({
      id: "a",
      kind: null,
      profile: null,
      startedAt: null,
      endedAt: null,
      counters: {},
    });
    server.use(
      http.get(`${base}/admin/simulator/status`, () =>
        HttpResponse.json({ profile: "normal" }),
      ),
    );
    await expect(source.getSimulatorStatus()).rejects.toMatchObject({
      body: { code: "CONTRACT_MISMATCH" },
    });
  });
});
