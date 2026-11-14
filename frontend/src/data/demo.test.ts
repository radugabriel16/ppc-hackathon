import { beforeEach, describe, expect, it, vi } from "vitest";
import { LocalDemoSource } from "./demo";
import { AppError } from "./errors";
import { REGIONS, REGION_INFO } from "./models";

let source: LocalDemoSource;
beforeEach(() => {
  source = new LocalDemoSource();
  const values = new Map<string, string>();
  vi.stubGlobal("sessionStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  });
});
describe("LocalDemoSource integration boundary", () => {
  it("requires authentication and enforces manager-only resolution", async () => {
    const map = await source.getMap("MUNTENIA");
    const issue = map.issueList.find((x) => x.status === "OPEN")!;
    await expect(
      source.updateIssue({
        id: issue.id,
        version: issue.version!,
        status: "IN_PROGRESS",
      }),
    ).rejects.toMatchObject({ status: 401 });
    await source.login({ name: "Operator", role: "OPERATOR" });
    await expect(
      source.updateIssue({
        id: issue.id,
        version: issue.version!,
        status: "RESOLVED",
      }),
    ).rejects.toMatchObject({ status: 403 });
    await source.login({ name: "Manager", role: "MANAGER" });
    expect(
      await source.updateIssue({
        id: issue.id,
        version: issue.version!,
        status: "RESOLVED",
      }),
    ).toMatchObject({ status: "RESOLVED", version: 2 });
  });
  it("simulates 409 with the required message and returns authoritative data on refetch", async () => {
    await source.login({ name: "Operator", role: "OPERATOR" });
    const issue = (await source.getMap("BANAT")).issueList.find(
      (x) => x.status === "OPEN",
    )!;
    await expect(
      source.updateIssue({
        id: issue.id,
        version: issue.version!,
        status: "IN_PROGRESS",
        simulateConflict: true,
      }),
    ).rejects.toMatchObject({
      status: 409,
      body: {
        message: "someone else already took this issue",
        requestId: expect.any(String),
      },
    });
    const refreshed = (await source.getMap("BANAT")).issueList.find(
      (x) => x.id === issue.id,
    )!;
    expect(refreshed).toMatchObject({
      status: "IN_PROGRESS",
      version: issue.version! + 1,
    });
    expect(issue.status).toBe("OPEN"); // A previous query result cannot be mutated by the source.
    await expect(
      source.updateIssue({
        id: issue.id,
        version: issue.version!,
        status: "OPEN",
      }),
    ).rejects.toBeInstanceOf(AppError);
  });
  it("validates issue details and preserves optional video evidence", async () => {
    await source.login({ name: "Operator", role: "OPERATOR" });
    const asset = (await source.getMap("DOBROGEA")).assetList[0];
    await expect(
      source.createIssue({
        assetId: asset.id,
        description: "short",
        severity: "LOW",
        offsetSeconds: -1,
      }),
    ).rejects.toMatchObject({
      body: {
        fieldErrors: {
          description: expect.any(String),
          offsetSeconds: expect.any(String),
          videoId: expect.any(String),
        },
      },
    });
    const created = await source.createIssue({
      assetId: asset.id,
      description: "Visible thermal damage",
      severity: "HIGH",
      videoId: "F-DRONE-1",
      offsetSeconds: 4.5,
    });
    expect(created).toMatchObject({
      region: "DOBROGEA",
      assetId: asset.id,
      coordinates: asset.coordinates,
      status: "OPEN",
      version: 1,
      videoId: "F-DRONE-1",
      offsetSeconds: 4.5,
    });
  });
  it.each(REGIONS)(
    "returns GeoJSON in [longitude, latitude], with line geometry and no client data (%s)",
    async (region) => {
      const map = await source.getMap(region);
      const bbox = REGION_INFO[region].bbox;
      expect(map.assets.type).toBe("FeatureCollection");
      expect(map.issues.type).toBe("FeatureCollection");
      expect(map.outages.type).toBe("FeatureCollection");
      expect(
        map.assets.features.some(
          (x) =>
            x.properties?.type === "LINE_SEGMENT" &&
            x.geometry.type === "LineString",
        ),
      ).toBe(true);
      for (const asset of map.assetList) {
        expect(asset.coordinates[0]).toBeGreaterThan(bbox[0]);
        expect(asset.coordinates[0]).toBeLessThan(bbox[2]);
        expect(asset.coordinates[1]).toBeGreaterThan(bbox[1]);
        expect(asset.coordinates[1]).toBeLessThan(bbox[3]);
      }
      const serialized = JSON.stringify(map);
      expect(serialized).not.toMatch(/email|phone|customer|address/i);
    },
  );
  it("filters and paginates files using the UI model", async () => {
    vi.spyOn(source.uploads, "listFiles").mockResolvedValue([]);
    const page = await source.getFiles({
      region: "MUNTENIA",
      search: "drone",
      category: "DRONE_VIDEO",
      page: 1,
      size: 2,
    });
    expect(page).toMatchObject({
      page: 1,
      size: 2,
      totalElements: 6,
      totalPages: 3,
    });
    expect(page.items).toHaveLength(2);
    expect(
      page.items.every(
        (x) => x.region === "MUNTENIA" && x.category === "DRONE_VIDEO",
      ),
    ).toBe(true);
    const corrupt = await source.getFiles({
      region: "BANAT",
      search: "",
      status: "CORRUPT",
      page: 0,
      size: 20,
    });
    expect(
      corrupt.items.every((x) => x.expectedSha256 !== x.actualSha256),
    ).toBe(true);
  });
  it("sorts cases by dueAt before pagination, with consistent completed checklists", async () => {
    const first = await source.getCases({
      region: "BANAT",
      search: "",
      page: 0,
      size: 6,
    });
    const next = await source.getCases({
      region: "BANAT",
      search: "",
      page: 1,
      size: 6,
    });
    const rows = [...first.items, ...next.items];
    expect(rows.map((x) => x.dueAt)).toEqual(rows.map((x) => x.dueAt).sort());
    expect(
      rows
        .filter((x) => x.status === "COMPLETE")
        .every((x) => x.documents.every((d) => d.received)),
    ).toBe(true);
    expect(rows.some((x) => x.documents.some((d) => !d.received))).toBe(true);
  });
});
