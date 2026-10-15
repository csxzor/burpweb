export interface FileInfo { name: string; size: number }
export interface OriginRow { origin: string; items: number; paths: number }
export interface Stats {
  items: number;
  origins: number;
  skipped: number;
  malformed: [number, string][];
  by_origin?: OriginRow[];
}
export interface Snapshot {
  id: string;
  name: string;
  created: string;
  files: FileInfo[];
  stats: Stats;
  damaged: boolean;
}

export type VaultState = "new" | "locked" | "unlocked";
export interface ReplayState { running: boolean; port: number | null; snapshot_id: string | null }
export interface AppState { vault: VaultState; replay: ReplayState | null }

export type Tier = "EXACT" | "FALLBACK" | "HEAD" | "MISS" | "BLOCKED";

export type EventMsg =
  | { type: "request"; tier: Tier; method: string; url: string; status: number; item: string | null; ts: number }
  | { type: "blocked"; address: string; ts: number }
  | { type: "replay"; running: boolean; snapshot_id: string | null; port: number | null; ts: number }
  | { type: "misses"; misses: { key: string; count: number }[]; ts: number }
  | { type: "toast"; level: "error" | "info"; message: string; ts: number };
