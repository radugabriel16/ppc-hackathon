import { AppError, errorText } from "../data/errors";
import { forgetUpload, savedUploads, saveUpload } from "./persistence";
import type {
  HashService,
  KeyValueStorage,
  SavedUpload,
  UploadEvent,
  UploadInput,
  UploadSnapshot,
  UploadState,
  UploadTransport,
} from "./types";

export interface EngineOptions {
  transport: UploadTransport;
  hasher: HashService;
  storage: KeyValueStorage;
  random?: () => number;
  now?: () => number;
  baseDelayMs?: number;
  maxRetries?: number;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
}
export const abortableSleep = (
  ms: number,
  signal: AbortSignal,
): Promise<void> =>
  new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const finish = () => {
      signal.removeEventListener("abort", abort);
      resolve();
    };
    const timer = setTimeout(finish, ms);
    const abort = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal.addEventListener("abort", abort, { once: true });
  });
export function retryAfterMs(value: string | undefined, now: number): number {
  if (!value) return 0;
  const seconds = Number(value);
  return Number.isFinite(seconds)
    ? Math.max(0, seconds * 1000)
    : Math.max(0, Date.parse(value) - now) || 0;
}

// No React, network globals, or generated-client dependency. Part numbers are 1-based.
export class UploadEngine {
  private snapshot: UploadSnapshot;
  private listeners = new Set<(event: UploadEvent) => void>();
  private controller?: AbortController;
  private running?: Promise<void>;
  private session?: SavedUpload;
  private cancelled = false;
  private startedAt = 0;
  private baselineBytes = 0;
  constructor(
    private file: File,
    private input: Omit<UploadInput, "fileName" | "sizeBytes">,
    private options: EngineOptions,
    resume?: SavedUpload,
  ) {
    this.session = resume;
    this.snapshot = {
      state: "idle",
      sentBytes: 0,
      totalBytes: file.size,
      speed: 0,
      retries: 0,
    };
  }
  getSnapshot = () => this.snapshot;
  subscribe = (listener: (event: UploadEvent) => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private emit(type: UploadEvent["type"], update: Partial<UploadSnapshot>) {
    this.snapshot = { ...this.snapshot, ...update };
    for (const listener of this.listeners)
      listener({ type, snapshot: this.snapshot });
  }
  private state(state: UploadState) {
    this.emit("state", { state, speed: 0 });
  }
  start(): Promise<void> {
    if (this.cancelled || this.snapshot.state === "verifying")
      return Promise.resolve();
    if (this.running) return this.running;
    this.controller = new AbortController();
    this.emit("state", { error: undefined });
    this.running = this.run(this.controller.signal)
      .catch((error) => {
        if (this.controller?.signal.aborted) return;
        this.emit("state", {
          state: "failed",
          speed: 0,
          error: errorText(error),
        });
      })
      .finally(() => {
        this.running = undefined;
      });
    return this.running;
  }
  pause() {
    if (!["verifying", "cancelled", "idle"].includes(this.snapshot.state)) {
      this.controller?.abort();
      this.state("paused");
    }
  }
  async resume() {
    await this.running;
    return this.start();
  }
  async cancel() {
    this.cancelled = true;
    this.controller?.abort();
    await this.running;
    try {
      if (this.session)
        await this.retry(
          (s) => this.options.transport.cancel(this.session!.uploadId, s),
          new AbortController().signal,
        );
      if (this.session)
        forgetUpload(this.options.storage, this.session.uploadId);
      this.state("cancelled");
    } catch (error) {
      this.cancelled = false;
      this.emit("state", { state: "failed", error: errorText(error) });
    }
  }
  private async retry<T>(
    operation: (signal: AbortSignal) => Promise<T>,
    signal: AbortSignal,
  ): Promise<T> {
    for (let attempt = 0; ; attempt++) {
      signal.throwIfAborted();
      try {
        return await operation(signal);
      } catch (error) {
        signal.throwIfAborted();
        const retryable =
          error instanceof TypeError ||
          (error instanceof AppError &&
            [0, 408, 429, 500, 502, 503, 504].includes(error.status));
        if (!retryable || attempt >= (this.options.maxRetries ?? 7))
          throw error;
        this.emit("retries", { retries: this.snapshot.retries + 1 });
        const jitter = 0.5 + (this.options.random ?? Math.random)();
        const delay =
          Math.min(30000, (this.options.baseDelayMs ?? 500) * 2 ** attempt) *
          jitter;
        const after =
          error instanceof AppError
            ? retryAfterMs(error.retryAfter, (this.options.now ?? Date.now)())
            : 0;
        await (this.options.sleep ?? abortableSleep)(
          Math.max(delay, after),
          signal,
        );
      }
    }
  }
  private async run(signal: AbortSignal) {
    this.state("hashing");
    const firstHash = await this.options.hasher.digest(
      this.file.slice(0, 1024 * 1024),
      signal,
    );
    const fingerprint = JSON.stringify([
      this.file.name,
      this.file.size,
      this.file.lastModified,
      firstHash,
    ]);
    if (this.session && this.session.fingerprint !== fingerprint)
      throw new Error(
        "File does not match the saved upload. Select the original file.",
      );
    this.session ??= savedUploads(this.options.storage).find(
      (x) =>
        x.fingerprint === fingerprint &&
        x.category === this.input.category &&
        x.region === this.input.metadata.region,
    );
    const fullHash = await this.options.hasher.digest(this.file, signal);
    signal.throwIfAborted();
    let chunkSize: number;
    let totalParts: number;
    if (!this.session) {
      // Creation is deliberately not retried: the contract has no create idempotency key.
      const created = await this.options.transport.create(
        { ...this.input, fileName: this.file.name, sizeBytes: this.file.size },
        signal,
      );
      chunkSize = created.chunkSize;
      totalParts = created.totalParts;
      this.session = {
        uploadId: created.uploadId,
        fingerprint,
        chunkSize,
        fileName: this.file.name,
        sizeBytes: this.file.size,
        lastModified: this.file.lastModified,
        category: this.input.category,
        region: this.input.metadata.region,
        simulateCorrupt: this.input.metadata.simulateCorrupt,
      };
      saveUpload(this.options.storage, this.session);
    } else {
      chunkSize = this.session.chunkSize;
      totalParts = Math.ceil(this.file.size / chunkSize);
    }
    if (
      !Number.isSafeInteger(chunkSize) ||
      chunkSize <= 0 ||
      totalParts !== Math.ceil(this.file.size / chunkSize)
    )
      throw new Error("Invalid upload negotiation.");
    const status = await this.retry(
      (s) => this.options.transport.getStatus(this.session!.uploadId, s),
      signal,
    );
    signal.throwIfAborted();
    if (status.totalParts !== totalParts)
      throw new Error("Server part count changed. Start a new upload.");
    const received = new Set(status.receivedParts);
    if (
      [...received].some((n) => !Number.isInteger(n) || n < 1 || n > totalParts)
    )
      throw new Error("Invalid server part list.");
    const partBytes = (n: number) =>
      Math.min(chunkSize, this.file.size - (n - 1) * chunkSize);
    this.baselineBytes = [...received].reduce(
      (sum, n) => sum + partBytes(n),
      0,
    );
    this.startedAt = (this.options.now ?? Date.now)();
    this.emit("progress", { sentBytes: this.baselineBytes });
    signal.throwIfAborted();
    this.state("uploading");
    const missing = Array.from({ length: totalParts }, (_, i) => i + 1).filter(
      (n) => !received.has(n),
    );
    let next = 0;
    let failure: unknown;
    const worker = async () => {
      while (next < missing.length && !failure) {
        const part = missing[next++];
        try {
          signal.throwIfAborted();
          const body = this.file.slice(
            (part - 1) * chunkSize,
            part * chunkSize,
          );
          const hash = await this.options.hasher.digest(body, signal);
          await this.retry(
            (s) =>
              this.options.transport.putPart(
                this.session!.uploadId,
                part,
                body,
                hash,
                s,
              ),
            signal,
          );
          signal.throwIfAborted();
          this.emit("progress", {
            sentBytes: this.snapshot.sentBytes + body.size,
          });
          signal.throwIfAborted();
          this.emit("speed", {
            speed:
              (this.snapshot.sentBytes - this.baselineBytes) /
              Math.max(
                0.001,
                ((this.options.now ?? Date.now)() - this.startedAt) / 1000,
              ),
          });
        } catch (error) {
          failure = error;
        }
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(3, missing.length) }, worker),
    );
    if (failure) throw failure;
    signal.throwIfAborted();
    this.state("completing");
    const result = await this.retry(
      (s) =>
        this.options.transport.complete(this.session!.uploadId, fullHash, s),
      signal,
    );
    signal.throwIfAborted();
    forgetUpload(this.options.storage, this.session.uploadId);
    this.emit("state", { state: "verifying", fileId: result.fileId, speed: 0 });
  }
}
