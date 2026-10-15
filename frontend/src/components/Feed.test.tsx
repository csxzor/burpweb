import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { emptyFeed, feedReducer, type FeedState } from "../feed";
import type { EventMsg } from "../types";
import { Feed } from "./Feed";

// Vitest stubs CSS imports (even ?raw gives an empty string), so read the stylesheet from disk.
const feedCss = readFileSync(join(process.cwd(), "src/components/Feed.css"), "utf8"); // tests run from frontend/

const request = (n: number, tier: "EXACT" | "FALLBACK" | "MISS", url = `https://shop.invalid/p${n}`): EventMsg => ({
  type: "request", tier, method: "GET", url, status: tier === "MISS" ? 404 : 200,
  item: tier === "FALLBACK" ? "trjs #4" : null, ts: n,
});
const build = (events: EventMsg[]): FeedState =>
  events.reduce((state, event) => feedReducer(state, { type: "event", event }), emptyFeed());

function setup(overrides: Partial<React.ComponentProps<typeof Feed>> = {}) {
  const props = { state: emptyFeed(), status: "open" as const, running: true, onCopied: vi.fn(), ...overrides };
  render(<Feed {...props} />);
  return props;
}

afterEach(() => vi.restoreAllMocks());

test("empty states say what to do", () => {
  setup({ running: false });
  expect(screen.getByText(/Start a replay to see requests here/)).toBeInTheDocument();
});

test("a running replay with no traffic yet waits for requests", () => {
  setup({ running: true });
  expect(screen.getByText(/Waiting for requests/)).toBeInTheDocument();
});

test("rows are newest first and show badge, method, url, status and source item", () => {
  setup({ state: build([request(1, "EXACT"), request(2, "FALLBACK")]) });
  const rows = within(screen.getByRole("list", { name: "Requests" })).getAllByRole("listitem");
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent("FALLBACK");
  expect(rows[0]).toHaveTextContent("https://shop.invalid/p2");
  expect(rows[0]).toHaveTextContent("trjs #4");
  expect(rows[1]).toHaveTextContent("EXACT");
  expect(rows[1]).toHaveTextContent("200");
});

test("blocked connections appear as BLOCKED rows", () => {
  setup({ state: build([{ type: "blocked", address: "10.0.0.5:22", ts: 1 }]) });
  const row = screen.getByRole("listitem");
  expect(row).toHaveTextContent("BLOCKED");
  expect(row).toHaveTextContent("10.0.0.5:22");
});

test("filter chips show counts and narrow the list", async () => {
  setup({ state: build([request(1, "EXACT"), request(2, "MISS"), request(3, "EXACT")]) });
  expect(screen.getByRole("button", { name: "ALL 3" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "EXACT 2" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "MISS 1" }));
  const rows = within(screen.getByRole("list", { name: "Requests" })).getAllByRole("listitem");
  expect(rows).toHaveLength(1);
  expect(rows[0]).toHaveTextContent("MISS");
  expect(screen.getByRole("button", { name: "MISS 1" })).toHaveAttribute("aria-pressed", "true");
});

test("test_long_url_is_one_ellipsized_line", () => {
  const long = "https://shop.invalid/" + "a".repeat(600) + "?token=" + "b".repeat(300);
  setup({ state: build([request(1, "EXACT", long)]) });
  const url = document.querySelector(".row-url") as HTMLElement;
  expect(url).toHaveAttribute("title", long); // the full URL is one hover away
  const rule = /\.row-url\s*\{[^}]*\}/.exec(feedCss)![0];
  expect(rule).toMatch(/white-space:\s*nowrap/);
  expect(rule).toMatch(/overflow:\s*hidden/);
  expect(rule).toMatch(/text-overflow:\s*ellipsis/);
});

test("the Misses tab lists urls with counts and copies them all", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  const state = feedReducer(emptyFeed(), {
    type: "event",
    event: { type: "misses", ts: 1, misses: [{ key: "GET https://x.invalid/a", count: 3 }, { key: "GET https://x.invalid/b", count: 1 }] },
  });
  const { onCopied } = setup({ state });
  expect(screen.getByRole("tab", { name: /Misses/ })).toHaveTextContent("2");
  await userEvent.click(screen.getByRole("tab", { name: /Misses/ }));
  const rows = screen.getAllByRole("listitem");
  expect(rows[0]).toHaveTextContent("GET https://x.invalid/a");
  expect(rows[0]).toHaveTextContent("3");
  await userEvent.click(screen.getByRole("button", { name: "Copy all" }));
  expect(writeText).toHaveBeenCalledWith("GET https://x.invalid/a\nGET https://x.invalid/b");
  expect(onCopied).toHaveBeenCalledWith(2);
});

test("the Misses tab is reassuring when empty", async () => {
  setup();
  await userEvent.click(screen.getByRole("tab", { name: /Misses/ }));
  expect(screen.getByText(/everything so far came from the snapshot/i)).toBeInTheDocument();
});

test("a reconnecting pill appears while the socket is down", () => {
  setup({ status: "reconnecting" });
  expect(screen.getByRole("status")).toHaveTextContent("Reconnecting…");
});
