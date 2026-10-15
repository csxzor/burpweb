import { MAX_ROWS, emptyFeed, feedReducer, visibleRows, type FeedState } from "./feed";
import type { EventMsg } from "./types";

const request = (n: number, tier: "EXACT" | "MISS" = "EXACT"): EventMsg => ({
  type: "request", tier, method: "GET", url: `https://shop.invalid/p${n}`, status: tier === "MISS" ? 404 : 200, item: null, ts: n,
});
const apply = (state: FeedState, event: EventMsg) => feedReducer(state, { type: "event", event });

test("rows are newest first", () => {
  let s = emptyFeed();
  s = apply(s, request(1));
  s = apply(s, request(2));
  expect(s.rows.map((r) => r.url)).toEqual(["https://shop.invalid/p2", "https://shop.invalid/p1"]);
  expect(s.rows[0].id).toBeGreaterThan(s.rows[1].id);
});

test("test_feed_caps_rows_but_keeps_counting", () => {
  let s = emptyFeed();
  for (let i = 0; i < MAX_ROWS + 120; i++) s = apply(s, request(i, i % 4 === 0 ? "MISS" : "EXACT"));
  expect(s.rows).toHaveLength(MAX_ROWS);
  expect(s.rows[0].url).toBe(`https://shop.invalid/p${MAX_ROWS + 119}`);
  expect(s.counts.ALL).toBe(MAX_ROWS + 120);
  expect(s.counts.MISS + s.counts.EXACT).toBe(MAX_ROWS + 120);
  expect(s.counts.MISS).toBe(155);
});

test("blocked events become BLOCKED rows", () => {
  const s = apply(emptyFeed(), { type: "blocked", address: "10.0.0.5:22", ts: 1 });
  expect(s.rows[0]).toMatchObject({ tier: "BLOCKED", method: "TCP", url: "10.0.0.5:22", status: null });
  expect(s.counts.BLOCKED).toBe(1);
});

test("misses events replace the list, and other events leave the feed alone", () => {
  let s = apply(emptyFeed(), { type: "misses", misses: [{ key: "GET https://x/a", count: 2 }], ts: 1 });
  expect(s.misses).toEqual([{ key: "GET https://x/a", count: 2 }]);
  s = apply(s, { type: "replay", running: true, snapshot_id: "a", port: 1, ts: 2 });
  s = apply(s, { type: "toast", level: "info", message: "x", ts: 3 });
  expect(s.rows).toHaveLength(0);
  expect(s.misses).toHaveLength(1);
});

test("clear resets everything", () => {
  let s = apply(emptyFeed(), request(1));
  s = feedReducer(s, { type: "clear" });
  expect(s).toEqual(emptyFeed());
});

test("visibleRows filters by tier", () => {
  let s = emptyFeed();
  s = apply(s, request(1, "EXACT"));
  s = apply(s, request(2, "MISS"));
  expect(visibleRows(s.rows, "ALL")).toHaveLength(2);
  expect(visibleRows(s.rows, "MISS").map((r) => r.tier)).toEqual(["MISS"]);
});
