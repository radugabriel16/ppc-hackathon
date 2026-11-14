import { digestBlob } from "./hash";

const jobs = new Map<number, AbortController>();
self.onmessage = async (
  event: MessageEvent<{ id: number; blob?: Blob; cancel?: boolean }>,
) => {
  const { id, blob, cancel } = event.data;
  if (cancel) {
    jobs.get(id)?.abort();
    return;
  }
  if (!blob) return;
  const controller = new AbortController();
  jobs.set(id, controller);
  try {
    self.postMessage({ id, hash: await digestBlob(blob, controller.signal) });
  } catch (error) {
    self.postMessage({
      id,
      error: error instanceof Error ? error.message : "Hashing failed",
    });
  } finally {
    jobs.delete(id);
  }
};
