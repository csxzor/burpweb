import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Snapshot, View } from "../types";
import { Library } from "./Library";

const snap = (id: string, name: string, extra: Partial<Snapshot> = {}): Snapshot => ({
  id,
  name,
  created: "2026-10-15T10:00:00Z",
  files: [{ name: "a.xml", size: 10 }],
  stats: { items: 617, origins: 4, skipped: 30, malformed: [] },
  damaged: false,
  ...extra,
});

function setup(overrides: Partial<React.ComponentProps<typeof Library>> = {}) {
  const props = {
    snapshots: [snap("a", "Treasury"), snap("b", "Acme portal")],
    view: { kind: "snapshot", id: "a" } as View,
    replayingId: null as string | null,
    onSelect: vi.fn(),
    onRename: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn().mockResolvedValue(undefined),
    onLock: vi.fn(),
    ...overrides,
  };
  render(<Library {...props} />);
  return props;
}

test("lists snapshots with their stats and marks the selected one", () => {
  setup();
  const treasury = screen.getByRole("button", { name: /Treasury/ });
  expect(treasury).toHaveTextContent("617 items · 4 origins");
  expect(treasury.closest("li")).toHaveAttribute("aria-current", "true");
  expect(screen.getByRole("button", { name: /Acme portal/ }).closest("li")).not.toHaveAttribute("aria-current");
});

test("test_snapshot_name_is_rendered_as_text", () => {
  const evil = '<img src=x onerror="alert(1)">';
  setup({ snapshots: [snap("a", evil)] });
  expect(screen.getByText(evil)).toBeInTheDocument();
  expect(document.querySelector("img")).toBeNull();
});

test("selecting a snapshot and the new-snapshot button report the view", async () => {
  const { onSelect } = setup();
  await userEvent.click(screen.getByRole("button", { name: /Acme portal/ }));
  expect(onSelect).toHaveBeenCalledWith({ kind: "snapshot", id: "b" });
  await userEvent.click(screen.getByRole("button", { name: "+ New snapshot" }));
  expect(onSelect).toHaveBeenCalledWith({ kind: "new" });
});

test("rename saves on Enter and cancels on Escape", async () => {
  const { onRename } = setup();
  await userEvent.click(screen.getByRole("button", { name: "Rename" }));
  const field = screen.getByLabelText("Snapshot name");
  await userEvent.clear(field);
  await userEvent.type(field, "Treasury Q3{Enter}");
  expect(onRename).toHaveBeenCalledWith("a", "Treasury Q3");
  await waitFor(() => expect(screen.queryByLabelText("Snapshot name")).toBeNull());

  vi.mocked(onRename).mockClear();
  await userEvent.click(screen.getByRole("button", { name: "Rename" }));
  await userEvent.type(screen.getByLabelText("Snapshot name"), "x{Escape}");
  expect(onRename).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("Snapshot name")).toBeNull();
});

test("a failed rename keeps the editor open with the error", async () => {
  setup({ onRename: vi.fn().mockRejectedValue(new Error("snapshot damaged")) });
  await userEvent.click(screen.getByRole("button", { name: "Rename" }));
  await userEvent.type(screen.getByLabelText("Snapshot name"), "x{Enter}");
  expect(await screen.findByRole("alert")).toHaveTextContent("snapshot damaged");
  expect(screen.getByLabelText("Snapshot name")).toBeInTheDocument();
});

test("delete asks first, naming the snapshot, and only then deletes", async () => {
  const { onDelete } = setup();
  await userEvent.click(screen.getByRole("button", { name: "Delete" }));
  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveTextContent("Treasury");
  await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(onDelete).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

  await userEvent.click(screen.getByRole("button", { name: "Delete" }));
  await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }));
  expect(onDelete).toHaveBeenCalledWith("a");
});

test("damaged snapshots are flagged and cannot be renamed", () => {
  setup({ snapshots: [snap("a", "Broken", { damaged: true, stats: { items: 0, origins: 0, skipped: 0, malformed: [] } })] });
  expect(screen.getByText("Damaged")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Rename" })).toBeNull();
  expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
});

test("the replaying snapshot shows a live dot, and Lock is wired", async () => {
  const { onLock } = setup({ replayingId: "b" });
  expect(screen.getAllByRole("img", { name: "Replaying" })).toHaveLength(1);
  expect(screen.getByRole("button", { name: /Acme portal/ })).toContainElement(screen.getByRole("img", { name: "Replaying" }));
  await userEvent.click(screen.getByRole("button", { name: "Lock" }));
  expect(onLock).toHaveBeenCalled();
});

test("an empty library explains what to do", () => {
  setup({ snapshots: [], view: { kind: "new" } });
  expect(screen.getByText(/No snapshots yet/)).toBeInTheDocument();
});
