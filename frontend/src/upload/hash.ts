import { createSHA256 } from "hash-wasm";

// Incremental hashing keeps memory bounded independently of file size.
export async function digestBlob(
  blob: Blob,
  signal?: AbortSignal,
): Promise<string> {
  const hash = await createSHA256();
  hash.init();
  for (let offset = 0; offset < blob.size; offset += 1024 * 1024) {
    signal?.throwIfAborted();
    const buffer = await blob.slice(offset, offset + 1024 * 1024).arrayBuffer();
    signal?.throwIfAborted();
    hash.update(new Uint8Array(buffer));
  }
  signal?.throwIfAborted();
  return hash.digest("hex");
}
