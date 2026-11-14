import "fake-indexeddb/auto";
import { describe, expect, it } from "vitest";
import { FakeUploadTransport, IndexedDemoStore } from "./fake-transport";
import { digestBlob } from "./hash";

describe("demo server durability", () => {
  it("preserves simultaneously uploaded blobs across new transport/store instances", async () => {
    const signal = new AbortController().signal;
    const server = new FakeUploadTransport({
      store: new IndexedDemoStore(),
      failureRate: 0,
      latencyMs: 0,
      chunkSize: 3,
    });
    const session = await server.create(
      {
        fileName: "test.bin",
        sizeBytes: 9,
        category: "METER_READING",
        metadata: { region: "MUNTENIA" },
      },
      signal,
    );
    const blobs = ["abc", "def", "ghi"].map((x) => new Blob([x]));
    await Promise.all(
      blobs.map(async (blob, i) =>
        server.putPart(
          session.uploadId,
          i + 1,
          blob,
          await digestBlob(blob),
          signal,
        ),
      ),
    );
    const reloaded = new FakeUploadTransport({
      store: new IndexedDemoStore(),
      failureRate: 0,
      latencyMs: 0,
    });
    expect(
      (await reloaded.getStatus(session.uploadId, signal)).receivedParts,
    ).toEqual([1, 2, 3]);
    const hash = await digestBlob(new Blob(blobs));
    const result = await reloaded.complete(session.uploadId, hash, signal);
    expect((await reloaded.getFile(result.fileId))?.actualSha256).toBe(hash);
    await reloaded.cancel(session.uploadId, signal);
  });
});
