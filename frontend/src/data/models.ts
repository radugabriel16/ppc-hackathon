import type {
  FeatureCollection,
  LineString,
  MultiPolygon,
  Point,
} from "geojson";
export type {
  ForecastRun,
  ForecastRunCreate,
  SegmentThreshold,
  ClientMissingDocuments,
} from "../api/gen/types.gen";
import type { IssueType } from "../api/gen/types.gen";
export type { IssueType };

export interface GeographicArea {
  id: string;
  code: string;
  name: string;
  region: Region;
  parentId: string | null;
  geometry: MultiPolygon;
  meterCount: number;
}

export const REGIONS = ["MUNTENIA", "BANAT", "DOBROGEA"] as const;
export type Region = (typeof REGIONS)[number];
export type Role = "OPERATOR" | "MANAGER";
export interface LoginInput {
  name: string;
  role: Role;
  password?: string;
}
export interface Session {
  user: { name: string; role: Role };
  csrfToken: string;
}
export const CATEGORIES = [
  "METER_READING",
  "OUTAGE_RECORD",
  "CONNECTION_DOCUMENT",
  "DRONE_VIDEO",
] as const;
export type Category = (typeof CATEGORIES)[number];
export const FILE_STATUSES = [
  "STAGING",
  "VERIFYING",
  "READY",
  "FAILED",
  "CORRUPT",
] as const;
export type FileStatus = (typeof FILE_STATUSES)[number];
export interface Page<T> {
  items: T[];
  page: number;
  size: number;
  totalElements: number;
  totalPages: number;
}
export interface FileRecord {
  id: string;
  name: string;
  category: Category;
  status: FileStatus;
  sizeBytes: number;
  region: Region;
  createdAt: string;
  expectedSha256: string;
  actualSha256: string;
}
export interface FileFilter {
  region: Region;
  subregionId?: string;
  category?: Category;
  status?: FileStatus;
  search: string;
  page: number;
  size: number;
}
export type IssueStatus = "OPEN" | "IN_PROGRESS" | "RESOLVED";
export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export interface Asset {
  id: string;
  name: string;
  type: "SUBSTATION" | "TRANSFORMER" | "LINE_SEGMENT";
  region: Region;
  segmentId?: string;
  coordinates: [number, number];
}
export interface Issue {
  id: string;
  assetId: string;
  region: Region;
  description: string;
  severity: Severity;
  status: IssueStatus;
  version: number | null;
  coordinates: [number, number];
  videoId?: string;
  offsetSeconds?: number;
  type?: IssueType;
  title?: string;
  isHistorical?: boolean;
  segmentId?: string;
  regionId?: string;
  clientId?: string;
  caseId?: string;
  forecastDate?: string;
  createdAt?: string;
}
export interface CreateIssue {
  assetId: string;
  severity: Severity;
  description: string;
  videoId?: string;
  offsetSeconds?: number;
  coordinates?: [number, number];
  regionId?: string;
  segmentId?: string;
}
export interface IssueFilter {
  region?: Region;
  segmentId?: string;
  type?: IssueType;
  status?: IssueStatus;
  clientId?: string;
  from?: string;
  to?: string;
  page: number;
  size: number;
}
export interface MeterMarker {
  id: string;
  assetId: string;
  code: string;
  segmentId?: string;
  coordinates: [number, number];
  clientType: string | null;
  lastReading: { kWh: number; timestamp: string } | null;
}
export interface MapData {
  assets: FeatureCollection<Point | LineString>;
  issues: FeatureCollection<Point>;
  outages: FeatureCollection<Point>;
  assetList: Asset[];
  issueList: Issue[];
  meters?: MeterMarker[];
}
export interface CaseRecord {
  id: string;
  title: string;
  region: Region;
  dueAt: string | null;
  status: "OPEN" | "REVIEW" | "COMPLETE";
  documents: { name: string; received: boolean }[];
}
export interface CaseFilter {
  region?: Region;
  segmentId?: string;
  missingOnly?: boolean;
  search: string;
  status?: CaseRecord["status"];
  page: number;
  size: number;
}
export interface Statistics {
  files: number;
  ready: number;
  corrupt: number;
  openIssues: number;
  overdueCases: number;
  bytes: number;
}
export const STORAGES = ["db", "ftp", "s3"] as const;
export type StorageKind = (typeof STORAGES)[number];
export type BenchmarkProfile = "normal" | "peak";
export interface StorageBenchmark {
  category: Category;
  storage: StorageKind;
  profile: BenchmarkProfile;
  p50Ms: number;
  p95Ms: number;
  p99Ms: number;
  throughputMiBps: number;
  errorRate: number;
}
export interface StorageRecommendation {
  category: Category;
  storage: StorageKind;
  reason: string;
}
export type MeterAnomaly = "spike" | "zero" | "gap";
export interface MeterReading {
  timestamp: string;
  kWh: number | null;
  anomaly: MeterAnomaly | null;
}
export interface MeterConsumption {
  id: string;
  label: string;
  region: Region;
  intervalMinutes: number;
  readings: MeterReading[];
}
export interface OutageHotspot {
  id: string;
  assetName: string;
  region: Region;
  coordinates: [number, number];
  outageCount: number;
  durationMinutes: number;
}
export interface ForecastPoint {
  timestamp: string;
  estimate: number | null;
  asOf: string;
  modelVersion: string;
  fallbackUsed: boolean;
  status: "READY" | "INSUFFICIENT_DATA";
}
export interface EffectivePolicy {
  category: string;
  backend: string | null;
  fallback: string | null;
  maxSizeBytes: number | null;
  maxConcurrency: number | null;
  encryption: string | null;
  resumable: boolean | null;
  chunkSizeBytes: number | null;
}
export const SIMULATOR_PROFILES = ["normal", "peak", "storm"] as const;
export const BACKFILL_ANOMALIES = ["spike", "zero", "gap"] as const;
export interface SimulatorStart {
  profile: (typeof SIMULATOR_PROFILES)[number];
  readingsPerSecond: number;
}
export interface SimulatorBackfill {
  anomaly: (typeof BACKFILL_ANOMALIES)[number];
  from: string;
  to: string;
}
export interface SimulatorState {
  running: boolean;
  profile: string | null;
  readingsPerSecond: number | null;
}
export interface ScenarioRun {
  id: string;
  kind: string | null;
  profile: string | null;
  startedAt: string | null;
  endedAt: string | null;
  counters: Record<string, unknown>;
}
export interface RecentAlert {
  id: string;
  severity: string | null;
  message: string;
  occurredAt: string | null;
}
export interface RegionDefinition {
  name: string;
  center: [number, number];
  bbox: [number, number, number, number];
}
// Illustrative operational areas, not authoritative administrative boundaries.
export const REGION_INFO: Record<Region, RegionDefinition> = {
  MUNTENIA: {
    name: "Muntenia",
    center: [26.1, 44.43],
    bbox: [24.5, 43.65, 27.5, 45.55],
  },
  BANAT: {
    name: "Banat",
    center: [21.23, 45.75],
    bbox: [20.25, 44.6, 22.7, 46.25],
  },
  DOBROGEA: {
    name: "Dobrogea",
    center: [28.63, 44.18],
    bbox: [27.5, 43.7, 29.75, 45.5],
  },
};
export const label = (value: string) =>
  value
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/^\w/, (c) => c.toUpperCase());
export const bytes = (value: number) =>
  value < 1024
    ? `${value} B`
    : value < 1048576
      ? `${(value / 1024).toFixed(1)} KB`
      : `${(value / 1048576).toFixed(1)} MB`;
