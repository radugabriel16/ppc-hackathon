import type { Category, FileStatus, Region } from "../data/models";
import type { FileUploadMetadata } from "../api/gen/types.gen";

export interface UploadInput {
  category: Category;
  fileName: string;
  sizeBytes: number;
  metadata: {
    region: Region;
    simulateCorrupt?: boolean;
    fileMetadata?: FileUploadMetadata;
  };
}
export interface UploadSession {
  uploadId: string;
  chunkSize: number;
  totalParts: number;
  expiresAt: string;
}
export interface UploadStatus {
  status:
    | "PENDING"
    | "UPLOADING"
    | "COMPLETING"
    | "COMPLETED"
    | "ABORTED"
    | "EXPIRED";
  receivedParts: number[];
  totalParts: number;
}
export interface CompletedUpload {
  fileId: string;
  status: "VERIFYING" | "READY";
}
export interface UploadTransport {
  direct?(
    file: File,
    metadata: FileUploadMetadata,
    signal: AbortSignal,
  ): Promise<CompletedUpload>;
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
  fileMetadata?: FileUploadMetadata;
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
