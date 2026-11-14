import * as sdk from "../api/gen/sdk.gen";
import type {
  PageMeta,
  Region as ApiRegion,
  FileResource,
  ConnectionCase,
} from "../api/gen/types.gen";
import { ApiConnection, contractError, requireValue } from "./api-client";
import { ApiUploadTransport } from "./api-upload";
import {
  storageBenchmark,
  storageRecommendations,
  meterConsumption,
  outageHotspots,
  forecast,
} from "./stats-mapping";
import {
  policyRows,
  recentAlert,
  scenarioRun,
  simulatorState,
} from "./admin-mapping";
import {
  assetList,
  fileRecord,
  issueRecord,
  mapCollection,
  geographicAreas,
  coordinate,
} from "./api-mapping";
import { AppError } from "./errors";
import type {
  CaseFilter,
  CaseRecord,
  CreateIssue,
  FileFilter,
  IssueStatus,
  LoginInput,
  MapData,
  Page,
  Region,
  Statistics,
  SimulatorStart,
  SimulatorBackfill,
  ScenarioRun,
  GeographicArea,
  IssueFilter,
  ForecastRunCreate,
  MeterMarker,
} from "./models";
import type { DataSource } from "./source";

export class ApiSource implements DataSource {
  readonly uploads;
  readonly connection: ApiConnection;
  get uploadScope() {
    return `${this.kind}:${this.client.getConfig().baseUrl}`;
  }
  private regions?: Promise<ApiRegion[]>;
  private maps = new Map<Region, MapData>();
  constructor(
    baseUrl = "/api/v1",
    readonly kind: "api" | "mock" = "api",
  ) {
    this.connection = new ApiConnection(baseUrl);
    this.uploads = new ApiUploadTransport(this.connection);
  }
  private get client() {
    return this.connection.client;
  }
  getDocumentTypes() {
    return this.connection.read(sdk.getDocumentTypes({ client: this.client }));
  }
  downloadFile(id: string) {
    return this.connection.read(
      sdk.getFilesIdDownload({
        client: this.client,
        path: { id },
        parseAs: "blob",
      }),
    );
  }
  async getStorageBenchmark() {
    return storageBenchmark(
      await this.connection.read(
        sdk.getStatsStorageBenchmark({ client: this.client }),
      ),
    );
  }
  async getStorageRecommendations() {
    return storageRecommendations(
      await this.connection.read(
        sdk.getStatsRecommendations({ client: this.client }),
      ),
    );
  }
  async getMeterConsumption(region: Region, subregionId?: string) {
    return meterConsumption(
      await this.connection.read(
        sdk.getStatsMeters({
          client: this.client,
          query: {
            regionId: await this.regionId(region),
            subregionId,
            size: 100,
          },
        }),
      ),
      region,
    );
  }
  async getOutageHotspots(region: Region, subregionId?: string) {
    return outageHotspots(
      await this.connection.read(
        sdk.getStatsOutagesHotspots({
          client: this.client,
          query: {
            regionId: await this.regionId(region),
            subregionId,
            size: 100,
          },
        }),
      ),
      region,
    );
  }
  async getForecast(region: Region, subregionId?: string) {
    const items = [];
    let page = 0;
    let totalPages = 1;
    do {
      const result = await this.connection.read(
        sdk.getStatsForecast({
          client: this.client,
          query: {
            page,
            size: 100,
            regionId: await this.regionId(region),
            subregionId,
          },
        }),
      );
      items.push(...result.items);
      totalPages = result.totalPages ?? 1;
      page += 1;
    } while (page < totalPages);
    return forecast({ items }, region);
  }
  async getPolicies() {
    return policyRows(
      await this.connection.read(sdk.getAdminPolicies({ client: this.client })),
    );
  }
  async reloadPolicies() {
    return policyRows(
      await this.connection.read(
        sdk.createAdminPoliciesReload({
          client: this.client,
          headers: this.connection.mutationHeaders(),
        }),
      ),
    );
  }
  async getSimulatorStatus() {
    return simulatorState(
      await this.connection.read(
        sdk.getAdminSimulatorStatus({ client: this.client }),
      ),
    );
  }
  async startSimulator(input: SimulatorStart) {
    return simulatorState(
      await this.connection.read(
        sdk.createAdminSimulatorStart({
          client: this.client,
          headers: this.connection.mutationHeaders(),
          body: input,
        }),
      ),
    );
  }
  async stopSimulator() {
    return simulatorState(
      await this.connection.read(
        sdk.createAdminSimulatorStop({
          client: this.client,
          headers: this.connection.mutationHeaders(),
        }),
      ),
    );
  }
  async backfillSimulator(input: SimulatorBackfill) {
    return scenarioRun(
      await this.connection.read(
        sdk.createAdminSimulatorBackfill({
          client: this.client,
          headers: this.connection.mutationHeaders(),
          // The contract has no anomalies field; anomaly names are backfill profiles.
          body: { profile: input.anomaly, from: input.from, to: input.to },
        }),
      ),
    );
  }
  async getScenarioRuns(
    page: number,
    size: number,
  ): Promise<Page<ScenarioRun>> {
    const data = await this.connection.read(
      sdk.getAdminScenarioRuns({
        client: this.client,
        query: { page, size },
      }),
    );
    return {
      items: requireValue(data.items, "scenarioRuns.items").map(scenarioRun),
      page: requireValue(data.page, "scenarioRuns.page"),
      size: requireValue(data.size, "scenarioRuns.size"),
      totalElements: requireValue(
        data.totalElements,
        "scenarioRuns.totalElements",
      ),
      totalPages: requireValue(data.totalPages, "scenarioRuns.totalPages"),
    };
  }
  async getRecentAlerts() {
    return (
      await this.connection.read(sdk.getAlertsRecent({ client: this.client }))
    ).map(recentAlert);
  }
  private async all<T>(
    getPage: (page: number) => Promise<PageMeta & { items?: T[] }>,
  ): Promise<T[]> {
    const rows: T[] = [];
    for (let page = 0; page < 10000; page++) {
      const data = await getPage(page);
      const items = requireValue(data.items, "page.items");
      const totalPages = requireValue(data.totalPages, "page.totalPages");
      if (
        !Number.isSafeInteger(totalPages) ||
        totalPages < 0 ||
        data.page !== page ||
        (page + 1 < totalPages && !items.length)
      )
        throw contractError("Inconsistent API pagination.");
      rows.push(...items);
      if (page + 1 >= totalPages) return rows;
    }
    throw contractError("API pagination exceeds the supported limit.");
  }
  private getRegions() {
    this.regions ??= this.all((page) =>
      this.connection.read(
        sdk.getRegions({ client: this.client, query: { page, size: 100 } }),
      ),
    ).catch((error) => {
      this.regions = undefined;
      throw error;
    });
    return this.regions;
  }
  private async regionId(region: Region) {
    const row = (await this.getRegions()).find(
      (x) => x.code?.toUpperCase() === region,
    );
    if (!row?.id) throw contractError(`API regions do not include ${region}.`);
    return row.id;
  }
  async getGeography(): Promise<GeographicArea[]> {
    return geographicAreas(await this.getRegions());
  }
  private async regionCode(id?: string): Promise<Region> {
    const code = (await this.getRegions())
      .find((x) => x.id === id)
      ?.code?.toUpperCase();
    if (code !== "MUNTENIA" && code !== "BANAT" && code !== "DOBROGEA")
      throw contractError("Unknown or missing regionId in API response.");
    return code;
  }
  async getSession() {
    try {
      return await this.connection.identity(
        sdk.getAuthMe({ client: this.client }),
      );
    } catch (error) {
      if (error instanceof AppError && error.status === 401) {
        this.connection.clearSession();
        return null;
      }
      throw error;
    }
  }
  async login(input: LoginInput) {
    if (!input.password)
      throw contractError("Username and password are required.");
    this.connection.clearSession();
    return this.connection.identity(
      sdk.createAuthLogin({
        client: this.client,
        body: { username: input.name, password: input.password },
      }),
    );
  }
  async logout() {
    await this.connection.read(
      sdk.createAuthLogout({
        client: this.client,
        headers: this.connection.mutationHeaders(),
      }),
    );
    this.connection.clearSession();
    this.maps.clear();
    this.regions = undefined;
  }
  async getMap(region: Region, subregionId?: string): Promise<MapData> {
    const regionId = await this.regionId(region);
    const [assets, rawAssets, issues, rawOutages] = await Promise.all([
      this.all((page) =>
        this.connection.read(
          sdk.getAssets({
            client: this.client,
            query: { regionId, subregionId, page, size: 100 },
          }),
        ),
      ),
      this.connection.read(
        sdk.getMapFeatures({
          client: this.client,
          query: { regionId, subregionId, layer: "ASSETS" },
        }),
      ),
      this.all((page) =>
        this.connection.read(
          sdk.getMapIssues({
            client: this.client,
            query: {
              regionId,
              subregionId,
              includeHistorical: false,
              page,
              size: 100,
            },
          }),
        ),
      ),
      this.connection.read(
        sdk.getMapFeatures({
          client: this.client,
          query: { regionId, subregionId, layer: "OUTAGES" },
        }),
      ),
    ]);
    const mappedAssets = mapCollection(rawAssets, "ASSETS", assets);
    const issueList = issues
      .filter((i) => !i.isHistorical)
      .map((i) => issueRecord(i, region));
    const mappedIssues: MapData["issues"] = {
      type: "FeatureCollection",
      features: issueList.map((i) => ({
        type: "Feature",
        id: i.id,
        geometry: { type: "Point", coordinates: i.coordinates },
        properties: {
          id: i.id,
          type: i.type ?? "OUTAGE_REPORT",
          title: i.title,
          status: i.status,
        },
      })),
    };
    const map: MapData = {
      assets: mappedAssets,
      issues: mappedIssues,
      outages: mapCollection(rawOutages, "OUTAGES"),
      assetList: assetList(mappedAssets, region),
      issueList,
    };
    this.maps.set(region, map);
    return map;
  }
  async getMapMeters(
    region: Region,
    segmentId?: string,
  ): Promise<MeterMarker[]> {
    const regionId = await this.regionId(region);
    const [meters, clients] = await Promise.all([
      this.all((page) =>
        this.connection.read(
          sdk.getMeters({
            client: this.client,
            query: { regionId, segmentId, page, size: 100 },
          }),
        ),
      ),
      this.all((page) =>
        this.connection.read(
          sdk.getClients({
            client: this.client,
            query: { regionId, page, size: 100 },
          }),
        ),
      ),
    ]);
    const markers: MeterMarker[] = [];
    for (let offset = 0; offset < meters.length; offset += 8) {
      markers.push(
        ...(await Promise.all(
          meters.slice(offset, offset + 8).map(async (meter) => {
            const id = requireValue(meter.id, "meter.id");
            const readings = await this.connection.read(
              sdk.getMeterReadings({
                client: this.client,
                query: { meterId: id, page: 0, size: 1 },
              }),
            );
            const reading = requireValue(readings.items, "readings.items")[0];
            return {
              id,
              code: requireValue(meter.externalCode, "meter.externalCode"),
              segmentId: meter.segmentId ?? meter.subregionId ?? undefined,
              coordinates: coordinate(meter.location?.coordinates),
              clientType:
                clients.find((c) => c.id === meter.clientId)?.clientType ??
                null,
              lastReading: reading
                ? {
                    kWh: requireValue(reading.energyKwh, "reading.energyKwh"),
                    timestamp: requireValue(
                      reading.intervalEnd,
                      "reading.intervalEnd",
                    ),
                  }
                : null,
            };
          }),
        )),
      );
    }
    return markers;
  }
  async getIssues(filter: IssueFilter) {
    const { region, ...query } = filter;
    const result = await this.connection.read(
      sdk.getMapIssues({
        client: this.client,
        query: {
          ...query,
          regionId: region ? await this.regionId(region) : undefined,
          includeHistorical: false,
        },
      }),
    );
    return {
      items: await Promise.all(
        requireValue(result.items, "issues.items")
          .filter((i) => !i.isHistorical)
          .map(async (dto) =>
            issueRecord(
              dto,
              region ?? (await this.regionCode(dto.regionId ?? undefined)),
            ),
          ),
      ),
      page: requireValue(result.page, "issues.page"),
      size: requireValue(result.size, "issues.size"),
      totalElements: requireValue(result.totalElements, "issues.totalElements"),
      totalPages: requireValue(result.totalPages, "issues.totalPages"),
    };
  }
  createForecastRun(body: ForecastRunCreate) {
    return this.connection.read(
      sdk.createForecastRun({
        client: this.client,
        headers: this.connection.mutationHeaders(),
        body,
      }),
    );
  }
  getForecastRun(id: string) {
    return this.connection.read(
      sdk.getForecastRun({ client: this.client, path: { id } }),
    );
  }
  getForecastThresholds() {
    return this.connection.read(
      sdk.getForecastThresholds({ client: this.client }),
    );
  }
  updateForecastThreshold(segmentId: string, value: number) {
    return this.connection.read(
      sdk.updateForecastThreshold({
        client: this.client,
        headers: this.connection.mutationHeaders(),
        path: { segmentId },
        body: { dailyEnergyKwh: value },
      }),
    );
  }
  async createIssue(input: CreateIssue) {
    const asset = [...this.maps.values()]
      .flatMap((x) => x.assetList)
      .find((x) => x.id === input.assetId);
    if (!asset)
      throw contractError(
        "Load the asset on the map before creating an issue.",
      );
    if (
      input.offsetSeconds !== undefined &&
      (!Number.isInteger(input.offsetSeconds) || input.offsetSeconds < 0)
    )
      throw new AppError(422, {
        code: "VALIDATION",
        message: "Video offset must be a non-negative whole number of seconds.",
        fieldErrors: { offsetSeconds: "Use whole seconds." },
        requestId: "client-validation",
      });
    const data = await this.connection.read(
      sdk.createMapIssues({
        client: this.client,
        headers: this.connection.mutationHeaders(),
        body: {
          assetId: input.assetId,
          location: {
            type: "Point",
            coordinates: input.coordinates ?? asset.coordinates,
          },
          type: "OUTAGE_REPORT",
          regionId: input.regionId,
          segmentId: input.segmentId,
          severity: input.severity,
          description: input.description,
          videoInspectionId: input.videoId,
          videoOffsetSeconds: input.offsetSeconds,
        },
      }),
    );
    return {
      ...issueRecord(data, asset.region),
      videoId: input.videoId,
      offsetSeconds: input.offsetSeconds,
    };
  }
  async updateIssue(input: {
    id: string;
    status: IssueStatus;
    version: number;
    simulateConflict?: boolean;
  }) {
    const region = [...this.maps].find(([, map]) =>
      map.issueList.some((x) => x.id === input.id),
    )?.[0];
    const data = await this.connection.read(
      sdk.patchMapIssuesIdStatus({
        client: this.client,
        headers: this.connection.mutationHeaders(),
        path: { id: input.id },
        body: { status: input.status, version: input.version },
      }),
    );
    return issueRecord(
      data,
      region ?? (await this.regionCode(data.regionId ?? undefined)),
    );
  }
  private async fileRows(
    region: Region,
    filter?: Pick<FileFilter, "category" | "status" | "subregionId">,
  ): Promise<FileResource[]> {
    const regionId = await this.regionId(region);
    return this.all((page) =>
      this.connection.read(
        sdk.getFiles({
          client: this.client,
          query: {
            regionId,
            subregionId: filter?.subregionId,
            category: filter?.category,
            status: filter?.status,
            page,
            size: 100,
          },
        }),
      ),
    );
  }
  async getFiles(filter: FileFilter) {
    const rows = (await this.fileRows(filter.region, filter))
      .map((x) => fileRecord(x, filter.region))
      .filter((x) =>
        `${x.name} ${x.id}`.toLowerCase().includes(filter.search.toLowerCase()),
      )
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    return paginate(rows, filter.page, filter.size);
  }
  async getFile(id: string) {
    const dto = await this.connection.read(
      sdk.getFilesId({ client: this.client, path: { id } }),
    );
    const file = fileRecord(dto, await this.regionCode(dto.regionId));
    if (file.status === "READY" || file.status === "CORRUPT") {
      const verify = await this.connection.read(
        sdk.getFilesIdVerify({ client: this.client, path: { id } }),
      );
      file.expectedSha256 = requireValue(
        verify.expectedSha256,
        "verify.expectedSha256",
      );
      file.actualSha256 = requireValue(
        verify.actualSha256,
        "verify.actualSha256",
      );
      if (!requireValue(verify.valid, "verify.valid")) file.status = "CORRUPT";
    }
    return file;
  }
  private async caseRows(
    region?: Region,
    segmentId?: string,
  ): Promise<ConnectionCase[]> {
    const regionId = region ? await this.regionId(region) : undefined;
    return this.all((page) =>
      this.connection.read(
        sdk.getConnectionCases({
          client: this.client,
          query: { regionId, segmentId, page, size: 100 },
        }),
      ),
    );
  }
  async getCases(filter: CaseFilter): Promise<Page<CaseRecord>> {
    const missingClients = filter.missingOnly
      ? await this.all(async (page) =>
          this.connection.read(
            sdk.getClientsMissingDocuments({
              client: this.client,
              query: {
                regionId: filter.region
                  ? await this.regionId(filter.region)
                  : undefined,
                segmentId: filter.segmentId,
                page,
                size: 100,
              },
            }),
          ),
        )
      : undefined;
    const missingCases = missingClients
      ? new Map(
          missingClients.flatMap((c) =>
            (c.cases ?? []).map((item) => [item.caseId, c] as const),
          ),
        )
      : undefined;
    const scopedRows = (
      await this.caseRows(filter.region, filter.segmentId)
    ).filter((dto) => !missingCases || missingCases.has(dto.id));
    const records = await Promise.all(
      scopedRows.map(async (dto) => ({
        id: requireValue(dto.id, "case.id"),
        title: missingCases
          ? `${requireValue(missingCases.get(dto.id)?.externalCode, "client.externalCode")} · Connection case ${dto.id?.slice(0, 8)}`
          : `Connection case ${requireValue(dto.id, "case.id").slice(0, 8)}`,
        region:
          filter.region ??
          (await this.regionCode(missingCases?.get(dto.id)?.regionId)),
        dueAt: dto.dueAt ?? null,
        status:
          dto.status === "CLOSED"
            ? ("COMPLETE" as const)
            : dto.status === "OPEN"
              ? ("OPEN" as const)
              : (() => {
                  throw contractError("Unknown case status.");
                })(),
        documents: [] as CaseRecord["documents"],
      })),
    );
    const rows = records
      .filter(
        (x) =>
          (!filter.status || x.status === filter.status) &&
          `${x.title} ${x.id}`
            .toLowerCase()
            .includes(filter.search.toLowerCase()),
      )
      .sort((a, b) => (a.dueAt ?? "9999").localeCompare(b.dueAt ?? "9999"));
    const page = paginate(rows, filter.page, filter.size);
    const types = await this.connection.read(
      sdk.getDocumentTypes({ client: this.client }),
    );
    await Promise.all(
      page.items.map(async (row) => {
        const checklist = await this.connection.read(
          sdk.getConnectionCasesIdDocuments({
            client: this.client,
            path: { id: row.id },
          }),
        );
        const missing = requireValue(
          checklist.missingDocumentTypes,
          "checklist.missingDocumentTypes",
        );
        const received = [
          ...new Map(
            requireValue(checklist.documents, "checklist.documents")
              .filter(
                (doc) =>
                  !missing.some((type) => type.id === doc.documentTypeId),
              )
              .map((doc) => [doc.documentTypeId, doc]),
          ).values(),
        ];
        row.documents = [
          ...received.map((doc) => ({
            name:
              types.find((t) => t.id === doc.documentTypeId)?.name ??
              `Document ${doc.documentTypeId ?? "unknown"}`,
            received: true,
          })),
          ...missing.map((doc) => ({
            name: requireValue(doc.name, "documentType.name"),
            received: false,
          })),
        ];
      }),
    );
    return page;
  }
  async getStatistics(region: Region): Promise<Statistics> {
    // Contract stats schemas are opaque; compute only UI facts available in typed endpoints.
    const [files, cases, map] = await Promise.all([
      this.fileRows(region),
      this.caseRows(region),
      this.getMap(region),
    ]);
    return {
      files: files.length,
      ready: files.filter((x) => x.status === "READY").length,
      corrupt: files.filter((x) => x.status === "CORRUPT").length,
      bytes: files.reduce(
        (n, x) => n + requireValue(x.sizeBytes, "file.sizeBytes"),
        0,
      ),
      openIssues: map.issueList.filter((x) => x.status !== "RESOLVED").length,
      overdueCases: cases.filter(
        (x) =>
          x.status !== "CLOSED" && x.dueAt && Date.parse(x.dueAt) < Date.now(),
      ).length,
    };
  }
}
function paginate<T>(items: T[], page: number, size: number): Page<T> {
  return {
    items: items.slice(page * size, (page + 1) * size),
    page,
    size,
    totalElements: items.length,
    totalPages: Math.ceil(items.length / size),
  };
}
