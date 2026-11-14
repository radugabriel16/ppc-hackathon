import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkerHasher } from "./worker-hasher";

class FakeWorker {
  static latest: FakeWorker;
  onmessage?: (event: {
    data: { id: number; hash?: string; error?: string };
  }) => void;
  onerror?: () => void;
  postMessage = vi.fn();
  terminate = vi.fn();
  constructor() {
    FakeWorker.latest = this;
  }
}
beforeEach(() => vi.stubGlobal("Worker", FakeWorker));
afterEach(() => vi.unstubAllGlobals());
describe("worker hash adapter", () => {
  it("routes concurrently computed hashes by job id", async () => {
    const hasher = new WorkerHasher();
    const signal = new AbortController().signal;
    const first = hasher.digest(new Blob(["one"]), signal);
    const second = hasher.digest(new Blob(["two"]), signal);
    FakeWorker.latest.onmessage?.({ data: { id: 2, hash: "second" } });
    FakeWorker.latest.onmessage?.({ data: { id: 1, hash: "first" } });
    expect(await Promise.all([first, second])).toEqual(["first", "second"]);
    hasher.dispose();
  });
  it("cancels the worker job and ignores a late reply", async () => {
    const hasher = new WorkerHasher();
    const controller = new AbortController();
    const digest = hasher.digest(new Blob(["one"]), controller.signal);
    const rejected = expect(digest).rejects.toMatchObject({
      name: "AbortError",
    });
    controller.abort();
    await rejected;
    expect(FakeWorker.latest.postMessage).toHaveBeenCalledWith({
      id: 1,
      cancel: true,
    });
    FakeWorker.latest.onmessage?.({ data: { id: 1, hash: "too late" } });
    hasher.dispose();
  });
  it("fails pending and future jobs after worker failure instead of hanging", async () => {
    const hasher = new WorkerHasher();
    const signal = new AbortController().signal;
    const digest = hasher.digest(new Blob(["one"]), signal);
    const rejected = expect(digest).rejects.toThrow("Reload the page");
    FakeWorker.latest.onerror?.();
    await rejected;
    await expect(hasher.digest(new Blob(["two"]), signal)).rejects.toThrow(
      "Reload the page",
    );
    hasher.dispose();
  });
  it("disposal terminates the worker and rejects pending work", async () => {
    const hasher = new WorkerHasher();
    const digest = hasher.digest(
      new Blob(["one"]),
      new AbortController().signal,
    );
    const rejected = expect(digest).rejects.toThrow("disposed");
    hasher.dispose();
    await rejected;
    expect(FakeWorker.latest.terminate).toHaveBeenCalledTimes(1);
  });
});
