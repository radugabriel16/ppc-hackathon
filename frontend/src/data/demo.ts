import type { FeatureCollection, LineString, Point } from "geojson";
import {
  FakeUploadTransport,
  IndexedDemoStore,
} from "../upload/fake-transport";
import { AppError } from "./errors";
import { DemoAdministration } from "./demo-administration";
import { CATEGORIES, REGIONS, REGION_INFO } from "./models";
import type {
  Asset,
  CaseFilter,
  CaseRecord,
  CreateIssue,
  FileFilter,
  FileRecord,
  Issue,
  IssueStatus,
  MapData,
  Page,
  Region,
  Role,
  Session,
  SimulatorStart,
  SimulatorBackfill,
  StorageBenchmark,
  StorageRecommendation,
  MeterConsumption,
  MeterReadingFilter,
  MeterReadingWindow,
  RawMeterReading,
  ReadingMeter,
  OutageHotspot,
  ForecastPoint,
} from "./models";
import type { DataSource } from "./source";
import { mockRegions } from "../mocks/fixtures";
import { geographicAreas } from "./api-mapping";

const delay = () => new Promise((resolve) => setTimeout(resolve, 180));
const paged = <T>(rows: T[], page: number, size: number): Page<T> => ({
  items: rows.slice(page * size, (page + 1) * size),
  page,
  size,
  totalElements: rows.length,
  totalPages: Math.ceil(rows.length / size),
});
const demoHash = (seed: number) =>
  Array.from({ length: 64 }, (_, i) =>
    ((seed * 7 + i * 3) % 16).toString(16),
  ).join("");
export class LocalDemoSource implements DataSource {
  readonly kind = "demo" as const;
  readonly uploads = new FakeUploadTransport({ store: new IndexedDemoStore() });
  async getGeography() {
    this.requireSession();
    return geographicAreas(mockRegions);
  }
  private session: Session | null = null;
  private readonly administration = new DemoAdministration(() => {
    if (this.requireSession().user.role !== "MANAGER")
      throw new AppError(403, {
        code: "FORBIDDEN",
        message: "This operation requires a manager.",
        requestId: "demo-admin",
      });
  });
  getPolicies() {
    return this.administration.getPolicies();
  }
  reloadPolicies() {
    return this.administration.reloadPolicies();
  }
  getSimulatorStatus() {
    return this.administration.getSimulatorStatus();
  }
  startSimulator(input: SimulatorStart) {
    return this.administration.startSimulator(input);
  }
  stopSimulator() {
    return this.administration.stopSimulator();
  }
  backfillSimulator(input: SimulatorBackfill) {
    return this.administration.backfillSimulator(input);
  }
  getScenarioRuns(page: number, size: number) {
    return this.administration.getScenarioRuns(page, size);
  }
  getRecentAlerts() {
    return this.administration.getRecentAlerts();
  }
  // No benchmark measurements exist in the isolated local source. Realistic
  // synthetic statistics are served only by the explicitly selected MSW mode.
  async getStorageBenchmark(): Promise<StorageBenchmark[]> {
    return [];
  }
  async getStorageRecommendations(): Promise<StorageRecommendation[]> {
    return [];
  }
  async getMeterConsumption(): Promise<MeterConsumption[]> {
    return [];
  }
  async getReadingMeters(): Promise<ReadingMeter[]> {
    this.requireSession();
    return [];
  }
  async getMeterReadings(filter: MeterReadingFilter): Promise<Page<RawMeterReading>> {
    this.requireSession();
    return paged([], filter.page, filter.size);
  }
  async getMeterReadingWindow(): Promise<MeterReadingWindow> {
    this.requireSession();
    return { readings: [], from: null, to: null };
  }
  async getOutageHotspots(): Promise<OutageHotspot[]> {
    return [];
  }
  async getForecast(): Promise<ForecastPoint[]> {
    return [];
  }
  private assets: Asset[] = REGIONS.flatMap((region) => {
    const [lon, lat] = REGION_INFO[region].center;
    return Array.from(
      { length: 12 },
      (_, i): Asset => ({
        id: `${region.slice(0, 3)}-${String(i + 1).padStart(3, "0")}`,
        name: `${REGION_INFO[region].name} ${i % 3 === 0 ? "substation" : i % 3 === 1 ? "transformer" : "feeder"} ${i + 1}`,
        type:
          i % 3 === 0
            ? "SUBSTATION"
            : i % 3 === 1
              ? "TRANSFORMER"
              : "LINE_SEGMENT",
        region,
        coordinates: [
          lon + ((i % 4) - 1.5) * 0.17,
          lat + (Math.floor(i / 4) - 1) * 0.14,
        ],
      }),
    );
  });
  private issues: (Issue & { version: number })[] = this.assets
    .filter((_, i) => i % 2 === 0)
    .map((asset, i) => ({
      id: `ISS-${100 + i}`,
      assetId: asset.id,
      region: asset.region,
      coordinates: asset.coordinates,
      severity: i % 3 === 0 ? "HIGH" : "MEDIUM",
      status: i % 3 === 0 ? "OPEN" : i % 3 === 1 ? "IN_PROGRESS" : "RESOLVED",
      version: 1,
      description: [
        "Thermal anomaly detected during inspection",
        "Vegetation clearance required",
        "Insulation inspection completed",
      ][i % 3],
    }));
  private files: FileRecord[] = REGIONS.flatMap((region, r) =>
    Array.from({ length: 24 }, (_, i) => ({
      id: `F-${r + 1}${String(i + 1).padStart(3, "0")}`,
      name: `${["meter-batch", "outage-log", "connection-pack", "drone-inspection"][i % 4]}-${String(i + 1).padStart(3, "0")}.${["csv", "json", "pdf", "mp4"][i % 4]}`,
      category: CATEGORIES[i % 4],
      status: (i % 11 === 0
        ? "CORRUPT"
        : i % 9 === 0
          ? "FAILED"
          : i % 7 === 0
            ? "VERIFYING"
            : "READY") as FileRecord["status"],
      region,
      sizeBytes: (i + 1) * (i % 4 === 3 ? 15000000 : 58421),
      createdAt: new Date(
        Date.UTC(2026, 10, 14, 12 - Math.floor(i / 3), i % 60),
      ).toISOString(),
      expectedSha256: demoHash(i + r),
      actualSha256: i % 11 === 0 ? demoHash(i + r + 1) : demoHash(i + r),
    })),
  );
  private cases: (CaseRecord & { dueAt: string })[] = REGIONS.flatMap(
    (region, r) =>
      Array.from({ length: 14 }, (_, i) => ({
        id: `CAS-${r + 1}${String(i + 1).padStart(3, "0")}`,
        title:
          [
            "New grid connection",
            "Substation maintenance",
            "Feeder extension",
            "Incident investigation",
          ][i % 4] + ` · ${REGION_INFO[region].name} ${i + 1}`,
        region,
        dueAt: new Date(Date.UTC(2026, 10, 12 + i, 15)).toISOString(),
        status: (i % 5 === 0
          ? "COMPLETE"
          : i % 3 === 0
            ? "REVIEW"
            : "OPEN") as CaseRecord["status"],
        documents: [
          { name: "Connection application", received: true },
          {
            name: "Technical assessment",
            received: i % 5 === 0 || i % 3 === 0,
          },
          {
            name: "Site inspection report",
            received: i % 5 === 0 || i % 2 === 0,
          },
          { name: "Approval document", received: i % 5 === 0 },
        ],
      })),
  );
  async getSession() {
    if (!this.session) {
      try {
        const stored = sessionStorage.getItem("filegrid.demo-session");
        if (stored) this.session = JSON.parse(stored) as Session;
      } catch {
        /* A blocked session store does not prevent demo login. */
      }
    }
    return this.session;
  }
  async login(input: { name: string; role: Role }) {
    await delay();
    this.session = {
      user: { name: input.name.trim() || "Alex Morgan", role: input.role },
      csrfToken: crypto.randomUUID(),
    };
    try {
      sessionStorage.setItem(
        "filegrid.demo-session",
        JSON.stringify(this.session),
      );
    } catch {
      /* Session stays in memory. */
    }
    return this.session;
  }
  async logout() {
    this.session = null;
    try {
      sessionStorage.removeItem("filegrid.demo-session");
    } catch {
      /* In-memory sessions can still be cleared. */
    }
  }
  private requireSession() {
    if (!this.session)
      throw new AppError(401, {
        code: "UNAUTHENTICATED",
        message: "Please sign in.",
        requestId: "demo-auth",
      });
    return this.session;
  }
  async getMap(region: Region): Promise<MapData> {
    await delay();
    const assetList = this.assets.filter((x) => x.region === region);
    const issueList = this.issues.filter((x) => x.region === region);
    const assets: FeatureCollection<Point | LineString> = {
      type: "FeatureCollection",
      features: assetList.map((x) => ({
        type: "Feature",
        id: x.id,
        properties: { id: x.id, name: x.name, type: x.type },
        geometry:
          x.type === "LINE_SEGMENT"
            ? {
                type: "LineString",
                coordinates: [
                  x.coordinates,
                  [x.coordinates[0] + 0.11, x.coordinates[1] + 0.07],
                ],
              }
            : { type: "Point", coordinates: x.coordinates },
      })),
    };
    const issues: FeatureCollection<Point> = {
      type: "FeatureCollection",
      features: issueList.map((x) => ({
        type: "Feature",
        id: x.id,
        properties: {
          id: x.id,
          assetId: x.assetId,
          description: x.description,
          status: x.status,
          type: x.type ?? "OUTAGE_REPORT",
          severity: x.severity,
        },
        geometry: { type: "Point", coordinates: x.coordinates },
      })),
    };
    const center = REGION_INFO[region].center;
    const outages: FeatureCollection<Point> = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {
            id: `OUT-${region.slice(0, 3)}-01`,
            name: "Planned feeder maintenance",
            affectedAssets: 3,
          },
          geometry: {
            type: "Point",
            coordinates: [center[0] + 0.15, center[1] + 0.09],
          },
        },
      ],
    };
    return structuredClone({ assets, issues, outages, assetList, issueList });
  }
  async createIssue(input: CreateIssue) {
    this.requireSession();
    await delay();
    const asset = this.assets.find((x) => x.id === input.assetId);
    const fields: Record<string, string> = {};
    if (!asset) fields.assetId = "Choose an asset.";
    if (input.description.trim().length < 8)
      fields.description = "Use at least 8 characters.";
    if (
      input.offsetSeconds !== undefined &&
      (!Number.isFinite(input.offsetSeconds) || input.offsetSeconds < 0)
    )
      fields.offsetSeconds = "Offset must be a non-negative number.";
    if (input.offsetSeconds !== undefined && !input.videoId)
      fields.videoId = "A video ID is required for an offset.";
    if (Object.keys(fields).length)
      throw new AppError(400, {
        code: "VALIDATION",
        message: "Check the issue details.",
        fieldErrors: fields,
        requestId: "demo-validation",
      });
    const issue: Issue & { version: number } = {
      ...input,
      description: input.description.trim(),
      id: `ISS-${crypto.randomUUID().slice(0, 6)}`,
      region: asset!.region,
      coordinates: input.coordinates ?? asset!.coordinates,
      status: "OPEN",
      version: 1,
    };
    this.issues.push(issue);
    return structuredClone(issue);
  }
  async updateIssue(input: {
    id: string;
    status: IssueStatus;
    version: number;
    simulateConflict?: boolean;
  }) {
    const session = this.requireSession();
    await delay();
    if (input.status === "RESOLVED" && session.user.role !== "MANAGER")
      throw new AppError(403, {
        code: "FORBIDDEN",
        message: "Only managers can resolve issues.",
        requestId: "demo-role",
      });
    const issue = this.issues.find((x) => x.id === input.id);
    if (!issue)
      throw new AppError(404, {
        code: "NOT_FOUND",
        message: "Issue not found.",
        requestId: "demo-missing",
      });
    if (input.simulateConflict) {
      issue.version++;
      issue.status = "IN_PROGRESS";
    }
    if (issue.version !== input.version)
      throw new AppError(409, {
        code: "VERSION_CONFLICT",
        message: "someone else already took this issue",
        requestId: `demo-conflict-${issue.id}`,
      });
    issue.status = input.status;
    issue.version++;
    return structuredClone(issue);
  }
  async getFiles(filter: FileFilter) {
    await delay();
    const uploaded = await this.uploads.listFiles();
    const files = [...uploaded, ...this.files].filter(
      (x) =>
        x.region === filter.region &&
        (!filter.category || x.category === filter.category) &&
        (!filter.status || x.status === filter.status) &&
        `${x.name} ${x.id}`.toLowerCase().includes(filter.search.toLowerCase()),
    );
    return paged(
      files.sort((a, b) => b.createdAt.localeCompare(a.createdAt)),
      filter.page,
      filter.size,
    );
  }
  async getFile(id: string) {
    await delay();
    const file =
      this.files.find((x) => x.id === id) ?? (await this.uploads.getFile(id));
    if (!file)
      throw new AppError(404, {
        code: "NOT_FOUND",
        message: "File not found.",
        requestId: "demo-file",
      });
    return file;
  }
  async getCases(filter: CaseFilter) {
    await delay();
    return paged(
      this.cases
        .filter(
          (x) =>
            (!filter.region || x.region === filter.region) &&
            (!filter.clientId || x.customerId === filter.clientId) &&
            (!filter.caseId || x.id === filter.caseId) &&
            (!filter.missingOnly || x.documents.some((d) => !d.received)) &&
            (!filter.status || filter.status === x.status) &&
            `${x.title} ${x.id}`
              .toLowerCase()
              .includes(filter.search.toLowerCase()),
        )
        .sort((a, b) => a.dueAt.localeCompare(b.dueAt)),
      filter.page,
      filter.size,
    );
  }
  async getStatistics(region: Region) {
    const files = [...this.files, ...(await this.uploads.listFiles())].filter(
      (x) => x.region === region,
    );
    return {
      files: files.length,
      ready: files.filter((x) => x.status === "READY").length,
      corrupt: files.filter((x) => x.status === "CORRUPT").length,
      bytes: files.reduce((n, x) => n + x.sizeBytes, 0),
      openIssues: this.issues.filter(
        (x) => x.region === region && x.status !== "RESOLVED",
      ).length,
      overdueCases: this.cases.filter(
        (x) =>
          x.region === region &&
          x.status !== "COMPLETE" &&
          Date.parse(x.dueAt) < Date.now(),
      ).length,
    };
  }
}
