import { http, HttpResponse } from "msw";
import type { RequestHandler } from "msw";
import type {
  ConnectionCase,
  MapIssue,
  MapIssueCreateRequest,
  MapIssueStatusUpdateRequest,
  Me,
  UploadSessionCreateRequest,
  FileResource,
  GeoJsonFeature,
  FileUploadMetadata,
} from "../api/gen/types.gen";
import { digestBlob } from "../upload/hash";
import { AppError } from "../data/errors";
import {
  FakeUploadTransport,
  IndexedDemoStore,
  MemoryDemoStore,
} from "../upload/fake-transport";
import type { DemoStore } from "../upload/fake-transport";
import { examples, mockRegions } from "./fixtures";
import { createAdminHandlers } from "./admin";
import { createStatsHandlers } from "./stats";
import type { Region } from "../data/models";

type MockSession = { me: Me; csrf: string };
interface Options {
  store?: DemoStore;
  failureRate?: number;
  verifyMs?: number;
}
export function createMockApi(options: Options = {}) {
  const store =
    options.store ??
    (typeof indexedDB === "undefined"
      ? new MemoryDemoStore()
      : new IndexedDemoStore("filegrid-msw-server"));
  const uploads = new FakeUploadTransport({
    store,
    failureRate: options.failureRate ?? 0.2,
    chunkSize: examples.upload.chunkSize,
    latencyMs: 30,
    verifyMs: options.verifyMs,
  });
  const base = "*/api/v1";
  const error = (
    status: number,
    message: string,
    code = "MOCK_ERROR",
    extra: object = {},
  ) =>
    HttpResponse.json(
      { code, message, requestId: `mock-${crypto.randomUUID()}`, ...extra },
      { status },
    );
  const guard = async (request: Request, mutation = false, manager = false) => {
    const session = await store.get<MockSession>("mock:session");
    if (!session)
      return error(401, "Sign in to the mock API.", "UNAUTHENTICATED");
    if (mutation && request.headers.get("X-CSRF-Token") !== session.csrf)
      return error(403, "Invalid CSRF token.", "CSRF_INVALID");
    if (manager && session.me.role !== "MANAGER")
      return error(403, "This operation requires a manager.", "FORBIDDEN");
  };
  const wrap = async (run: () => Promise<Response>) => {
    try {
      return await run();
    } catch (e) {
      if (e instanceof AppError)
        return HttpResponse.json(
          {
            ...e.body,
            fieldErrors: e.body.fieldErrors
              ? Object.entries(e.body.fieldErrors).map(([field, message]) => ({
                  field,
                  message,
                }))
              : [],
          },
          {
            status: e.status,
            headers: e.retryAfter ? { "Retry-After": e.retryAfter } : undefined,
          },
        );
      if (e instanceof TypeError) return HttpResponse.error();
      throw e;
    }
  };
  const page = <T>(rows: T[], request: Request) => {
    const q = new URL(request.url).searchParams;
    const index = Math.max(0, Number(q.get("page") ?? 0));
    const size = Math.max(1, Number(q.get("size") ?? 20));
    return {
      items: rows.slice(index * size, (index + 1) * size),
      page: index,
      size,
      totalElements: rows.length,
      totalPages: Math.ceil(rows.length / size),
    };
  };
  const regionForAsset = (id: unknown) =>
    examples.assets.items?.find((x) => x.id === id)?.regionId;
  const fixtureRegionId = examples.file.regionId;
  // Keep the compare-and-update atomic across simultaneous mock PATCH requests.
  let issueWrite: Promise<unknown> = Promise.resolve();
  const serializeIssueWrite = <T>(write: () => Promise<T>): Promise<T> => {
    const result = issueWrite.then(write);
    issueWrite = result.catch(() => undefined);
    return result;
  };
  const listFiles = async (): Promise<FileResource[]> => [
    examples.file,
    ...(await store.entries<FileResource>("mock:direct-file:")).map(
      (entry) => entry.value,
    ),
    ...(await uploads.listFiles()).map((file) => ({
      id: file.id.replace(/^up-/, ""),
      regionId: mockRegions.find((x) => x.code === file.region)?.id,
      category: file.category,
      originalName: file.name,
      sizeBytes: file.sizeBytes,
      sha256: file.expectedSha256,
      status: file.status,
      createdAt: file.createdAt,
    })),
  ];
  const cases: ConnectionCase[] = [
    {
      id: examples.checklist.caseId,
      clientId: "2e594f3a-1bad-4ec5-9627-69ad0be8ecf1",
      status: "OPEN",
      openedAt: "2026-01-10T08:00:00Z",
      dueAt: null,
    },
  ];
  const handlers: RequestHandler[] = [
    ...createStatsHandlers(base, guard),
    ...createAdminHandlers({ base, store, guard, error, page }),
    http.post(`${base}/auth/login`, async ({ request }) => {
      const body = (await request.json()) as {
        username?: string;
        password?: string;
      };
      if (
        !["operator", "manager"].includes(body.username ?? "") ||
        body.password !== body.username
      )
        return error(
          401,
          "Use operator/operator or manager/manager in mock mode.",
          "INVALID_CREDENTIALS",
        );
      const session: MockSession = {
        me: {
          id: crypto.randomUUID(),
          username: body.username,
          role: body.username === "manager" ? "MANAGER" : "OPERATOR",
        },
        csrf: crypto.randomUUID(),
      };
      await store.put("mock:session", session);
      return HttpResponse.json(session.me, {
        headers: {
          "X-CSRF-Token": session.csrf,
          "Set-Cookie": "filegrid_session=mock; Path=/; SameSite=Lax",
        },
      });
    }),
    http.get(`${base}/auth/me`, async ({ request }) => {
      const denied = await guard(request);
      if (denied) return denied;
      const session = (await store.get<MockSession>("mock:session"))!;
      return HttpResponse.json(session.me, {
        headers: { "X-CSRF-Token": session.csrf },
      });
    }),
    http.post(`${base}/auth/logout`, async ({ request }) => {
      const denied = await guard(request, true);
      if (denied) return denied;
      await store.delete("mock:session");
      return new HttpResponse(null, { status: 204 });
    }),
    http.get(
      `${base}/regions`,
      async ({ request }) =>
        (await guard(request)) ?? HttpResponse.json(page(mockRegions, request)),
    ),
    http.get(`${base}/assets`, async ({ request }) => {
      const denied = await guard(request);
      if (denied) return denied;
      const region = new URL(request.url).searchParams.get("regionId");
      return HttpResponse.json(
        page(
          (examples.assets.items ?? []).filter(
            (x) => !region || x.regionId === region,
          ),
          request,
        ),
      );
    }),
    http.get(`${base}/map/features`, async ({ request }) => {
      const denied = await guard(request);
      if (denied) return denied;
      const query = new URL(request.url).searchParams;
      const layer = query.get("layer");
      const region = query.get("regionId");
      if (!["ASSETS", "ISSUES", "OUTAGES"].includes(layer ?? ""))
        return error(422, "Unknown map layer.");
      const featureKind =
        layer === "ASSETS" ? "ASSET" : layer === "ISSUES" ? "ISSUE" : "OUTAGE";
      const features = (examples.map.features ?? []).filter(
        (x) =>
          x.properties?.kind === featureKind &&
          (!region ||
            regionForAsset(x.properties?.assetId ?? x.properties?.id) ===
              region),
      );
      if (layer === "ISSUES") {
        for (const row of await store.entries<MapIssue>("mock:issue:")) {
          const issue = row.value;
          if (region && regionForAsset(issue.assetId) !== region) continue;
          const mapped: GeoJsonFeature = {
            type: "Feature",
            geometry: {
              type: "Point",
              coordinates: issue.location?.coordinates,
            },
            properties: { ...issue, kind: "ISSUE", location: undefined },
          };
          const existing = features.findIndex(
            (x) => x.properties?.id === issue.id,
          );
          if (existing < 0) features.push(mapped);
          else features[existing] = mapped;
        }
      }
      return HttpResponse.json({ type: "FeatureCollection", features });
    }),
    http.post(`${base}/map-issues`, async ({ request }) => {
      const denied = await guard(request, true);
      if (denied) return denied;
      const body = (await request.json()) as MapIssueCreateRequest;
      if (
        !regionForAsset(body.assetId) ||
        body.location?.type !== "Point" ||
        !body.location.coordinates ||
        !["LOW", "MEDIUM", "HIGH", "CRITICAL"].includes(body.severity) ||
        (body.videoOffsetSeconds != null &&
          !Number.isInteger(body.videoOffsetSeconds))
      )
        return error(422, "Invalid issue details.", "VALIDATION");
      const issue: MapIssue = {
        id: crypto.randomUUID(),
        assetId: body.assetId,
        location: body.location,
        severity: body.severity,
        description: body.description,
        status: "OPEN",
        version: 1,
        createdAt: new Date().toISOString(),
      };
      await store.put(`mock:issue:${issue.id}`, issue);
      return HttpResponse.json(issue, { status: 201 });
    }),
    http.patch(`${base}/map-issues/:id/status`, async ({ request, params }) => {
      const body = (await request.json()) as MapIssueStatusUpdateRequest;
      const denied = await guard(request, true, body.status === "RESOLVED");
      if (denied) return denied;
      return serializeIssueWrite(async () => {
        const issue = await store.get<MapIssue>(`mock:issue:${params.id}`);
        if (!issue)
          return error(
            409,
            "Issue version is unavailable or has changed.",
            "VERSION_CONFLICT",
          );
        if (issue.version !== body.version)
          return error(
            409,
            "someone else already took this issue",
            "VERSION_CONFLICT",
          );
        if (!["OPEN", "IN_PROGRESS", "RESOLVED"].includes(body.status))
          return error(422, "Invalid issue status.");
        const updated = {
          ...issue,
          status: body.status,
          version: body.version + 1,
        };
        await store.put(`mock:issue:${params.id}`, updated);
        return HttpResponse.json(updated);
      });
    }),
    http.post(`${base}/files`, async ({ request }) => {
      const denied = await guard(request, true);
      if (denied) return denied;
      const form = await request.formData();
      const file = form.get("file");
      let metadata: FileUploadMetadata;
      try {
        metadata = JSON.parse(
          String(form.get("metadata")),
        ) as FileUploadMetadata;
      } catch {
        return error(422, "Invalid JSON upload metadata.");
      }
      if (
        !(file instanceof File) ||
        !metadata ||
        !["OUTAGE_RECORD", "CONNECTION_DOCUMENT", "DRONE_VIDEO"].includes(
          metadata.category,
        )
      )
        return error(422, "Invalid direct upload.");
      const resource: FileResource = {
        id: crypto.randomUUID(),
        regionId:
          "assetId" in metadata
            ? regionForAsset(metadata.assetId)
            : fixtureRegionId,
        category: metadata.category,
        originalName: file.name,
        sizeBytes: file.size,
        sha256: await digestBlob(file),
        status: "READY",
        createdAt: new Date().toISOString(),
      };
      await store.put(`mock:direct-file:${resource.id}`, resource);
      await store.put(`mock:bytes:${resource.id}`, file);
      return HttpResponse.json(resource, { status: 201 });
    }),
    http.get(`${base}/files/:id/download`, async ({ request, params }) => {
      const denied = await guard(request);
      if (denied) return denied;
      const file = await store.get<Blob>(`mock:bytes:${params.id}`);
      if (file) return new HttpResponse(file);
      const parts = await store.entries<{ number: number; body: Blob }>(
        `part:${params.id}:`,
      );
      if (!parts.length) return error(404, "Mock file content is unavailable.");
      return new HttpResponse(
        new Blob(
          parts
            .map((entry) => entry.value)
            .sort((a, b) => a.number - b.number)
            .map((part) => part.body),
        ),
      );
    }),
    http.get(`${base}/files`, async ({ request }) => {
      const denied = await guard(request);
      if (denied) return denied;
      const q = new URL(request.url).searchParams;
      return HttpResponse.json(
        page(
          (await listFiles()).filter(
            (x) =>
              (!q.get("regionId") || x.regionId === q.get("regionId")) &&
              (!q.get("category") || x.category === q.get("category")) &&
              (!q.get("status") || x.status === q.get("status")),
          ),
          request,
        ),
      );
    }),
    http.get(`${base}/files/:id`, async ({ request, params }) => {
      const denied = await guard(request);
      if (denied) return denied;
      const file = (await listFiles()).find((x) => x.id === params.id);
      return file ? HttpResponse.json(file) : error(404, "File not found.");
    }),
    http.get(`${base}/files/:id/verify`, async ({ request, params }) => {
      const denied = await guard(request);
      if (denied) return denied;
      const file = (await listFiles()).find((x) => x.id === params.id);
      if (!file) return error(404, "File not found.");
      const uploaded = await uploads.getFile(`up-${String(params.id)}`);
      const actual = uploaded?.actualSha256 ?? file.sha256;
      return HttpResponse.json({
        valid: actual === file.sha256,
        expectedSha256: file.sha256,
        actualSha256: actual,
        checkedAt: new Date().toISOString(),
      });
    }),
    http.get(`${base}/connection-cases`, async ({ request }) => {
      const denied = await guard(request);
      if (denied) return denied;
      const region = new URL(request.url).searchParams.get("regionId");
      return HttpResponse.json(
        page(!region || region === fixtureRegionId ? cases : [], request),
      );
    }),
    http.get(
      `${base}/connection-cases/:id/documents`,
      async ({ request, params }) => {
        const denied = await guard(request);
        if (denied) return denied;
        return params.id === examples.checklist.caseId
          ? HttpResponse.json(examples.checklist)
          : error(404, "Case not found.");
      },
    ),
    http.get(
      `${base}/document-types`,
      async ({ request }) =>
        (await guard(request)) ??
        HttpResponse.json(examples.checklist.missingDocumentTypes ?? []),
    ),
    http.post(`${base}/uploads`, async ({ request }) =>
      wrap(async () => {
        const denied = await guard(request, true);
        if (denied) return denied;
        const body = (await request.json()) as UploadSessionCreateRequest;
        if (
          !body.fileName ||
          !Number.isSafeInteger(body.sizeBytes) ||
          body.sizeBytes <= 0 ||
          body.category !== "DRONE_VIDEO" ||
          body.metadata?.category !== "DRONE_VIDEO" ||
          !body.metadata.assetId ||
          !body.metadata.recordedAt
        )
          return error(422, "Invalid upload details.");
        const assetId =
          body.metadata && "assetId" in body.metadata
            ? body.metadata.assetId
            : undefined;
        const regionId = regionForAsset(assetId) ?? fixtureRegionId;
        const region = mockRegions.find((x) => x.id === regionId)
          ?.code as Region;
        const created = await uploads.create(
          {
            category: body.category,
            fileName: body.fileName,
            sizeBytes: body.sizeBytes,
            metadata: { region },
          },
          request.signal,
        );
        return HttpResponse.json(created, { status: 201 });
      }),
    ),
    http.put(
      `${base}/uploads/:id/parts/:partNumber`,
      async ({ request, params }) =>
        wrap(async () => {
          const denied = await guard(request, true);
          if (denied) return denied;
          const body = new Blob([await request.arrayBuffer()]);
          const result = await uploads.putPart(
            String(params.id),
            Number(params.partNumber),
            body,
            request.headers.get("X-Part-SHA256") ?? "",
            request.signal,
          );
          return HttpResponse.json(result);
        }),
    ),
    http.get(`${base}/uploads/:id`, async ({ request, params }) =>
      wrap(
        async () =>
          (await guard(request)) ??
          HttpResponse.json(
            await uploads.getStatus(String(params.id), request.signal),
          ),
      ),
    ),
    http.post(`${base}/uploads/:id/complete`, async ({ request, params }) =>
      wrap(async () => {
        const denied = await guard(request, true);
        if (denied) return denied;
        const body = (await request.json()) as { sha256: string };
        const result = await uploads.complete(
          String(params.id),
          body.sha256,
          request.signal,
        );
        // Expose a contract-compatible UUID file ID; simulator-internal ID is kept on disk.
        return HttpResponse.json(
          { ...result, fileId: result.fileId.replace(/^up-/, "") },
          { status: 202 },
        );
      }),
    ),
    http.delete(`${base}/uploads/:id`, async ({ request, params }) =>
      wrap(async () => {
        const denied = await guard(request, true);
        if (denied) return denied;
        await uploads.cancel(String(params.id), request.signal);
        return new HttpResponse(null, { status: 204 });
      }),
    ),
  ];
  // Do not let an omitted API handler silently reach a real server in mock mode.
  handlers.push(
    http.all(`${base}/*`, () =>
      error(
        501,
        "This contract operation has no mock handler.",
        "MOCK_NOT_IMPLEMENTED",
      ),
    ),
  );
  return {
    handlers,
    store,
    uploads,
    reset: async () => {
      for (const prefix of ["mock:", "file:", "upload:", "part:"])
        for (const entry of await store.entries(prefix))
          await store.delete(entry.key);
    },
  };
}
export const mockApi = createMockApi();
export const handlers = mockApi.handlers;
