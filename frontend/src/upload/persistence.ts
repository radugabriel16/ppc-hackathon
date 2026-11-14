import type { KeyValueStorage, SavedUpload } from "./types";
import { CATEGORIES, REGIONS } from "../data/models";

const KEY = "filegrid.uploads.v1";
export function scopedStorage(
  storage: KeyValueStorage,
  scope: string,
): KeyValueStorage {
  const key = (value: string) => `${scope}:${value}`;
  return {
    getItem: (name) => storage.getItem(key(name)),
    setItem: (name, value) => storage.setItem(key(name), value),
    removeItem: (name) => storage.removeItem(key(name)),
  };
}
export function savedUploads(storage: KeyValueStorage): SavedUpload[] {
  const raw = storage.getItem(KEY);
  if (!raw) return [];
  try {
    const items: unknown = JSON.parse(raw);
    if (!Array.isArray(items)) return [];
    return items.filter(
      (x): x is SavedUpload =>
        typeof x === "object" &&
        x !== null &&
        typeof x.uploadId === "string" &&
        typeof x.fingerprint === "string" &&
        typeof x.fileName === "string" &&
        Number.isSafeInteger(x.chunkSize) &&
        x.chunkSize > 0 &&
        Number.isSafeInteger(x.sizeBytes) &&
        x.sizeBytes >= 0 &&
        Number.isFinite(x.lastModified) &&
        CATEGORIES.includes(x.category) &&
        REGIONS.includes(x.region),
    );
  } catch {
    return [];
  }
}
export function saveUpload(storage: KeyValueStorage, upload: SavedUpload) {
  storage.setItem(
    KEY,
    JSON.stringify([
      ...savedUploads(storage).filter((x) => x.uploadId !== upload.uploadId),
      upload,
    ]),
  );
}
export function forgetUpload(storage: KeyValueStorage, id: string) {
  storage.setItem(
    KEY,
    JSON.stringify(savedUploads(storage).filter((x) => x.uploadId !== id)),
  );
}
