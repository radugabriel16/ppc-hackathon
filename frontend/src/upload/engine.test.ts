import { describe, expect, it, vi } from "vitest";
import { AppError } from "../data/errors";
import { abortableSleep, retryAfterMs, UploadEngine } from "./engine";
import { FakeUploadTransport, MemoryDemoStore } from "./fake-transport";
import { digestBlob } from "./hash";
import { savedUploads } from "./persistence";
import type { EngineOptions } from "./engine";
import type { KeyValueStorage, UploadEvent, UploadSnapshot } from "./types";

class MemoryStorage implements KeyValueStorage {
  data = new Map<string, string>();
  getItem(key: string) {
    return this.data.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.data.set(key, value);
  }
  removeItem(key: string) {
    this.data.delete(key);
  }
}
function seededRandom(seed: number) {
  return () => {
    seed = (1664525 * seed + 1013904223) >>> 0;
    return seed / 4294967296;
  };
}
const file = (size = 4096 * 21 + 37, name = "inspection.mp4") =>
  new File(
    [Uint8Array.from({ length: size }, (_, i) => (i * 29) % 256)],
    name,
    { lastModified: 1730000000000 },
  );
const input = {
  category: "DRONE_VIDEO" as const,
  metadata: { region: "BANAT" as const },
};
function setup(
  extra: Partial<EngineOptions> = {},
  serverOptions: Partial<
    ConstructorParameters<typeof FakeUploadTransport>[0]
  > = {},
) {
  const store = new MemoryDemoStore();
  const server = new FakeUploadTransport({
    store,
    chunkSize: 4096,
    latencyMs: 0,
    failureRate: 0,
    ...serverOptions,
  });
  const storage = new MemoryStorage();
  const sleep = vi.fn(async (_ms: number, signal: AbortSignal) => {
    signal.throwIfAborted();
  });
  const options: EngineOptions = {
    transport: server,
    hasher: { digest: digestBlob },
    storage,
    sleep,
    baseDelayMs: 1,
    ...extra,
  };
  return { server, storage, options, sleep, store };
}

describe("incremental SHA-256", () => {
  it("matches standard vectors, including empty and multiple 1 MB blocks", async () => {
    expect(await digestBlob(new Blob(["abc"]))).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
    expect(await digestBlob(new Blob([]))).toBe(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    );
    const big = new Blob([new Uint8Array(1024 * 1024 * 2 + 7)]);
    const native = await crypto.subtle.digest(
      "SHA-256",
      await big.arrayBuffer(),
    );
    expect(await digestBlob(big)).toBe(
      [...new Uint8Array(native)]
        .map((x) => x.toString(16).padStart(2, "0"))
        .join(""),
    );
  });
});
describe("upload engine against an in-memory fake server", () => {
  it("preserves paused state when paused at the initial status event", async () => {
    const { options, server } = setup();
    const engine = new UploadEngine(file(20), input, options);
    const put = vi.spyOn(server, "putPart");
    const unsubscribe = engine.subscribe((event) => {
      if (event.type === "progress") engine.pause();
    });
    await engine.start();
    expect(engine.getSnapshot().state).toBe("paused");
    expect(put).not.toHaveBeenCalled();
    unsubscribe();
    await engine.resume();
    expect(engine.getSnapshot().state).toBe("verifying");
  });
  it.each([7, 42, 131])(
    "survives 20%% random failures and dropped acknowledgements (seed %i)",
    async (seed) => {
      const { server, options, storage } = setup(
        { maxRetries: 15 },
        { failureRate: 0.2, random: seededRandom(seed) },
      );
      const source = file(4096 * 60 + 123);
      const engine = new UploadEngine(source, input, options);
      const events: UploadEvent[] = [];
      engine.subscribe((event) => events.push(event));
      let concurrent = 0;
      let peak = 0;
      const delegate = server.putPart.bind(server);
      vi.spyOn(server, "putPart").mockImplementation(async (...args) => {
        concurrent++;
        peak = Math.max(peak, concurrent);
        try {
          return await delegate(...args);
        } finally {
          concurrent--;
        }
      });
      await engine.start();
      expect(engine.getSnapshot()).toMatchObject({
        state: "verifying",
        sentBytes: source.size,
        totalBytes: source.size,
      });
      expect(engine.getSnapshot().retries).toBeGreaterThan(0);
      expect(peak).toBe(3);
      expect(events.map((x) => x.type)).toEqual(
        expect.arrayContaining(["state", "progress", "speed", "retries"]),
      );
      const progress = events
        .filter((x) => x.type === "progress")
        .map((x) => x.snapshot.sentBytes);
      expect(progress).toEqual([...progress].sort((a, b) => a - b));
      expect(Math.max(...progress)).toBe(source.size);
      expect(savedUploads(storage)).toEqual([]);
      const result = await server.getFile(engine.getSnapshot().fileId!);
      expect(result?.actualSha256).toBe(await digestBlob(source));
    },
  );
  it("resumes after reload by GET status and sends only missing parts, even after an acknowledgement was lost", async () => {
    const { server, options, store, storage } = setup();
    const source = file();
    const engine = new UploadEngine(source, input, options);
    engine.subscribe((event) => {
      if (event.type === "progress" && event.snapshot.sentBytes >= 4096 * 3)
        engine.pause();
    });
    await engine.start();
    expect(engine.getSnapshot().state).toBe("paused");
    const saved = savedUploads(storage)[0];
    expect(saved.fingerprint).toContain(source.name);
    // Mimic a server accept just before a browser connection disappears.
    const body = source.slice(4096 * 4, 4096 * 5);
    await server.putPart(
      saved.uploadId,
      5,
      body,
      await digestBlob(body),
      new AbortController().signal,
    );
    // New engine AND transport, same server disk and browser localStorage.
    const reloadedServer = new FakeUploadTransport({
      store,
      failureRate: 0,
      latencyMs: 0,
    });
    const before = await reloadedServer.getStatus(
      saved.uploadId,
      new AbortController().signal,
    );
    const calls: string[] = [];
    const status = reloadedServer.getStatus.bind(reloadedServer);
    vi.spyOn(reloadedServer, "getStatus").mockImplementation(
      async (...args) => {
        calls.push("GET");
        return status(...args);
      },
    );
    const put = reloadedServer.putPart.bind(reloadedServer);
    const sent: number[] = [];
    vi.spyOn(reloadedServer, "putPart").mockImplementation(async (...args) => {
      calls.push("PUT");
      sent.push(args[1]);
      return put(...args);
    });
    const resumed = new UploadEngine(
      source,
      input,
      { ...options, transport: reloadedServer },
      saved,
    );
    await resumed.start();
    expect(calls[0]).toBe("GET");
    expect(resumed.getSnapshot().state).toBe("verifying");
    expect(sent).toHaveLength(before.totalParts - before.receivedParts.length);
    expect(sent.some((n) => before.receivedParts.includes(n))).toBe(false);
  });
  it("supports pause and resume on the same instance without starting a second run", async () => {
    const { options } = setup();
    const engine = new UploadEngine(file(), input, options);
    let paused = false;
    engine.subscribe((event) => {
      if (
        !paused &&
        event.type === "progress" &&
        event.snapshot.sentBytes > 0
      ) {
        paused = true;
        engine.pause();
      }
    });
    const run = engine.start();
    expect(engine.start()).toBe(run);
    await run;
    expect(engine.getSnapshot().state).toBe("paused");
    await engine.resume();
    expect(engine.getSnapshot().state).toBe("verifying");
  });
  it("cancels in-flight work and deletes persisted session and server parts", async () => {
    const { options, storage, server } = setup();
    const engine = new UploadEngine(file(), input, options);
    engine.subscribe((event) => {
      if (event.type === "progress" && event.snapshot.sentBytes > 0)
        engine.pause();
    });
    await engine.start();
    const id = savedUploads(storage)[0].uploadId;
    await engine.cancel();
    expect(engine.getSnapshot().state).toBe("cancelled");
    expect(savedUploads(storage)).toEqual([]);
    await expect(
      server.getStatus(id, new AbortController().signal),
    ).rejects.toMatchObject({ status: 404 });
    await engine.resume();
    expect(engine.getSnapshot().state).toBe("cancelled");
  });
  it("rejects a different file before sending parts", async () => {
    const { options, server, storage } = setup();
    const engine = new UploadEngine(file(), input, options);
    engine.subscribe((event) => {
      if (event.type === "progress" && event.snapshot.sentBytes > 0)
        engine.pause();
    });
    await engine.start();
    const saved = savedUploads(storage)[0];
    const spy = vi.spyOn(server, "putPart");
    const resumed = new UploadEngine(
      file(123, "wrong.mp4"),
      input,
      options,
      saved,
    );
    await resumed.start();
    expect(resumed.getSnapshot()).toMatchObject({
      state: "failed",
      error: expect.stringContaining("does not match"),
    });
    expect(spy).not.toHaveBeenCalled();
  });
  it("honors Retry-After and uses exponential backoff with jitter", async () => {
    const { options, sleep, server } = setup({
      baseDelayMs: 100,
      random: () => 0.5,
    });
    const fault = (retryAfter?: string) =>
      new AppError(
        503,
        { code: "BUSY", message: "Busy", requestId: "req-123" },
        retryAfter,
      );
    vi.spyOn(server, "putPart")
      .mockRejectedValueOnce(fault("8"))
      .mockRejectedValueOnce(fault())
      .mockRejectedValueOnce(fault());
    const engine = new UploadEngine(file(10), input, options);
    await engine.start();
    expect(sleep.mock.calls.map((x) => x[0])).toEqual([8000, 200, 400]);
    expect(engine.getSnapshot().retries).toBe(3);
    expect(engine.getSnapshot().state).toBe("verifying");
    expect(
      retryAfterMs(
        "Fri, 14 Nov 2025 12:00:08 GMT",
        Date.parse("2025-11-14T12:00:00Z"),
      ),
    ).toBe(8000);
    expect(retryAfterMs("bad", 0)).toBe(0);
  });
  it("fails on 422 without retrying or completing and includes requestId", async () => {
    const { options, server } = setup();
    vi.spyOn(server, "putPart").mockRejectedValue(
      new AppError(422, {
        code: "HASH_MISMATCH",
        message: "Part hash mismatch",
        requestId: "req-hash",
      }),
    );
    const complete = vi.spyOn(server, "complete");
    const engine = new UploadEngine(file(10), input, options);
    await engine.start();
    expect(engine.getSnapshot()).toMatchObject({
      state: "failed",
      retries: 0,
      error: expect.stringContaining("req-hash"),
    });
    expect(complete).not.toHaveBeenCalled();
  });
  it("the fake server really checks raw part hashes and implements idempotent PUT", async () => {
    const { server } = setup();
    const blob = new Blob(["abc"]);
    const signal = new AbortController().signal;
    const session = await server.create(
      { ...input, fileName: "a", sizeBytes: blob.size },
      signal,
    );
    await expect(
      server.putPart(session.uploadId, 1, blob, "wrong", signal),
    ).rejects.toMatchObject({ status: 422 });
    const sha = await digestBlob(blob);
    expect(
      await server.putPart(session.uploadId, 1, blob, sha, signal),
    ).toEqual(await server.putPart(session.uploadId, 1, blob, sha, signal));
    expect(
      (await server.getStatus(session.uploadId, signal)).receivedParts,
    ).toEqual([1]);
  });
  it.each([false, true])(
    "transitions VERIFYING to READY/CORRUPT (corrupt=%s)",
    async (corrupt) => {
      let now = 1730000000000;
      const { options, server } = setup({}, { now: () => now, verifyMs: 500 });
      const engine = new UploadEngine(
        file(20),
        { ...input, metadata: { ...input.metadata, simulateCorrupt: corrupt } },
        options,
      );
      await engine.start();
      const id = engine.getSnapshot().fileId!;
      expect((await server.getFile(id))?.status).toBe("VERIFYING");
      now += 501;
      expect((await server.getFile(id))?.status).toBe(
        corrupt ? "CORRUPT" : "READY",
      );
    },
  );
  it("retries completion safely if the response is lost after server acceptance", async () => {
    const { options, server } = setup();
    const complete = server.complete.bind(server);
    vi.spyOn(server, "complete").mockImplementationOnce(async (...args) => {
      await complete(...args);
      throw new TypeError("Connection dropped");
    });
    const engine = new UploadEngine(file(20), input, options);
    await engine.start();
    expect(engine.getSnapshot().state).toBe("verifying");
    expect(await server.listFiles()).toHaveLength(1);
  });
  it("stops after the retry budget and can be resumed later", async () => {
    const { options, server } = setup({ maxRetries: 2 });
    const spy = vi
      .spyOn(server, "putPart")
      .mockRejectedValue(new TypeError("offline"));
    const engine = new UploadEngine(file(20), input, options);
    await engine.start();
    expect(engine.getSnapshot()).toMatchObject({ state: "failed", retries: 2 });
    expect(spy).toHaveBeenCalledTimes(3);
    spy.mockRestore();
    await engine.resume();
    expect(engine.getSnapshot().state).toBe("verifying");
  });
  it("uploads an empty file without inventing a part", async () => {
    const { options, server } = setup();
    const spy = vi.spyOn(server, "putPart");
    const engine = new UploadEngine(file(0), input, options);
    await engine.start();
    expect(engine.getSnapshot().state).toBe("verifying");
    expect(spy).not.toHaveBeenCalled();
  });
  it("aborts a retry wait immediately on pause", async () => {
    const { options, server } = setup({
      sleep: abortableSleep,
      baseDelayMs: 60000,
    });
    vi.spyOn(server, "putPart").mockRejectedValue(new TypeError("offline"));
    const engine = new UploadEngine(file(20), input, options);
    const waiting = new Promise<void>((resolve) =>
      engine.subscribe((event) => {
        if (event.type === "retries") {
          queueMicrotask(() => {
            engine.pause();
            resolve();
          });
        }
      }),
    );
    const run = engine.start();
    await waiting;
    await run;
    expect(engine.getSnapshot().state).toBe("paused");
  });
  it("captures snapshots without mutating previously emitted events", async () => {
    const { options } = setup();
    const engine = new UploadEngine(file(), input, options);
    const snapshots: UploadSnapshot[] = [];
    engine.subscribe((event) => snapshots.push(event.snapshot));
    await engine.start();
    expect(snapshots[0].state).toBe("idle");
    expect(snapshots.at(-1)?.state).toBe("verifying");
  });
});
