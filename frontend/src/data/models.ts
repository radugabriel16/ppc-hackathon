import type { FeatureCollection, LineString, Point } from "geojson";

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
}
export interface CreateIssue {
  assetId: string;
  severity: Severity;
  description: string;
  videoId?: string;
  offsetSeconds?: number;
}
export interface MapData {
  assets: FeatureCollection<Point | LineString>;
  issues: FeatureCollection<Point>;
  outages: FeatureCollection<Point>;
  assetList: Asset[];
  issueList: Issue[];
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
  region: Region;
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
