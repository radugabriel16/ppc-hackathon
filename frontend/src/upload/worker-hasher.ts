import type { HashService } from "./types";

export class WorkerHasher implements HashService {
  private worker = new Worker(new URL("./hash.worker.ts", import.meta.url), {
    type: "module",
  });
  private sequence = 0;
  private failure?: Error;
  private pending = new Map<
    number,
    {
      resolve: (hash: string) => void;
      reject: (error: Error) => void;
      cleanup: () => void;
    }
  >();
  constructor() {
    this.worker.onmessage = (
      event: MessageEvent<{ id: number; hash: string; error?: string }>,
    ) => {
      const job = this.pending.get(event.data.id);
      if (!job) return;
      job.cleanup();
      this.pending.delete(event.data.id);
      if (event.data.error) job.reject(new Error(event.data.error));
      else job.resolve(event.data.hash);
    };
    this.worker.onerror = () => {
      this.failure = new Error(
        "Hash worker failed. Reload the page to try again.",
      );
      this.rejectAll(this.failure);
    };
  }
  digest(blob: Blob, signal: AbortSignal): Promise<string> {
    signal.throwIfAborted();
    if (this.failure) return Promise.reject(this.failure);
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const abort = () => {
        this.worker.postMessage({ id, cancel: true });
        this.pending.delete(id);
        signal.removeEventListener("abort", abort);
        reject(new DOMException("Aborted", "AbortError"));
      };
      this.pending.set(id, {
        resolve,
        reject,
        cleanup: () => signal.removeEventListener("abort", abort),
      });
      signal.addEventListener("abort", abort, { once: true });
      try {
        this.worker.postMessage({ id, blob });
      } catch (error) {
        signal.removeEventListener("abort", abort);
        this.pending.delete(id);
        reject(error);
      }
    });
  }
  private rejectAll(error: Error) {
    for (const job of this.pending.values()) {
      job.cleanup();
      job.reject(error);
    }
    this.pending.clear();
  }
  dispose() {
    this.failure = new Error("Hash worker disposed");
    this.rejectAll(this.failure);
    this.worker.terminate();
  }
}
