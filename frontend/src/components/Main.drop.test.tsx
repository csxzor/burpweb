import { fireEvent, render, screen } from "@testing-library/react";
import { api } from "../api";
import type { Snapshot } from "../types";
import { Main } from "./Main";

class FakeXhr {
  upload = { onprogress: null };
  onload = null;
  onerror = null;
  onabort = null;
  open() {}
  send() {}
  abort() {}
}

const snap: Snapshot = {
  id: "a", name: "Treasury", created: "2026-10-15T10:00:00Z", files: [{ name: "a.xml", size: 10 }],
  stats: { items: 5, origins: 1, skipped: 0, malformed: [] }, damaged: false,
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("a file dropped anywhere in the window starts a new snapshot", async () => {
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  vi.spyOn(api, "snapshots").mockResolvedValue([snap]);
  vi.spyOn(api, "state").mockResolvedValue({ vault: "unlocked", replay: null });
  render(<Main onLocked={vi.fn()} />);
  await screen.findByRole("button", { name: /Treasury/ }); // the library is showing a snapshot
  const dropped = new File(["<items/>"], "history.xml");
  fireEvent.dragEnter(window, { dataTransfer: { types: ["Files"], files: [dropped] } });
  expect(screen.getByText("Drop Burp XML exports")).toBeInTheDocument(); // the full-window overlay
  fireEvent.drop(window, { dataTransfer: { types: ["Files"], files: [dropped] } });
  expect(await screen.findByText("history.xml")).toBeInTheDocument(); // a chip on the new-snapshot stage
  expect(screen.getByRole("button", { name: "Create snapshot" })).toBeInTheDocument();
});
