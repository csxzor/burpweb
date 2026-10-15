import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api";
import type { Snapshot } from "../types";
import { Main } from "./Main";

const snap = (id: string, name: string): Snapshot => ({
  id, name, created: "2026-10-15T10:00:00Z", files: [{ name: "a.xml", size: 10 }],
  stats: { items: 5, origins: 1, skipped: 0, malformed: [] }, damaged: false,
});

afterEach(() => vi.restoreAllMocks());

function mockApi(list: Snapshot[]) {
  vi.spyOn(api, "snapshots").mockResolvedValue(list);
  vi.spyOn(api, "state").mockResolvedValue({ vault: "unlocked", replay: null });
}

test("loads the library and shows each snapshot", async () => {
  mockApi([snap("a", "Treasury"), snap("b", "Acme")]);
  render(<Main onLocked={vi.fn()} />);
  expect(await screen.findByRole("button", { name: /Treasury/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Acme/ })).toBeInTheDocument();
});

test("deleting a snapshot removes it from the library", async () => {
  mockApi([snap("a", "Treasury"), snap("b", "Acme")]);
  const remove = vi.spyOn(api, "remove").mockResolvedValue(undefined);
  render(<Main onLocked={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: /Acme/ }));
  await userEvent.click(screen.getByRole("button", { name: "Delete" }));
  await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }));
  expect(remove).toHaveBeenCalledWith("b");
  await waitFor(() => expect(screen.queryByRole("button", { name: /Acme/ })).toBeNull());
  expect(screen.getByRole("button", { name: /Treasury/ })).toBeInTheDocument();
});

test("renaming updates the card", async () => {
  mockApi([snap("a", "Treasury")]);
  vi.spyOn(api, "rename").mockResolvedValue({ ...snap("a", "Treasury Q3") });
  render(<Main onLocked={vi.fn()} />);
  await screen.findByRole("button", { name: /Treasury/ });
  await userEvent.click(screen.getByRole("button", { name: "Rename" }));
  const field = screen.getByLabelText("Snapshot name");
  await userEvent.clear(field);
  await userEvent.type(field, "Treasury Q3{Enter}");
  expect(await screen.findByRole("button", { name: /Treasury Q3/ })).toBeInTheDocument();
});

test("Lock locks the library and reports it", async () => {
  mockApi([]);
  const lock = vi.spyOn(api, "lock").mockResolvedValue({ ok: true });
  const onLocked = vi.fn();
  render(<Main onLocked={onLocked} />);
  await userEvent.click(await screen.findByRole("button", { name: "Lock" }));
  await waitFor(() => expect(onLocked).toHaveBeenCalled());
  expect(lock).toHaveBeenCalled();
});

test("a failed load is shown instead of an empty library", async () => {
  vi.spyOn(api, "snapshots").mockRejectedValue(new Error("boom"));
  vi.spyOn(api, "state").mockResolvedValue({ vault: "unlocked", replay: null });
  render(<Main onLocked={vi.fn()} />);
  expect(await screen.findByText(/Couldn't load the library/)).toBeInTheDocument();
});
