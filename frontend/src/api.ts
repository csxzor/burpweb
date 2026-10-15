import type { AppState, Snapshot } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

interface AuthHandlers { locked?: () => void; forbidden?: () => void }
let handlers: AuthHandlers = {};

export function setAuthHandlers(next: AuthHandlers): void {
  handlers = next;
}

/** 423 means the library was locked elsewhere; 403 means this page's token is no longer valid. */
export function notifyAuthStatus(status: number): void {
  if (status === 423) handlers.locked?.();
  else if (status === 403) handlers.forbidden?.();
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (res.status === 204) return undefined as T;
  let data: { error?: string } | null = null;
  try {
    data = await res.json();
  } catch {
    // not JSON; fall back to the status text below
  }
  if (!res.ok) {
    notifyAuthStatus(res.status);
    throw new ApiError(res.status, data?.error ?? (res.statusText || `HTTP ${res.status}`));
  }
  return data as T;
}

export const api = {
  state: () => request<AppState>("GET", "/api/state"),
  createVault: (passphrase: string) => request<{ ok: true }>("POST", "/api/vault/create", { passphrase }),
  unlock: (passphrase: string) => request<{ ok: true }>("POST", "/api/vault/unlock", { passphrase }),
  lock: () => request<{ ok: true }>("POST", "/api/vault/lock", {}),
  snapshots: () => request<Snapshot[]>("GET", "/api/snapshots"),
  createSnapshot: (name: string, uploads: string[]) =>
    request<Snapshot>("POST", "/api/snapshots", { name, uploads }),
  addFiles: (id: string, uploads: string[]) =>
    request<Snapshot>("POST", `/api/snapshots/${id}/files`, { uploads }),
  rename: (id: string, name: string) => request<Snapshot>("PATCH", `/api/snapshots/${id}`, { name }),
  remove: (id: string) => request<void>("DELETE", `/api/snapshots/${id}`),
  startReplay: (snapshot_id: string, port?: number) =>
    request<{ snapshot_id: string; port: number; running: boolean }>("POST", "/api/replay", { snapshot_id, port }),
  stopReplay: () => request<void>("DELETE", "/api/replay"),
  openBrowser: () => request<{ ok: true }>("POST", "/api/browser", {}),
};
