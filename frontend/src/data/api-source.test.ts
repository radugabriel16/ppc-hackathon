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
import { examples, mockRegions } from "../mocks/fixtures";
import { MemoryDemoStore } from "../upload/fake-transport";
import { digestBlob } from "../upload/hash";
import { ApiConnection } from "./api-client";

const mock = createMockApi({
  store: new MemoryDemoStore(),
  failureRate: 0,
  verifyMs: 0,
});
const server = setupServer(...mock.handlers);
const base = "http://127.0.0.1/api/v1";
let source: ApiSource;
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());
afterEach(() => server.resetHandlers());
beforeEach(async () => {
  await mock.reset();
  source = new ApiSource(base, "mock");
  await source.login({
    name: "operator",
    password: "operator",
    role: "MANAGER",
  });
});
describe("generated client → ApiSource → MSW contract examples", () => {
  it("uses username/password and the server role; restores session and token after reload", async () => {
    expect(await source.getSession()).toMatchObject({
      user: { name: "operator", role: "OPERATOR" },
      csrfToken: expect.any(String),
    });
    const reloaded = new ApiSource(base, "mock");
    expect(await reloaded.getSession()).toMatchObject({
      user: { role: "OPERATOR" },
    });
    await reloaded.logout();
    expect(await source.getSession()).toBeNull();
  });
  it("maps UUID region IDs, normalizes asset properties and leaves missing issue versions unavailable", async () => {
    const map = await source.getMap("MUNTENIA");
    expect(map.assetList).toEqual([
      expect.objectContaining({
        id: examples.assets.items![0].id,
        name: "Muntenia Substation 1",
        type: "SUBSTATION",
        region: "MUNTENIA",
        coordinates: [26.1025, 44.4268],
      }),
    ]);
    expect(map.issues.features[0].geometry.coordinates).toEqual([26.11, 44.43]);
    expect(map.issueList[0]).toMatchObject({
      status: "OPEN",
      severity: "HIGH",
      version: null,
    });
    expect((await source.getMap("BANAT")).assetList).toEqual([]);
  });
  it("maps file pages and calls the real verification operation for expected/actual hashes", async () => {
    const files = await source.getFiles({
      region: "MUNTENIA",
      page: 0,
      size: 10,
      search: "outage",
      category: "OUTAGE_RECORD",
    });
    expect(files).toMatchObject({
      totalElements: 1,
      totalPages: 1,
      page: 0,
      size: 10,
    });
    expect(files.items[0]).toMatchObject({
      id: examples.file.id,
      name: examples.file.originalName,
      actualSha256: "",
    });
    const report = await source.getFile(examples.file.id!);
    expect(report).toMatchObject({
      expectedSha256: examples.file.sha256,
      actualSha256: examples.file.sha256,
      status: "READY",
    });
    server.use(
      http.get(`${base}/files/:id/verify`, () =>
        HttpResponse.json({
          valid: false,
          expectedSha256: "a".repeat(64),
          actualSha256: "b".repeat(64),
        }),
      ),
    );
    expect(await source.getFile(examples.file.id!)).toMatchObject({
      status: "CORRUPT",
      actualSha256: "b".repeat(64),
    });
  });
  it("maps nullable case deadlines and the supplied received/missing document checklist", async () => {
    const cases = await source.getCases({
      region: "MUNTENIA",
      search: "",
      page: 0,
      size: 6,
    });
    expect(cases.items[0]).toMatchObject({
      id: examples.checklist.caseId,
      dueAt: null,
      status: "OPEN",
    });
    expect(cases.items[0].documents.filter((x) => x.received)).toHaveLength(1);
    expect(
      cases.items[0].documents.filter((x) => !x.received).map((x) => x.name),
    ).toEqual(examples.checklist.missingDocumentTypes!.map((x) => x.name));
  });
  it("aggregates typed operations for UI statistics rather than inventing opaque stats fields", async () => {
    expect(await source.getStatistics("MUNTENIA")).toEqual({
      files: 1,
      ready: 1,
      corrupt: 0,
      bytes: examples.file.sizeBytes,
      openIssues: 1,
      overdueCases: 0,
    });
  });
  it("uses issue location and whole-second video fields; forwards optimistic version and receives 409", async () => {
    const map = await source.getMap("MUNTENIA");
    const created = await source.createIssue({
      assetId: map.assetList[0].id,
      severity: "CRITICAL",
      description: "Insulation failure",
      videoId: "11111111-1111-4111-8111-111111111111",
      offsetSeconds: 12,
    });
    expect(created).toMatchObject({
      severity: "CRITICAL",
      version: 1,
      videoId: expect.any(String),
      offsetSeconds: 12,
    });
    await source.getMap("MUNTENIA");
    expect(
      await source.updateIssue({
        id: created.id,
        version: 1,
        status: "IN_PROGRESS",
      }),
    ).toMatchObject({ version: 2, status: "IN_PROGRESS" });
    await expect(
      source.updateIssue({ id: created.id, version: 1, status: "IN_PROGRESS" }),
    ).rejects.toMatchObject({
      status: 409,
      body: {
        code: "VERSION_CONFLICT",
        requestId: expect.stringContaining("mock-"),
      },
    });
    await expect(
      source.updateIssue({ id: created.id, version: 2, status: "RESOLVED" }),
    ).rejects.toMatchObject({ status: 403 });
    await expect(
      source.createIssue({
        assetId: map.assetList[0].id,
        severity: "LOW",
        description: "Inspection required",
        offsetSeconds: 1.5,
      }),
    ).rejects.toMatchObject({ status: 422 });
  });
  it("serializes simultaneous version updates so only one wins", async () => {
    const map = await source.getMap("MUNTENIA");
    const created = await source.createIssue({
      assetId: map.assetList[0].id,
      severity: "HIGH",
      description: "Investigate conductor",
    });
    await source.getMap("MUNTENIA");
    const results = await Promise.allSettled([
      source.updateIssue({ id: created.id, version: 1, status: "IN_PROGRESS" }),
      source.updateIssue({ id: created.id, version: 1, status: "IN_PROGRESS" }),
    ]);
    expect(results.filter((x) => x.status === "fulfilled")).toHaveLength(1);
    expect(results.find((x) => x.status === "rejected")).toMatchObject({
      reason: { status: 409 },
    });
  });
  it("sends raw bytes and CSRF/hash headers, supports status and idempotent parts, and completes to a UUID file", async () => {
    let requestSeen: Request | undefined;
    server.events.on("request:start", ({ request }) => {
      if (request.method === "PUT") requestSeen = request.clone();
    });
    const signal = new AbortController().signal;
    const blob = new Blob(["raw binary\u0000payload"]);
    const sha = await digestBlob(blob);
    const session = await source.uploads.create(
      {
        category: "DRONE_VIDEO",
        fileName: "sample.mp4",
        sizeBytes: blob.size,
        metadata: { region: "MUNTENIA" },
      },
      signal,
    );
    expect(session.chunkSize).toBe(examples.upload.chunkSize);
    expect(session.totalParts).toBe(1);
    await source.uploads.putPart(session.uploadId, 1, blob, sha, signal);
    expect(requestSeen?.credentials).toBe("include");
    expect(requestSeen?.headers.get("X-CSRF-Token")).toBeTruthy();
    expect(requestSeen?.headers.get("X-Part-SHA256")).toBe(sha);
    expect(requestSeen?.headers.get("Content-Type")).toBe(
      "application/octet-stream",
    );
    expect(await requestSeen!.text()).toBe(await blob.text());
    await source.uploads.putPart(session.uploadId, 1, blob, sha, signal);
    expect(
      (await source.uploads.getStatus(session.uploadId, signal)).receivedParts,
    ).toEqual([1]);
    const completed = await source.uploads.complete(
      session.uploadId,
      sha,
      signal,
    );
    expect(completed.fileId).toMatch(/^[0-9a-f-]{36}$/);
    expect(completed.status).toBe("VERIFYING");
    expect((await source.getFile(completed.fileId)).status).toBe("READY");
    await source.uploads.cancel(session.uploadId, signal);
    await source.uploads.cancel(session.uploadId, signal);
    server.events.removeAllListeners("request:start");
  });
  it("preserves Retry-After and 422 errors across the generated upload transport", async () => {
    const signal = new AbortController().signal;
    const session = await source.uploads.create(
      {
        category: "DRONE_VIDEO",
        fileName: "test",
        sizeBytes: 3,
        metadata: { region: "MUNTENIA" },
      },
      signal,
    );
    await expect(
      source.uploads.putPart(
        session.uploadId,
        1,
        new Blob(["abc"]),
        "0".repeat(64),
        signal,
      ),
    ).rejects.toMatchObject({ status: 422, body: { code: "HASH_MISMATCH" } });
    server.use(
      http.put(`${base}/uploads/:id/parts/:partNumber`, () =>
        HttpResponse.json(
          { code: "BUSY", message: "Back off", requestId: "req-busy" },
          { status: 429, headers: { "Retry-After": "3" } },
        ),
      ),
    );
    await expect(
      source.uploads.putPart(
        session.uploadId,
        1,
        new Blob(["abc"]),
        "0".repeat(64),
        signal,
      ),
    ).rejects.toMatchObject({
      status: 429,
      retryAfter: "3",
      body: { requestId: "req-busy" },
    });
  });
  it("never falls back to demo data on HTTP or network errors in api mode", async () => {
    source = new ApiSource(base, "api");
    server.use(
      http.get(`${base}/auth/me`, () =>
        HttpResponse.json(
          {
            code: "DOWN",
            message: "Backend unavailable",
            requestId: "req-down",
          },
          { status: 503 },
        ),
      ),
    );
    await expect(source.getSession()).rejects.toMatchObject({
      status: 503,
      body: { message: "Backend unavailable", requestId: "req-down" },
    });
    server.use(http.get(`${base}/auth/me`, () => HttpResponse.error()));
    await expect(source.getSession()).rejects.toBeInstanceOf(TypeError);
  });
  it("refuses mutations when the auth response provides no CSRF token", async () => {
    server.use(
      http.post(`${base}/auth/login`, () =>
        HttpResponse.json({ username: "operator", role: "OPERATOR" }),
      ),
    );
    const unextended = new ApiSource(base, "api");
    expect(
      (
        await unextended.login({
          name: "operator",
          role: "OPERATOR",
          password: "operator",
        })
      ).csrfToken,
    ).toBe("");
    await expect(unextended.logout()).rejects.toMatchObject({
      body: {
        code: "CONTRACT_MISMATCH",
        message: expect.stringContaining("CSRF"),
      },
    });
  });
  it("flattens fieldErrors arrays and preserves response request-ID headers", async () => {
    const connection = new ApiConnection(base);
    const response = new Response(null, {
      status: 422,
      headers: { "X-Request-ID": "header-request" },
    });
    await expect(
      connection.read(
        Promise.resolve({
          response,
          error: {
            code: "VALIDATION",
            message: "Check fields",
            fieldErrors: [{ field: "description", message: "Required" }],
          },
        }),
      ),
    ).rejects.toMatchObject({
      body: {
        fieldErrors: { description: "Required" },
        requestId: "header-request",
      },
    });
  });
  it("loads all API pages before applying UI search and pagination", async () => {
    const regionId = mockRegions[0].id;
    server.use(
      http.get(`${base}/files`, ({ request }) => {
        expect(new URL(request.url).searchParams.get("regionId")).toBe(
          regionId,
        );
        const page = Number(new URL(request.url).searchParams.get("page"));
        return HttpResponse.json({
          items: [
            {
              ...examples.file,
              id: `file-${page}`,
              originalName: `wanted-${page}.json`,
            },
          ],
          page,
          size: 1,
          totalElements: 3,
          totalPages: 3,
        });
      }),
    );
    expect(
      await source.getFiles({
        region: "MUNTENIA",
        search: "wanted",
        page: 1,
        size: 2,
      }),
    ).toMatchObject({
      totalElements: 3,
      totalPages: 2,
      items: [expect.objectContaining({ id: "file-2" })],
    });
  });
});
