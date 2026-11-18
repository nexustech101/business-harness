/** The upload dialog's queue; `UploadDialog` renders it. */
import { useState } from "react";
import { errorMessage } from "../../api/client";
import { useUploadDocument } from "../../api/library";
import type { DocumentDetail } from "../../api/types";

export type UploadItem = { file: File; state: "queued" | "uploading" | "done" | "failed"; result?: DocumentDetail; error?: string };

/**
 * Files to upload, each with its own state, result or error. `start` sends the ones not yet done one after another
 * (the API reads and indexes one document per upload slot).
 */
export function useUploadQueue() {
  const upload = useUploadDocument();
  const [items, setItems] = useState<UploadItem[]>([]);
  const [running, setRunning] = useState(false);

  const add = (files: FileList | null) => {
    const added = Array.from(files ?? [], (file): UploadItem => ({ file, state: "queued" })); // copy now: the input is reset next
    setItems((all) => [...all, ...added]);
  };
  const remove = (i: number) => setItems((all) => all.filter((_, j) => j !== i));
  const update = (i: number, change: Partial<UploadItem>) => setItems((all) => all.map((item, j) => (j === i ? { ...item, ...change } : item)));

  const start = async () => {
    setRunning(true);
    for (const [i, item] of items.entries()) {
      if (item.state === "done") continue;
      update(i, { state: "uploading", error: undefined });
      try {
        update(i, { state: "done", result: await upload.mutateAsync(item.file) });
      } catch (error) {
        update(i, { state: "failed", error: errorMessage(error) });
      }
    }
    setRunning(false);
  };

  return { items, add, remove, start, clear: () => setItems([]), running, remaining: items.filter((i) => i.state !== "done").length };
}
