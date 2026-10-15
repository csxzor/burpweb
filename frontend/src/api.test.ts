import { ApiError, api, setAuthHandlers } from "./api";

function respond(status: number, body?: unknown, statusText = "") {
  const res = new Response(body === undefined ? null : JSON.stringify(body), { status, statusText });
  return vi.fn().mockResolvedValue(res);
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAuthHandlers({});
});

test("sends JSON with a content type and returns the parsed body", async () => {
  const fetchMock = respond(200, { vault: "new", replay: null });
  vi.stubGlobal("fetch", fetchMock);
  await expect(api.state()).resolves.toEqual({ vault: "new", replay: null });
  await api.createVault("correct horse battery");
  const [url, init] = fetchMock.mock.calls[1];
  expect(url).toBe("/api/vault/create");
  expect(init.method).toBe("POST");
  expect(init.headers).toEqual({ "Content-Type": "application/json" });
  expect(JSON.parse(init.body)).toEqual({ passphrase: "correct horse battery" });
});

test("a 204 resolves to undefined", async () => {
  vi.stubGlobal("fetch", respond(204));
  await expect(api.remove("abc")).resolves.toBeUndefined();
});

test("errors carry the server's message and status", async () => {
  vi.stubGlobal("fetch", respond(422, { error: "no usable items" }));
  const err = await api.createSnapshot("n", ["u1"]).catch((e) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err).toMatchObject({ status: 422, message: "no usable items" });
});

test("a non-JSON error falls back to the status text", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 502, statusText: "Bad Gateway" })));
  await expect(api.state()).rejects.toMatchObject({ status: 502, message: "Bad Gateway" });
});

test("a 423 notifies the locked handler and still throws", async () => {
  const locked = vi.fn();
  setAuthHandlers({ locked });
  vi.stubGlobal("fetch", respond(423, { error: "library locked" }));
  await expect(api.snapshots()).rejects.toMatchObject({ status: 423 });
  expect(locked).toHaveBeenCalledTimes(1);
});

test("a 403 notifies the forbidden handler; a 401 notifies neither", async () => {
  const locked = vi.fn();
  const forbidden = vi.fn();
  setAuthHandlers({ locked, forbidden });
  vi.stubGlobal("fetch", respond(403, { error: "missing or bad token" }));
  await expect(api.state()).rejects.toMatchObject({ status: 403 });
  vi.stubGlobal("fetch", respond(401, { error: "wrong passphrase" }));
  await expect(api.unlock("nope")).rejects.toMatchObject({ status: 401 });
  expect(forbidden).toHaveBeenCalledTimes(1);
  expect(locked).not.toHaveBeenCalled();
});

test("endpoints use the documented paths and verbs", async () => {
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200 })));
  vi.stubGlobal("fetch", fetchMock);
  await api.rename("s1", "New name");
  await api.addFiles("s1", ["u1", "u2"]);
  await api.startReplay("s1", 9000);
  await api.stopReplay();
  await api.openBrowser();
  await api.lock();
  const calls = fetchMock.mock.calls.map(([url, init]) => `${init.method} ${url}`);
  expect(calls).toEqual([
    "PATCH /api/snapshots/s1",
    "POST /api/snapshots/s1/files",
    "POST /api/replay",
    "DELETE /api/replay",
    "POST /api/browser",
    "POST /api/vault/lock",
  ]);
});
