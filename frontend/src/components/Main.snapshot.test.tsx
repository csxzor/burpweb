import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, api } from "../api";
import type { Snapshot } from "../types";
import { Main } from "./Main";

const snap = (id: string, name: string): Snapshot => ({
  id, name, created: "2026-10-15T10:00:00Z", files: [{ name: "a.xml", size: 10 }],
  stats: { items: 5, origins: 1, skipped: 0, malformed: [] }, damaged: false,
});

beforeEach(() => {
  vi.spyOn(api, "snapshots").mockResolvedValue([snap("a", "Treasury"), snap("b", "Acme")]);
  vi.spyOn(api, "state").mockResolvedValue({ vault: "unlocked", replay: null });
});
afterEach(() => vi.restoreAllMocks());

test("the newest snapshot opens first, and selecting another switches the stage", async () => {
  render(<Main onLocked={vi.fn()} />);
  expect(await screen.findByRole("heading", { name: "Acme" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Treasury/ }));
  expect(await screen.findByRole("heading", { name: "Treasury" })).toBeInTheDocument();
});

test("Start replay calls the API and marks the snapshot live", async () => {
  const start = vi.spyOn(api, "startReplay").mockResolvedValue({ snapshot_id: "b", port: 8081, running: true });
  render(<Main onLocked={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Start replay" }));
  expect(start).toHaveBeenCalledWith("b", 8081);
  expect(await screen.findByText("Replaying on 127.0.0.1:8081")).toBeInTheDocument();
  expect(screen.getAllByRole("img", { name: "Replaying" }).length).toBeGreaterThan(0);
});

test("a failed start is shown as a toast and the button comes back", async () => {
  vi.spyOn(api, "startReplay").mockRejectedValue(new ApiError(409, "address already in use"));
  render(<Main onLocked={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Start replay" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("address already in use");
  await waitFor(() => expect(screen.getByRole("button", { name: "Start replay" })).toBeEnabled());
});

test("Stop and Open Firefox call the API", async () => {
  vi.spyOn(api, "state").mockResolvedValue({
    vault: "unlocked",
    replay: { running: true, port: 8081, snapshot_id: "b" },
  });
  const stop = vi.spyOn(api, "stopReplay").mockResolvedValue(undefined);
  const open = vi.spyOn(api, "openBrowser").mockResolvedValue({ ok: true });
  render(<Main onLocked={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Open Firefox" }));
  expect(open).toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Stop" }));
  expect(stop).toHaveBeenCalled();
  expect(await screen.findByRole("button", { name: "Start replay" })).toBeInTheDocument();
});

test("a missing Firefox is reported with the server's message", async () => {
  vi.spyOn(api, "state").mockResolvedValue({
    vault: "unlocked",
    replay: { running: true, port: 8081, snapshot_id: "b" },
  });
  vi.spyOn(api, "openBrowser").mockRejectedValue(new ApiError(409, "firefox/certutil not available"));
  render(<Main onLocked={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Open Firefox" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("firefox/certutil not available");
});
