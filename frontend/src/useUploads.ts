import { useCallback, useRef, useState } from "react";
import { uploadFile, type UploadHandle } from "./uploads";

export type UploadStatus = "uploading" | "done" | "error";

export interface UploadItem {
  id: string;
  name: string;
  size: number;
  loaded: number;
  status: UploadStatus;
  error?: string;
}

export type MakeUpload = (id: string, file: File, onProgress: (loaded: number, total: number) => void) => UploadHandle;

export function useUploads(makeUpload: MakeUpload = uploadFile) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const handles = useRef(new Map<string, UploadHandle>());

  const patch = useCallback((id: string, change: (item: UploadItem) => UploadItem) => {
    setItems((all) => all.map((item) => (item.id === id ? change(item) : item)));
  }, []);

  const add = useCallback(
    (files: File[]) => {
      for (const file of files) {
        const id = crypto.randomUUID();
        if (file.size === 0) {
          setItems((all) => [
            ...all,
            { id, name: file.name, size: 0, loaded: 0, status: "error", error: "This file is empty" },
          ]);
          continue;
        }
        setItems((all) => [...all, { id, name: file.name, size: file.size, loaded: 0, status: "uploading" }]);
        const handle = makeUpload(id, file, (loaded) => patch(id, (item) => ({ ...item, loaded })));
        handles.current.set(id, handle);
        handle.promise
          .then(() => patch(id, (item) => ({ ...item, status: "done", loaded: item.size })))
          .catch((error: Error) =>
            patch(id, (item) => (item.status === "uploading" ? { ...item, status: "error", error: error.message } : item)),
          )
          .finally(() => handles.current.delete(id));
      }
    },
    [makeUpload, patch],
  );

  const remove = useCallback((id: string) => {
    handles.current.get(id)?.abort();
    handles.current.delete(id);
    setItems((all) => all.filter((item) => item.id !== id));
  }, []);

  const clear = useCallback(() => {
    handles.current.forEach((handle) => handle.abort());
    handles.current.clear();
    setItems([]);
  }, []);

  return {
    items,
    add,
    remove,
    clear,
    doneIds: items.filter((item) => item.status === "done").map((item) => item.id),
    busy: items.some((item) => item.status === "uploading"),
  };
}
