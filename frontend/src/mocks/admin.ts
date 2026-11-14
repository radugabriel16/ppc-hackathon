import { http, HttpResponse, type RequestHandler } from "msw";
import type {
  Alert,
  PoliciesConfig,
  SimulatorStatus,
  SimulatorStartRequest,
  SimulatorBackfillRequest,
  ScenarioRun,
} from "../api/gen/types.gen";
import type { DemoStore } from "../upload/fake-transport";

// Supplemental mock records: the contract supplies schemas, but no admin examples.
const initialPolicies: PoliciesConfig = {
  categories: {
    METER_READING: {
      backend: "db",
      fallback: "s3",
      maxSizeBytes: 10485760,
      maxConcurrency: 8,
      encryption: "AES-256",
      resumable: false,
      chunkSizeBytes: null,
    },
    OUTAGE_RECORD: {
      backend: "db",
      fallback: "s3",
      maxSizeBytes: 52428800,
      maxConcurrency: 4,
      encryption: "AES-256",
      resumable: true,
      chunkSizeBytes: 16777216,
    },
    CONNECTION_DOCUMENT: {
      backend: "s3",
      fallback: "ftp",
      maxSizeBytes: 104857600,
      maxConcurrency: 3,
      encryption: "AES-256",
      resumable: true,
      chunkSizeBytes: 16777216,
    },
    DRONE_VIDEO: {
      backend: "s3",
      fallback: "ftp",
      maxSizeBytes: 10737418240,
      maxConcurrency: 3,
      encryption: "AES-256",
      resumable: true,
      chunkSizeBytes: 16777216,
    },
  },
};
interface AdminState {
  status: SimulatorStatus;
  runs: ScenarioRun[];
  alerts: Alert[];
}
interface Dependencies {
  base: string;
  store: DemoStore;
  guard: (
    request: Request,
    mutation?: boolean,
    manager?: boolean,
  ) => Promise<Response | undefined>;
  error: (status: number, message: string, code?: string) => Response;
  page: <T>(rows: T[], request: Request) => object;
}
export function createAdminHandlers({
  base,
  store,
  guard,
  error,
  page,
}: Dependencies): RequestHandler[] {
  const seededAt = new Date().toISOString();
  const state = async (): Promise<AdminState> =>
    (await store.get<AdminState>("mock:admin")) ?? {
      status: { running: false, profile: null, readingsPerSecond: null },
      runs: [],
      alerts: [
        {
          id: "f34b9b8e-2640-47dc-98a5-6ca19ea58b62",
          severity: "WARNING",
          message: "Mock storage fallback threshold exceeded for DRONE_VIDEO.",
          occurredAt: seededAt,
        },
      ],
    };
  let writing: Promise<unknown> = Promise.resolve();
  const mutate = (run: (current: AdminState) => Promise<Response>) => {
    const result = writing.then(async () => run(await state()));
    writing = result.catch(() => undefined);
    return result;
  };
  return [
    http.get(`${base}/admin/policies`, async ({ request }) => {
      const denied = await guard(request, false, true);
      return (
        denied ??
        HttpResponse.json(
          (await store.get<PoliciesConfig>("mock:policies")) ?? initialPolicies,
        )
      );
    }),
    http.post(`${base}/admin/policies/reload`, async ({ request }) => {
      const denied = await guard(request, true, true);
      if (denied) return denied;
      // Reload a deterministic mock configuration; there is no server disk in MSW.
      await store.put("mock:policies", initialPolicies);
      return HttpResponse.json(initialPolicies);
    }),
    http.get(`${base}/admin/simulator/status`, async ({ request }) => {
      const denied = await guard(request, false, true);
      return denied ?? HttpResponse.json((await state()).status);
    }),
    http.post(`${base}/admin/simulator/start`, async ({ request }) => {
      const denied = await guard(request, true, true);
      if (denied) return denied;
      const body = (await request.json()) as SimulatorStartRequest;
      if (
        !body ||
        !["normal", "peak", "storm"].includes(body.profile ?? "") ||
        typeof body.readingsPerSecond !== "number" ||
        !Number.isFinite(body.readingsPerSecond) ||
        body.readingsPerSecond <= 0
      )
        return error(
          422,
          "Choose normal, peak or storm and a positive readings rate.",
          "VALIDATION",
        );
      return mutate(async (current) => {
        const now = new Date().toISOString();
        for (const run of current.runs)
          if (run.kind === "SIMULATOR" && run.endedAt === null)
            run.endedAt = now;
        current.status = {
          running: true,
          profile: body.profile,
          readingsPerSecond: body.readingsPerSecond,
        };
        current.runs.unshift({
          id: crypto.randomUUID(),
          kind: "SIMULATOR",
          profile: body.profile,
          startedAt: now,
          endedAt: null,
          counters: { readings: 0 },
        });
        await store.put("mock:admin", current);
        return HttpResponse.json(current.status, { status: 202 });
      });
    }),
    http.post(`${base}/admin/simulator/stop`, async ({ request }) => {
      const denied = await guard(request, true, true);
      if (denied) return denied;
      return mutate(async (current) => {
        current.status = {
          running: false,
          profile: null,
          readingsPerSecond: null,
        };
        for (const run of current.runs)
          if (run.kind === "SIMULATOR" && run.endedAt === null)
            run.endedAt = new Date().toISOString();
        await store.put("mock:admin", current);
        return HttpResponse.json(current.status, { status: 202 });
      });
    }),
    http.post(`${base}/admin/simulator/backfill`, async ({ request }) => {
      const denied = await guard(request, true, true);
      if (denied) return denied;
      const body = (await request.json()) as SimulatorBackfillRequest;
      if (
        !body ||
        !["spike", "zero", "gap"].includes(body.profile ?? "") ||
        !Number.isFinite(Date.parse(body.from ?? "")) ||
        !Number.isFinite(Date.parse(body.to ?? "")) ||
        Date.parse(body.from!) >= Date.parse(body.to!)
      )
        return error(
          422,
          "Choose spike, zero or gap and a valid time range (from before to).",
          "VALIDATION",
        );
      return mutate(async (current) => {
        const now = new Date().toISOString();
        const run: ScenarioRun = {
          id: crypto.randomUUID(),
          kind: "BACKFILL",
          profile: body.profile,
          startedAt: now,
          endedAt: now,
          counters: { anomalies: 1 },
        };
        current.runs.unshift(run);
        current.alerts.unshift({
          id: crypto.randomUUID(),
          severity: "WARNING",
          message: `Mock ${body.profile} anomaly in backfill ${body.from} – ${body.to}.`,
          occurredAt: now,
        });
        current.alerts = current.alerts.slice(0, 50);
        await store.put("mock:admin", current);
        return HttpResponse.json(run, { status: 202 });
      });
    }),
    http.get(`${base}/admin/scenario-runs`, async ({ request }) => {
      const denied = await guard(request, false, true);
      return denied ?? HttpResponse.json(page((await state()).runs, request));
    }),
    http.get(`${base}/alerts/recent`, async ({ request }) => {
      // Contract requires a session here, but does not specify MANAGER-only access.
      const denied = await guard(request);
      return denied ?? HttpResponse.json((await state()).alerts);
    }),
  ];
}
