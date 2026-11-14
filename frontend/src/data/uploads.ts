import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSource } from "./context";
import { errorText } from "./errors";
import type { Category, Region } from "./models";
import { UploadEngine } from "../upload/engine";
import {
  forgetUpload,
  savedUploads,
  scopedStorage,
} from "../upload/persistence";
import { useSession } from "./hooks";
import { WorkerHasher } from "../upload/worker-hasher";
import type { SavedUpload, UploadSnapshot } from "../upload/types";
import type { FileUploadMetadata } from "../api/gen/types.gen";

export interface QueueItem {
  key: string;
  name: string;
  engine: UploadEngine;
  snapshot: UploadSnapshot;
}
export function useUploadQueue() {
  const source = useSource();
  const { data: session } = useSession();
  const scope = `${source.uploadScope ?? source.kind}:${session?.user.name ?? "anonymous"}`;
  const storage = useMemo(
    () =>
      scopedStorage(
        {
          getItem: (key) => localStorage.getItem(key),
          setItem: (key, value) => localStorage.setItem(key, value),
          removeItem: (key) => localStorage.removeItem(key),
        },
        scope,
      ),
    [scope],
  );
  const cache = useQueryClient();
  const [items, setItems] = useState<QueueItem[]>([]);
  const [error, setError] = useState("");
  const resources = useRef<{ engine: UploadEngine; unsubscribe: () => void }[]>(
    [],
  );
  const hasher = useRef<WorkerHasher | null>(null);
  const saved = useQuery({
    queryKey: ["saved-uploads", scope],
    queryFn: () => savedUploads(storage),
    refetchInterval: 1500,
  });
  const refresh = useCallback(() => {
    void cache.invalidateQueries({ queryKey: ["saved-uploads"] });
    void cache.invalidateQueries({ queryKey: ["files"] });
    void cache.invalidateQueries({ queryKey: ["statistics"] });
  }, [cache]);
  useEffect(
    () => () => {
      for (const resource of resources.current) {
        resource.engine.pause();
        resource.unsubscribe();
      }
      resources.current = [];
      hasher.current?.dispose();
      hasher.current = null;
    },
    [],
  );
  const add = (
    file: File,
    category: Category,
    region: Region,
    corrupt: boolean,
    resume?: SavedUpload,
    fileMetadata?: FileUploadMetadata,
  ) => {
    setError("");
    if (
      items.some(
        (x) =>
          x.name === file.name &&
          !["verifying", "cancelled"].includes(x.snapshot.state),
      )
    ) {
      setError("This file is already in the queue. Use its Resume button.");
      return;
    }
    try {
      hasher.current ??= new WorkerHasher();
      const engine = new UploadEngine(
        file,
        {
          category: resume?.category ?? category,
          metadata: {
            region: resume?.region ?? region,
            simulateCorrupt: resume?.simulateCorrupt ?? corrupt,
            fileMetadata: resume?.fileMetadata ?? fileMetadata,
          },
        },
        {
          transport: source.uploads,
          hasher: hasher.current,
          storage,
        },
        resume,
      );
      const key = crypto.randomUUID();
      const unsubscribe = engine.subscribe((event) => {
        setItems((current) =>
          current.map((item) =>
            item.key === key ? { ...item, snapshot: event.snapshot } : item,
          ),
        );
        if (event.type === "state") refresh();
      });
      resources.current.push({ engine, unsubscribe });
      setItems((current) => [
        ...current,
        { key, name: file.name, engine, snapshot: engine.getSnapshot() },
      ]);
      void engine.start();
    } catch (error) {
      setError(errorText(error));
    }
  };
  const discard = async (record: SavedUpload) => {
    setError("");
    try {
      await source.uploads.cancel(
        record.uploadId,
        new AbortController().signal,
      );
      forgetUpload(storage, record.uploadId);
      refresh();
    } catch (error) {
      setError(errorText(error));
    }
  };
  const dismiss = (key: string) => {
    items.find((item) => item.key === key)?.engine.pause();
    setItems((current) => current.filter((item) => item.key !== key));
    refresh();
  };
  return {
    items,
    saved: saved.data ?? [],
    savedError: saved.error,
    error,
    add,
    discard,
    dismiss,
  };
}
