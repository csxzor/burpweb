import { setAuthHandlers } from "./api";
import { uploadFile } from "./uploads";

class FakeXhr {
  upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 0;
  responseText = "";
  opened: [string, string] | null = null;
  sent: unknown = null;
  aborted = false;
  open(method: string, url: string) {
    this.opened = [method, url];
  }
  send(body: unknown) {
    this.sent = body;
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
}
const make = (xhr: FakeXhr) => () => xhr as unknown as XMLHttpRequest;
const file = new File(["<items/>"], "my history.xml");

afterEach(() => setAuthHandlers({}));

test("PUTs the raw file to the upload endpoint with an encoded name", () => {
  const xhr = new FakeXhr();
  uploadFile("abc-123", file, () => {}, make(xhr));
  expect(xhr.opened).toEqual(["PUT", "/api/uploads/abc-123?name=my%20history.xml"]);
  expect(xhr.sent).toBe(file);
});

test("reports progress and resolves on a 2xx", async () => {
  const xhr = new FakeXhr();
  const progress = vi.fn();
  const handle = uploadFile("u1", file, progress, make(xhr));
  xhr.upload.onprogress?.({ lengthComputable: true, loaded: 4, total: 8 } as ProgressEvent);
  xhr.status = 200;
  xhr.onload?.();
  await expect(handle.promise).resolves.toBeUndefined();
  expect(progress).toHaveBeenNthCalledWith(1, 4, 8);
  expect(progress).toHaveBeenLastCalledWith(file.size, file.size);
});

test("rejects with the server's message on an error status", async () => {
  const xhr = new FakeXhr();
  const handle = uploadFile("u1", file, () => {}, make(xhr));
  xhr.status = 409;
  xhr.responseText = JSON.stringify({ error: "upload id already used" });
  xhr.onload?.();
  await expect(handle.promise).rejects.toThrow("upload id already used");
});

test("a 423 notifies the locked handler", async () => {
  const locked = vi.fn();
  setAuthHandlers({ locked });
  const xhr = new FakeXhr();
  const handle = uploadFile("u1", file, () => {}, make(xhr));
  xhr.status = 423;
  xhr.responseText = "{}";
  xhr.onload?.();
  await expect(handle.promise).rejects.toThrow("Upload failed (HTTP 423)");
  expect(locked).toHaveBeenCalledTimes(1);
});

test("network errors and aborts reject", async () => {
  const a = new FakeXhr();
  const failing = uploadFile("u1", file, () => {}, make(a));
  a.onerror?.();
  await expect(failing.promise).rejects.toThrow("Network error");
  const b = new FakeXhr();
  const cancelled = uploadFile("u2", file, () => {}, make(b));
  cancelled.abort();
  await expect(cancelled.promise).rejects.toThrow("cancelled");
  expect(b.aborted).toBe(true);
});
