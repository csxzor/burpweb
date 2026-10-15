import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, api } from "../api";
import type { ReplayState, Snapshot } from "../types";
import type { MakeUpload } from "../useUploads";
import { SnapshotView } from "./SnapshotView";

const base: Snapshot = {
  id: "s1",
  name: "Treasury",
  created: "2026-10-15T10:00:00Z",
  files: [
    { name: "history.xml", size: 164518301 },
    { name: "frontend.xml", size: 346037 },
  ],
  stats: {
    items: 617,
    origins: 2,
    skipped: 30,
    malformed: [[1, "bad status line 'junk'"]],
    by_origin: [
      { origin: "https://shop.invalid", items: 600, paths: 72 },
      { origin: "https://fonts.gstatic.com", items: 17, paths: 3 },
    ],
  },
  damaged: false,
};

type Props = React.ComponentProps<typeof SnapshotView>;
function setup(overrides: Partial<Props> = {}) {
  const props: Props = {
    snapshot: base,
    replay: null,
    onStart: vi.fn().mockResolvedValue(undefined),
    onStop: vi.fn().mockResolvedValue(undefined),
    onOpenBrowser: vi.fn().mockResolvedValue(undefined),
    onUpdated: vi.fn(),
    ...overrides,
  };
  const view = render(<SnapshotView {...props} />);
  return { props, ...view };
}
const running = (id = "s1", port = 8081): ReplayState => ({ running: true, port, snapshot_id: id });
const instantUpload: MakeUpload = (_id, file, progress) => {
  progress(file.size, file.size);
  return { promise: Promise.resolve(), abort: () => {} };
};

afterEach(() => vi.restoreAllMocks());

test("shows the stats, the origins table and the files in order", () => {
  setup();
  expect(screen.getByRole("heading", { name: "Treasury" })).toBeInTheDocument();
  expect(screen.getByText("617")).toBeInTheDocument();
  expect(screen.getByText("30")).toBeInTheDocument();
  const rows = within(screen.getByRole("table")).getAllByRole("row");
  expect(rows).toHaveLength(3); // header + two origins
  expect(rows[1]).toHaveTextContent("600");
  expect(rows[1]).toHaveTextContent("https://shop.invalid");
  const files = screen.getAllByRole("listitem").filter((li) => li.closest("ol.files"));
  expect(files[0]).toHaveTextContent("history.xml");
  expect(files[0]).toHaveTextContent("164.5 MB");
  expect(files[1]).toHaveTextContent("frontend.xml");
});

test("malformed items are listed with their reasons", async () => {
  setup();
  const details = screen.getByText(/1 malformed item skipped/);
  await userEvent.click(details);
  expect(screen.getByText(/bad status line 'junk'/)).toBeInTheDocument();
});

test("Start uses the default port, or the one typed", async () => {
  const { props } = setup();
  await userEvent.click(screen.getByRole("button", { name: "Start replay" }));
  expect(props.onStart).toHaveBeenLastCalledWith(8081);
  const port = screen.getByLabelText("Replay port");
  await userEvent.clear(port);
  await userEvent.type(port, "9000");
  await userEvent.click(screen.getByRole("button", { name: "Start replay" }));
  expect(props.onStart).toHaveBeenLastCalledWith(9000);
});

test.each(["", "abc", "0", "70000", "80.5"])("an invalid port (%s) disables Start", async (value) => {
  setup();
  const port = screen.getByLabelText("Replay port");
  await userEvent.clear(port);
  if (value) await userEvent.type(port, value);
  expect(screen.getByRole("button", { name: "Start replay" })).toBeDisabled();
});

test("test_start_button_is_disabled_while_pending", async () => {
  let finish!: () => void;
  const onStart = vi.fn().mockImplementation(() => new Promise<void>((resolve) => { finish = resolve; }));
  setup({ onStart });
  const button = screen.getByRole("button", { name: "Start replay" });
  await userEvent.dblClick(button);
  expect(onStart).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Starting…" })).toBeDisabled();
  finish();
  await waitFor(() => expect(screen.getByRole("button", { name: "Start replay" })).toBeEnabled());
});

test("a running replay shows its address with Open Firefox and Stop", async () => {
  const { props } = setup({ replay: running() });
  expect(screen.getByText("Replaying on 127.0.0.1:8081")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Start replay" })).toBeNull();
  expect(screen.queryByLabelText("Replay port")).toBeNull(); // the address replaces the port field
  await userEvent.click(screen.getByRole("button", { name: "Open Firefox" }));
  expect(props.onOpenBrowser).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "Stop" }));
  expect(props.onStop).toHaveBeenCalledTimes(1);
});

test("when another snapshot is replaying, starting this one says it will switch", () => {
  setup({ replay: running("other") });
  expect(screen.getByText(/another snapshot is replaying/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Start replay" })).toBeEnabled();
});

test("a damaged snapshot cannot be started", () => {
  setup({ snapshot: { ...base, damaged: true } });
  expect(screen.getByText(/damaged and can't be replayed/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Start replay" })).toBeDisabled();
});

test("added files are sent to the snapshot and the updated snapshot is reported", async () => {
  const updated = { ...base, stats: { ...base.stats, items: 700 } };
  const addFiles = vi.spyOn(api, "addFiles").mockResolvedValue(updated);
  const { props, container } = setup({ makeUpload: instantUpload, replay: running() });
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  await userEvent.upload(input, new File(["<items/>"], "later.xml"));
  expect(await screen.findByText(/restart the replay/i)).toBeInTheDocument();
  const button = screen.getByRole("button", { name: "Add to snapshot" });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
  await waitFor(() => expect(props.onUpdated).toHaveBeenCalledWith(updated));
  expect(addFiles).toHaveBeenCalledWith("s1", [expect.any(String)]);
});

test("a rejected add shows the error and discards the stale uploads", async () => {
  vi.spyOn(api, "addFiles").mockRejectedValue(new ApiError(422, "no usable items"));
  const { container } = setup({ makeUpload: instantUpload });
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  await userEvent.upload(input, new File(["<items/>"], "bad.xml"));
  const button = await screen.findByRole("button", { name: "Add to snapshot" });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
  expect(await screen.findByRole("alert")).toHaveTextContent("no usable items");
  await waitFor(() => expect(screen.queryByText("bad.xml")).toBeNull()); // after the chip's exit animation
});
