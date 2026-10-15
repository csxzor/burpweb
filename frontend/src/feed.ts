import type { EventMsg, Tier } from "./types";

export const MAX_ROWS = 500;

export type TierFilter = "ALL" | Tier;

export interface FeedRow {
  id: number;
  tier: Tier;
  method: string;
  url: string;
  status: number | null;
  item: string | null;
  ts: number;
}
export interface MissEntry { key: string; count: number }

export interface FeedState {
  rows: FeedRow[]; // newest first, at most MAX_ROWS
  counts: Record<TierFilter, number>; // every event ever seen, not only the retained rows
  misses: MissEntry[];
  nextId: number;
}

export type FeedAction = { type: "event"; event: EventMsg } | { type: "clear" };

export const emptyFeed = (): FeedState => ({
  rows: [],
  counts: { ALL: 0, EXACT: 0, FALLBACK: 0, HEAD: 0, MISS: 0, BLOCKED: 0 },
  misses: [],
  nextId: 1,
});

type RowInput = Omit<FeedRow, "id">;

function addRow(state: FeedState, row: RowInput): FeedState {
  return {
    rows: [{ id: state.nextId, ...row }, ...state.rows].slice(0, MAX_ROWS),
    counts: { ...state.counts, ALL: state.counts.ALL + 1, [row.tier]: state.counts[row.tier] + 1 },
    misses: state.misses,
    nextId: state.nextId + 1,
  };
}

export function feedReducer(state: FeedState, action: FeedAction): FeedState {
  if (action.type === "clear") return emptyFeed();
  const e = action.event;
  switch (e.type) {
    case "request":
      return addRow(state, { tier: e.tier, method: e.method, url: e.url, status: e.status, item: e.item, ts: e.ts });
    case "blocked":
      return addRow(state, { tier: "BLOCKED", method: "TCP", url: e.address, status: null, item: null, ts: e.ts });
    case "misses":
      return { ...state, misses: e.misses };
    default:
      return state; // "replay" and "toast" are handled by the app shell
  }
}

export function visibleRows(rows: FeedRow[], filter: TierFilter): FeedRow[] {
  return filter === "ALL" ? rows : rows.filter((r) => r.tier === filter);
}
