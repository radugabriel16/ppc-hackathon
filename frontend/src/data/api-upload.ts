import {
  createUploads,
  putUploadsIdPartsPartNumber,
  getUploadsId,
  createUploadsIdComplete,
  deleteUploadsId,
  createFiles,
} from "../api/gen/sdk.gen";
import type { FileUploadMetadata } from "../api/gen/types.gen";
import type {
  UploadInput,
  UploadStatus,
  UploadTransport,
} from "../upload/types";
import { AppError } from "./errors";
import { ApiConnection, contractError, requireValue } from "./api-client";

export class ApiUploadTransport implements UploadTransport {
  constructor(private api: ApiConnection) {}
  async direct(file: File, metadata: FileUploadMetadata, signal: AbortSignal) {
    const data = await this.api.read(
      createFiles({
        client: this.api.client,
        signal,
        headers: this.api.mutationHeaders(),
        body: { file, metadata },
      }),
    );
    if (data.status !== "READY")
      throw contractError("Expected READY after direct upload.");
    return { fileId: requireValue(data.id, "file.id"), status: data.status };
  }
  async create(input: UploadInput, signal: AbortSignal) {
    const metadata = input.metadata.fileMetadata;
    if (
      input.category !== "DRONE_VIDEO" ||
      metadata?.category !== "DRONE_VIDEO"
    )
      throw contractError(
        "Resumable uploads require drone video asset and recording metadata.",
      );
    const data = await this.api.read(
      createUploads({
        client: this.api.client,
        signal,
        headers: this.api.mutationHeaders(),
        body: {
          category: "DRONE_VIDEO",
          fileName: input.fileName,
          sizeBytes: input.sizeBytes,
          mediaType: input.mediaType,
          metadata,
        },
      }),
    );
    return {
      uploadId: requireValue(data.uploadId, "uploadId"),
      chunkSize: requireValue(data.chunkSize, "chunkSize"),
      totalParts: requireValue(data.totalParts, "totalParts"),
      expiresAt: requireValue(data.expiresAt, "expiresAt"),
    };
  }
  async putPart(
    id: string,
    part: number,
    bytes: Blob,
    sha256: string,
    signal: AbortSignal,
  ) {
    const data = await this.api.read(
      putUploadsIdPartsPartNumber({
        client: this.api.client,
        signal,
        path: { id, partNumber: part },
        headers: {
          ...this.api.mutationHeaders(),
          "X-Part-SHA256": sha256,
          "Content-Type": "application/octet-stream",
        },
        body: bytes,
      }),
    );
    return {
      partNumber: requireValue(data.partNumber, "partNumber"),
      etag: requireValue(data.etag, "etag"),
    };
  }
  async getStatus(id: string, signal: AbortSignal): Promise<UploadStatus> {
    const data = await this.api.read(
      getUploadsId({ client: this.api.client, signal, path: { id } }),
    );
    const status = requireValue(data.status, "upload.status");
    return {
      status,
      receivedParts: requireValue(data.receivedParts, "receivedParts"),
      totalParts: requireValue(data.totalParts, "totalParts"),
    };
  }
  async complete(id: string, sha256: string, signal: AbortSignal) {
    const data = await this.api.read(
      createUploadsIdComplete({
        client: this.api.client,
        signal,
        path: { id },
        headers: this.api.mutationHeaders(),
        body: { sha256 },
      }),
    );
    if (data.status !== "VERIFYING")
      throw contractError("Expected VERIFYING after upload completion.");
    return {
      fileId: requireValue(data.fileId, "fileId"),
      status: "VERIFYING" as const,
    };
  }
  async cancel(id: string, signal: AbortSignal) {
    try {
      await this.api.read(
        deleteUploadsId({
          client: this.api.client,
          signal,
          path: { id },
          headers: this.api.mutationHeaders(),
        }),
      );
    } catch (error) {
      if (!(error instanceof AppError && error.status === 404)) throw error;
    }
  }
}
