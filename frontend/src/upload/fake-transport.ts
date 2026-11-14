import { AppError } from "../data/errors";
import { abortableSleep } from "./engine";
import { digestBlob } from "./hash";
import type {
  CompletedUpload,
  UploadFileRecord,
  UploadInput,
  UploadSession,
  UploadStatus,
  UploadTransport,
} from "./types";

export interface DemoStore {
  get<T>(key: string): Promise<T | undefined>;
  put<T>(key: string, value: T): Promise<void>;
  delete(key: string): Promise<void>;
  entries<T>(prefix: string): Promise<{ key: string; value: T }[]>;
}
export class MemoryDemoStore implements DemoStore {
  private data = new Map<string, unknown>();
  async get<T>(key: string) {
    return this.data.get(key) as T | undefined;
  }
  async put<T>(key: string, value: T) {
    this.data.set(key, value);
  }
  async delete(key: string) {
    this.data.delete(key);
  }
  async entries<T>(prefix: string) {
    return [...this.data]
      .filter(([key]) => key.startsWith(prefix))
      .map(([key, value]) => ({ key, value: value as T }));
  }
}
// IndexedDB represents the demo server disk. No file payloads go into localStorage.
export class IndexedDemoStore implements DemoStore {
  private db?: Promise<IDBDatabase>;
  constructor(private databaseName = "filegrid-demo-server") {}
  private open() {
    this.db ??= new Promise((resolve, reject) => {
      const request = indexedDB.open(this.databaseName, 1);
      request.onupgradeneeded = () =>
        request.result.createObjectStore("records");
      request.onsuccess = () => resolve(request.result);
      request.onerror = () =>
        reject(request.error ?? new Error("IndexedDB unavailable"));
    });
    return this.db;
  }
  private async operation<T>(
    mode: IDBTransactionMode,
    action: (store: IDBObjectStore) => IDBRequest<T>,
  ): Promise<T> {
    const db = await this.open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("records", mode);
      const request = action(tx.objectStore("records"));
      tx.oncomplete = () => resolve(request.result);
      tx.onerror = () => reject(tx.error ?? new Error("Demo storage failed"));
      tx.onabort = () =>
        reject(tx.error ?? new Error("Demo storage transaction aborted"));
    });
  }
  get<T>(key: string) {
    return this.operation("readonly", (store) => store.get(key)) as Promise<
      T | undefined
    >;
  }
  async put<T>(key: string, value: T) {
    await this.operation("readwrite", (store) => store.put(value, key));
  }
  async delete(key: string) {
    await this.operation("readwrite", (store) => store.delete(key));
  }
  async entries<T>(prefix: string) {
    const db = await this.open();
    return new Promise<{ key: string; value: T }[]>((resolve, reject) => {
      const items: { key: string; value: T }[] = [];
      const tx = db.transaction("records", "readonly");
      const request = tx
        .objectStore("records")
        .openCursor(IDBKeyRange.bound(prefix, `${prefix}\uffff`));
      request.onsuccess = () => {
        const cursor = request.result;
        if (cursor) {
          items.push({ key: String(cursor.key), value: cursor.value as T });
          cursor.continue();
        }
      };
      tx.oncomplete = () => resolve(items);
      tx.onerror = () => reject(tx.error);
    });
  }
}
interface ServerSession extends UploadSession {
  input: UploadInput;
  completed?: CompletedUpload;
}
interface ServerPart {
  number: number;
  body: Blob;
  hash: string;
}
export interface FakeOptions {
  store: DemoStore;
  failureRate?: number;
  random?: () => number;
  latencyMs?: number;
  chunkSize?: number;
  verifyMs?: number;
  now?: () => number;
}
const problem = (
  status: number,
  message: string,
  code = "DEMO_ERROR",
  retryAfter?: string,
) =>
  new AppError(
    status,
    { code, message, requestId: `demo-${crypto.randomUUID().slice(0, 8)}` },
    retryAfter,
  );

export class FakeUploadTransport implements UploadTransport {
  readonly store: DemoStore;
  private readonly now: () => number;
  constructor(private options: FakeOptions) {
    this.store = options.store;
    this.now = options.now ?? Date.now;
  }
  private async delay(signal: AbortSignal) {
    await abortableSleep(this.options.latencyMs ?? 180, signal);
  }
  private async session(id: string) {
    const session = await this.store.get<ServerSession>(`upload:${id}`);
    if (!session)
      throw problem(
        404,
        "Upload not found. Start a new upload.",
        "UPLOAD_NOT_FOUND",
      );
    if (!session.completed && Date.parse(session.expiresAt) < this.now())
      throw problem(
        410,
        "Upload expired. Cancel it and start again.",
        "UPLOAD_EXPIRED",
      );
    return session;
  }
  async create(
    input: UploadInput,
    signal: AbortSignal,
  ): Promise<UploadSession> {
    await this.delay(signal);
    const chunkSize = this.options.chunkSize ?? 1024 * 1024;
    const session: ServerSession = {
      uploadId: crypto.randomUUID(),
      chunkSize,
      totalParts: Math.ceil(input.sizeBytes / chunkSize),
      expiresAt: new Date(this.now() + 86400000).toISOString(),
      input,
    };
    await this.store.put(`upload:${session.uploadId}`, session);
    return session;
  }
  async putPart(
    id: string,
    part: number,
    body: Blob,
    sha256: string,
    signal: AbortSignal,
  ) {
    await this.delay(signal);
    const session = await this.session(id);
    if (session.completed) throw problem(409, "Upload already completed.");
    if (!Number.isInteger(part) || part < 1 || part > session.totalParts)
      throw problem(400, "Invalid part number.");
    const size = Math.min(
      session.chunkSize,
      session.input.sizeBytes - (part - 1) * session.chunkSize,
    );
    if (body.size !== size) throw problem(400, "Invalid part size.");
    const actual = await digestBlob(body, signal);
    if (actual !== sha256)
      throw problem(422, "Part SHA-256 mismatch.", "HASH_MISMATCH");
    const random = (this.options.random ?? Math.random)();
    const failureRate = this.options.failureRate ?? 0.2;
    if (random < failureRate / 2)
      throw problem(
        random < failureRate / 4 ? 429 : 503,
        "Temporary demo server overload.",
        "RETRY_LATER",
        "1",
      );
    signal.throwIfAborted();
    await this.store.put<ServerPart>(`part:${id}:${part}`, {
      number: part,
      body,
      hash: actual,
    });
    // The server accepted the part, but the response was lost. Retrying is idempotent.
    if (random < failureRate)
      throw new TypeError(
        "Demo connection dropped after the part was accepted.",
      );
    return { partNumber: part, etag: actual };
  }
  async getStatus(id: string, signal: AbortSignal): Promise<UploadStatus> {
    await this.delay(signal);
    const session = await this.session(id);
    const parts = await this.store.entries<ServerPart>(`part:${id}:`);
    const file = session.completed
      ? await this.getFile(session.completed.fileId)
      : undefined;
    return {
      status:
        file?.status === "READY" || file?.status === "CORRUPT"
          ? file.status
          : session.completed
            ? "VERIFYING"
            : "STAGING",
      receivedParts: parts.map((x) => x.value.number).sort((a, b) => a - b),
      totalParts: session.totalParts,
    };
  }
  async complete(
    id: string,
    sha256: string,
    signal: AbortSignal,
  ): Promise<CompletedUpload> {
    await this.delay(signal);
    const session = await this.session(id);
    if (session.completed) return session.completed;
    const parts = (await this.store.entries<ServerPart>(`part:${id}:`))
      .map((x) => x.value)
      .sort((a, b) => a.number - b.number);
    if (parts.length !== session.totalParts)
      throw problem(400, "Upload has missing parts.", "MISSING_PARTS");
    const actual = await digestBlob(new Blob(parts.map((x) => x.body)), signal);
    const result: CompletedUpload = { fileId: `up-${id}`, status: "VERIFYING" };
    const file: UploadFileRecord = {
      id: result.fileId,
      name: session.input.fileName,
      category: session.input.category,
      sizeBytes: session.input.sizeBytes,
      region: session.input.metadata.region,
      createdAt: new Date(this.now()).toISOString(),
      status: "VERIFYING",
      expectedSha256: sha256,
      actualSha256: session.input.metadata.simulateCorrupt
        ? `${actual[0] === "0" ? "1" : "0"}${actual.slice(1)}`
        : actual,
      verifyAt: this.now() + (this.options.verifyMs ?? 3500),
    };
    await this.store.put(`file:${file.id}`, file);
    await this.store.put<ServerSession>(`upload:${id}`, {
      ...session,
      completed: result,
    });
    return result;
  }
  async cancel(id: string, signal: AbortSignal) {
    await this.delay(signal);
    // DELETE is idempotent, including an expired or missing session.
    const parts = await this.store.entries<ServerPart>(`part:${id}:`);
    for (const part of parts) await this.store.delete(part.key);
    await this.store.delete(`upload:${id}`);
  }
  async getFile(id: string): Promise<UploadFileRecord | undefined> {
    const file = await this.store.get<UploadFileRecord>(`file:${id}`);
    if (file?.status === "VERIFYING" && file.verifyAt <= this.now()) {
      file.status =
        file.expectedSha256 === file.actualSha256 ? "READY" : "CORRUPT";
      await this.store.put(`file:${id}`, file);
    }
    return file;
  }
  async listFiles(): Promise<UploadFileRecord[]> {
    const rows = await this.store.entries<UploadFileRecord>("file:");
    const files = await Promise.all(
      rows.map((row) => this.getFile(row.value.id)),
    );
    return files.filter((file): file is UploadFileRecord => !!file);
  }
}
