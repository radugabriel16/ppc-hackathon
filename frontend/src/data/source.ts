import type {
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
  LoginInput,
  Session,
  Statistics,
  EffectivePolicy,
  SimulatorStart,
  SimulatorBackfill,
  SimulatorState,
  ScenarioRun,
  RecentAlert,
  StorageBenchmark,
  StorageRecommendation,
  MeterConsumption,
  OutageHotspot,
  ForecastPoint,
  GeographicArea,
  IssueFilter,
  ForecastRun,
  ForecastRunCreate,
  SegmentThreshold,
  MeterMarker,
} from "./models";
import type { UploadTransport } from "../upload/types";
import type { DocumentType } from "../api/gen/types.gen";

// The data boundary used by hooks, with typed contract resources for operations.
export interface DataSource {
  readonly documentIntake?: import("./document-intake").DocumentIntakeApi;
  readonly kind: "demo" | "mock" | "api";
  readonly uploadScope?: string;
  readonly uploads: UploadTransport;
  getDocumentTypes?(): Promise<DocumentType[]>;
  getGeography(): Promise<GeographicArea[]>;
  downloadFile?(id: string, inline?: boolean): Promise<Blob>;
  getSession(): Promise<Session | null>;
  login(input: LoginInput): Promise<Session>;
  logout(): Promise<void>;
  getMap(region: Region, subregionId?: string): Promise<MapData>;
  getMapMeters?(
    region: Region,
    segmentId: string,
  ): Promise<MeterMarker[]>;
  getIssues?(filter: IssueFilter): Promise<Page<Issue>>;
  createForecastRun?(input: ForecastRunCreate): Promise<ForecastRun>;
  getForecastRun?(id: string): Promise<ForecastRun>;
  getForecastThresholds?(): Promise<SegmentThreshold[]>;
  updateForecastThreshold?(
    segmentId: string,
    value: number,
  ): Promise<SegmentThreshold>;
  createIssue(input: CreateIssue): Promise<Issue>;
  updateIssue(input: {
    id: string;
    status: IssueStatus;
    version: number;
    simulateConflict?: boolean;
  }): Promise<Issue>;
  getFiles(filter: FileFilter): Promise<Page<FileRecord>>;
  getFile(id: string): Promise<FileRecord>;
  getCases(filter: CaseFilter): Promise<Page<CaseRecord>>;
  getStatistics(region: Region): Promise<Statistics>;
  getStorageBenchmark(): Promise<StorageBenchmark[]>;
  getStorageRecommendations(): Promise<StorageRecommendation[]>;
  getMeterConsumption(
    region: Region,
    subregionId?: string,
  ): Promise<MeterConsumption[]>;
  getOutageHotspots(
    region: Region,
    subregionId?: string,
  ): Promise<OutageHotspot[]>;
  getForecast(region: Region, subregionId?: string): Promise<ForecastPoint[]>;
  getPolicies(): Promise<EffectivePolicy[]>;
  reloadPolicies(): Promise<EffectivePolicy[]>;
  getSimulatorStatus(): Promise<SimulatorState>;
  startSimulator(input: SimulatorStart): Promise<SimulatorState>;
  stopSimulator(): Promise<SimulatorState>;
  backfillSimulator(input: SimulatorBackfill): Promise<ScenarioRun>;
  getScenarioRuns(page: number, size: number): Promise<Page<ScenarioRun>>;
  getRecentAlerts(): Promise<RecentAlert[]>;
}
