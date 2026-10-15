import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, api } from "../api";
import type { UploadItem } from "../useUploads";
import { NewSnapshot } from "./NewSnapshot";

type Uploads = React.ComponentProps<typeof NewSnapshot>["uploads"];

const done = (id: string, name: string): UploadItem => ({ id, name, size: 100, loaded: 100, status: "done" });
const uploading = (id: string, name: string): UploadItem => ({ id, name, size: 100, loaded: 40, status: "uploading" });

function uploadsWith(items: UploadItem[]): Uploads {
  return {
    items,
    add: vi.fn(),
    remove: vi.fn(),
    clear: vi.fn(),
    doneIds: items.filter((i) => i.status === "done").map((i) => i.id),
    busy: items.some((i) => i.status === "uploading"),
  };
}

afterEach(() => vi.restoreAllMocks());

test("starts with the drop zone and a disabled Create button", () => {
  render(<NewSnapshot uploads={uploadsWith([])} onCreated={vi.fn()} />);
  expect(screen.getByRole("button", { name: /Drop Burp XML exports/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create snapshot" })).toBeDisabled();
});

test("files picked in the drop zone are handed to the uploads", async () => {
  const uploads = uploadsWith([]);
  const { container } = render(<NewSnapshot uploads={uploads} onCreated={vi.fn()} />);
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  await userEvent.upload(input, new File(["<items/>"], "history.xml"));
  expect(uploads.add).toHaveBeenCalledTimes(1);
});

test("the name is prefilled from the first file and stays editable", async () => {
  render(<NewSnapshot uploads={uploadsWith([done("u1", "history.xml")])} onCreated={vi.fn()} />);
  const name = screen.getByLabelText("Snapshot name");
  expect(name).toHaveValue("history");
  await userEvent.clear(name);
  await userEvent.type(name, "Treasury");
  expect(name).toHaveValue("Treasury");
});

test("Create sends the name and finished uploads, once, then clears and reports", async () => {
  let finish!: (s: unknown) => void;
  const create = vi.spyOn(api, "createSnapshot").mockImplementation(
    () => new Promise((resolve) => { finish = resolve as (s: unknown) => void; }),
  );
  const uploads = uploadsWith([done("u1", "a.xml"), done("u2", "b.xml")]);
  const onCreated = vi.fn();
  render(<NewSnapshot uploads={uploads} onCreated={onCreated} />);
  const button = screen.getByRole("button", { name: "Create snapshot" });
  await userEvent.dblClick(button);
  expect(create).toHaveBeenCalledTimes(1);
  expect(create).toHaveBeenCalledWith("a", ["u1", "u2"]);
  expect(screen.getByRole("button", { name: "Validating…" })).toBeDisabled();
  const snapshot = { id: "s1", name: "a" };
  finish(snapshot);
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(snapshot));
  expect(uploads.clear).toHaveBeenCalled();
});

test("Create waits for uploads that are still running", () => {
  render(<NewSnapshot uploads={uploadsWith([done("u1", "a.xml"), uploading("u2", "b.xml")])} onCreated={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Create snapshot" })).toBeDisabled();
});

test("a validation error is shown, and the stale uploads are discarded", async () => {
  vi.spyOn(api, "createSnapshot").mockRejectedValue(new ApiError(422, "no usable items in the uploaded export(s)"));
  const uploads = uploadsWith([done("u1", "a.xml")]);
  const onCreated = vi.fn();
  render(<NewSnapshot uploads={uploads} onCreated={onCreated} />);
  await userEvent.click(screen.getByRole("button", { name: "Create snapshot" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("no usable items in the uploaded export(s)");
  expect(screen.getByText(/uploads were discarded/)).toBeInTheDocument();
  expect(uploads.clear).toHaveBeenCalled();
  expect(onCreated).not.toHaveBeenCalled();
});

test("chips show progress and errors, and can be removed", async () => {
  const items: UploadItem[] = [
    uploading("u1", "big.xml"),
    { id: "u2", name: "empty.xml", size: 0, loaded: 0, status: "error", error: "This file is empty" },
  ];
  const uploads = uploadsWith(items);
  render(<NewSnapshot uploads={uploads} onCreated={vi.fn()} />);
  expect(screen.getByRole("progressbar", { name: "Upload progress for big.xml" })).toHaveAttribute("aria-valuenow", "40");
  expect(screen.getByText("This file is empty")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Remove big.xml" }));
  expect(uploads.remove).toHaveBeenCalledWith("u1");
});

test("with several files, the order hint explains that later files win", () => {
  render(<NewSnapshot uploads={uploadsWith([done("u1", "a.xml"), done("u2", "b.xml")])} onCreated={vi.fn()} />);
  expect(screen.getByText(/later files override earlier ones/i)).toBeInTheDocument();
});
