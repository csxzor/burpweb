import { act, renderHook } from "@testing-library/react";
import type { UploadHandle } from "./uploads";
import { useUploads } from "./useUploads";

interface Pending {
  id: string;
  file: File;
  progress: (loaded: number, total: number) => void;
  resolve: () => void;
  reject: (e: Error) => void;
  aborted: boolean;
}

function harness() {
  const pending: Pending[] = [];
  const makeUpload = (id: string, file: File, progress: (l: number, t: number) => void): UploadHandle => {
    let resolve!: () => void;
    let reject!: (e: Error) => void;
    const promise = new Promise<void>((res, rej) => {
      resolve = res;
      reject = rej;
    });
    const entry: Pending = { id, file, progress, resolve, reject, aborted: false };
    pending.push(entry);
    return {
      promise,
      abort: () => {
        entry.aborted = true;
        reject(new Error("Upload cancelled"));
      },
    };
  };
  return { pending, makeUpload };
}
const xml = (name: string, text = "<items/>") => new File([text], name);

test("adds chips, tracks progress and completion", async () => {
  const { pending, makeUpload } = harness();
  const { result } = renderHook(() => useUploads(makeUpload));
  act(() => result.current.add([xml("a.xml"), xml("b.xml")]));
  expect(result.current.items.map((i) => i.status)).toEqual(["uploading", "uploading"]);
  expect(result.current.busy).toBe(true);
  expect(pending[0].id).toMatch(/^[A-Za-z0-9_-]+$/); // valid for the backend's route

  act(() => pending[0].progress(3, 8));
  expect(result.current.items[0].loaded).toBe(3);

  await act(async () => pending[0].resolve());
  expect(result.current.items[0]).toMatchObject({ status: "done", loaded: result.current.items[0].size });
  expect(result.current.busy).toBe(true);
  await act(async () => pending[1].resolve());
  expect(result.current.busy).toBe(false);
  expect(result.current.doneIds).toEqual(pending.map((p) => p.id));
});

test("a failed upload is marked with its error", async () => {
  const { pending, makeUpload } = harness();
  const { result } = renderHook(() => useUploads(makeUpload));
  act(() => result.current.add([xml("a.xml")]));
  await act(async () => pending[0].reject(new Error("Network error while uploading")));
  expect(result.current.items[0]).toMatchObject({ status: "error", error: "Network error while uploading" });
  expect(result.current.doneIds).toEqual([]);
});

test("test_empty_file_is_reported_not_uploaded", () => {
  const { pending, makeUpload } = harness();
  const { result } = renderHook(() => useUploads(makeUpload));
  act(() => result.current.add([xml("empty.xml", "")]));
  expect(pending).toHaveLength(0);
  expect(result.current.items[0]).toMatchObject({ status: "error", error: "This file is empty" });
});

test("remove aborts an in-flight upload and drops the chip without an error", async () => {
  const { pending, makeUpload } = harness();
  const { result } = renderHook(() => useUploads(makeUpload));
  act(() => result.current.add([xml("a.xml")]));
  const id = result.current.items[0].id;
  await act(async () => result.current.remove(id));
  expect(pending[0].aborted).toBe(true);
  expect(result.current.items).toEqual([]);
});

test("clear aborts everything and empties the list", async () => {
  const { pending, makeUpload } = harness();
  const { result } = renderHook(() => useUploads(makeUpload));
  act(() => result.current.add([xml("a.xml"), xml("b.xml")]));
  await act(async () => result.current.clear());
  expect(pending.every((p) => p.aborted)).toBe(true);
  expect(result.current.items).toEqual([]);
});
