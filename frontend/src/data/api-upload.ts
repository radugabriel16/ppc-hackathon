import {
  createUploads,
  putUploadsIdPartsPartNumber,
  getUploadsId,
  createUploadsIdComplete,
  deleteUploadsId,
} from "../api/gen/sdk.gen";
import type {
  UploadInput,
  UploadStatus,
  UploadTransport,
} from "../upload/types";
import { AppError } from "./errors";
import { ApiConnection, contractError, requireValue } from "./api-client";

export class ApiUploadTransport implements UploadTransport {
  constructor(private api: ApiConnection) {}
  async create(input: UploadInput, signal: AbortSignal) {
    // UI-only region/simulation flags are not FileUploadMetadata. Never send an invalid union.
    const data = await this.api.read(
      createUploads({
        client: this.api.client,
        signal,
        headers: this.api.mutationHeaders(),
        body: {
          category: input.category,
          fileName: input.fileName,
          sizeBytes: input.sizeBytes,
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
    if (
      status !== "STAGING" &&
      status !== "VERIFYING" &&
      status !== "READY" &&
      status !== "CORRUPT"
    )
      throw contractError(`Unsupported upload status: ${status}.`);
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
