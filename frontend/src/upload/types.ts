import type { Category, FileStatus, Region } from "../data/models";

export interface UploadInput {
  category: Category;
  fileName: string;
  sizeBytes: number;
  metadata: { region: Region; simulateCorrupt?: boolean };
}
export interface UploadSession {
  uploadId: string;
  chunkSize: number;
  totalParts: number;
  expiresAt: string;
}
export interface UploadStatus {
  status: "STAGING" | "VERIFYING" | "READY" | "CORRUPT";
  receivedParts: number[];
  totalParts: number;
}
export interface CompletedUpload {
  fileId: string;
  status: "VERIFYING";
}
export interface UploadTransport {
  create(input: UploadInput, signal: AbortSignal): Promise<UploadSession>;
  putPart(
    id: string,
    part: number,
    bytes: Blob,
    sha256: string,
    signal: AbortSignal,
  ): Promise<{ partNumber: number; etag: string }>;
  getStatus(id: string, signal: AbortSignal): Promise<UploadStatus>;
  complete(
    id: string,
    sha256: string,
    signal: AbortSignal,
  ): Promise<CompletedUpload>;
  cancel(id: string, signal: AbortSignal): Promise<void>;
}
export interface HashService {
  digest(blob: Blob, signal: AbortSignal): Promise<string>;
  dispose?(): void;
}
export type UploadState =
  | "idle"
  | "hashing"
  | "uploading"
  | "paused"
  | "completing"
  | "verifying"
  | "failed"
  | "cancelled";
export interface UploadSnapshot {
  state: UploadState;
  sentBytes: number;
  totalBytes: number;
  speed: number;
  retries: number;
  fileId?: string;
  error?: string;
}
export type UploadEvent = {
  type: "progress" | "speed" | "retries" | "state";
  snapshot: UploadSnapshot;
};
export interface SavedUpload {
  uploadId: string;
  fingerprint: string;
  chunkSize: number;
  fileName: string;
  sizeBytes: number;
  lastModified: number;
  category: Category;
  region: Region;
  simulateCorrupt?: boolean;
}
export interface KeyValueStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}
export interface UploadFileRecord {
  id: string;
  name: string;
  category: Category;
  sizeBytes: number;
  region: Region;
  createdAt: string;
  status: FileStatus;
  expectedSha256: string;
  actualSha256: string;
  verifyAt: number;
}
