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
} from "./models";
import type { UploadTransport } from "../upload/types";

// The only boundary the hooks know. Generated DTOs must never escape an ApiSource.
export interface DataSource {
  readonly kind: "demo" | "mock" | "api";
  readonly uploadScope?: string;
  readonly uploads: UploadTransport;
  getSession(): Promise<Session | null>;
  login(input: LoginInput): Promise<Session>;
  logout(): Promise<void>;
  getMap(region: Region): Promise<MapData>;
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
  getPolicies(): Promise<EffectivePolicy[]>;
  reloadPolicies(): Promise<EffectivePolicy[]>;
  getSimulatorStatus(): Promise<SimulatorState>;
  startSimulator(input: SimulatorStart): Promise<SimulatorState>;
  stopSimulator(): Promise<SimulatorState>;
  backfillSimulator(input: SimulatorBackfill): Promise<ScenarioRun>;
  getScenarioRuns(page: number, size: number): Promise<Page<ScenarioRun>>;
  getRecentAlerts(): Promise<RecentAlert[]>;
}
