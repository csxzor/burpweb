import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api";
import type { Snapshot } from "../types";
import { FakeWebSocket } from "../test-utils";
import { Main } from "./Main";

const snap = (id: string, name: string): Snapshot => ({
  id, name, created: "2026-10-15T10:00:00Z", files: [{ name: "a.xml", size: 10 }],
  stats: { items: 5, origins: 1, skipped: 0, malformed: [] }, damaged: false,
});
const request = (url: string, tier = "EXACT") => ({
  type: "request", tier, method: "GET", url, status: 200, item: null, ts: 1,
});

beforeEach(() => {
  vi.spyOn(api, "snapshots").mockResolvedValue([snap("a", "Treasury"), snap("b", "Acme")]);
  vi.spyOn(api, "state").mockResolvedValue({ vault: "unlocked", replay: null });
});
afterEach(() => vi.restoreAllMocks());

async function mounted(onLocked = vi.fn()) {
  render(<Main onLocked={onLocked} />);
  await screen.findByRole("heading", { name: "Acme" });
  const socket = FakeWebSocket.instances[0];
  act(() => socket.open());
  return { socket, onLocked };
}

test("connects to the events socket and shows requests as they arrive", async () => {
  const { socket } = await mounted();
  expect(socket.url).toMatch(/\/api\/events$/);
  act(() => socket.emit(request("https://shop.invalid/one")));
  act(() => socket.emit(request("https://shop.invalid/two")));
  const feed = screen.getByLabelText("Live feed");
  const rows = within(feed).getAllByRole("listitem");
  expect(rows[0]).toHaveTextContent("https://shop.invalid/two");
  expect(rows[1]).toHaveTextContent("https://shop.invalid/one");
});

test("a replay event marks the snapshot live and clears the old feed", async () => {
  const { socket } = await mounted();
  act(() => socket.emit(request("https://shop.invalid/old")));
  act(() => socket.emit({ type: "replay", running: true, snapshot_id: "b", port: 8081, ts: 2 }));
  expect(await screen.findByText("Replaying on 127.0.0.1:8081")).toBeInTheDocument();
  expect(screen.getAllByRole("img", { name: "Replaying" }).length).toBeGreaterThan(0);
  expect(within(screen.getByLabelText("Live feed")).queryByText(/shop.invalid\/old/)).toBeNull();
  act(() => socket.emit({ type: "replay", running: false, snapshot_id: "b", port: null, ts: 3 }));
  expect(await screen.findByRole("button", { name: "Start replay" })).toBeInTheDocument();
});

test("server toasts are shown", async () => {
  const { socket } = await mounted();
  act(() => socket.emit({ type: "toast", level: "error", message: "address already in use (choose another port)", ts: 1 }));
  expect(await screen.findByRole("alert")).toHaveTextContent("address already in use");
});

test("misses events fill the Misses tab", async () => {
  const { socket } = await mounted();
  act(() => socket.emit({ type: "misses", misses: [{ key: "GET https://x.invalid/z", count: 2 }], ts: 1 }));
  await userEvent.click(screen.getByRole("tab", { name: /Misses/ }));
  expect(screen.getByText("GET https://x.invalid/z")).toBeInTheDocument();
});

test("a dropped socket re-checks the library: a locked one returns to the unlock screen", async () => {
  const { socket, onLocked } = await mounted();
  vi.mocked(api.state).mockResolvedValue({ vault: "locked", replay: null });
  act(() => socket.drop());
  await waitFor(() => expect(onLocked).toHaveBeenCalled());
});

test("a dropped socket on an unlocked library re-syncs the replay state", async () => {
  const { socket, onLocked } = await mounted();
  vi.mocked(api.state).mockResolvedValue({
    vault: "unlocked",
    replay: { running: true, port: 9001, snapshot_id: "b" },
  });
  act(() => socket.drop());
  expect(await screen.findByText("Replaying on 127.0.0.1:9001")).toBeInTheDocument();
  expect(onLocked).not.toHaveBeenCalled();
});
