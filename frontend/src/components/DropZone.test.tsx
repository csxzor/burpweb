import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DropZone } from "./DropZone";

const TITLE = "Drop Burp XML exports or click to browse";
const file = (name = "a.xml") => new File(["<items/>"], name);

test("files chosen with the picker are reported", async () => {
  const onFiles = vi.fn();
  const { container } = render(<DropZone title={TITLE} onFiles={onFiles} />);
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  expect(input).toHaveAttribute("multiple");
  await userEvent.upload(input, [file("a.xml"), file("b.xml")]);
  expect(onFiles).toHaveBeenCalledTimes(1);
  expect(onFiles.mock.calls[0][0].map((f: File) => f.name)).toEqual(["a.xml", "b.xml"]);
});

test("dropping files reports them and cancels the event", () => {
  const onFiles = vi.fn();
  render(<DropZone title={TITLE} onFiles={onFiles} />);
  const zone = screen.getByRole("button", { name: TITLE });
  const dropped = [file()];
  fireEvent.dragEnter(zone, { dataTransfer: { types: ["Files"], files: dropped } });
  expect(zone).toHaveAttribute("data-over");
  const notCancelled = fireEvent.drop(zone, { dataTransfer: { types: ["Files"], files: dropped } });
  expect(notCancelled).toBe(false);
  expect(onFiles).toHaveBeenCalledWith(dropped);
  expect(zone).not.toHaveAttribute("data-over");
});

test("test_non_file_drags_are_ignored", () => {
  const onFiles = vi.fn();
  render(<DropZone title={TITLE} onFiles={onFiles} />);
  const zone = screen.getByRole("button", { name: TITLE });
  const text = { dataTransfer: { types: ["text/plain"], files: [] } };
  fireEvent.dragEnter(zone, text);
  expect(zone).not.toHaveAttribute("data-over");
  expect(fireEvent.drop(zone, text)).toBe(true);
  expect(onFiles).not.toHaveBeenCalled();
});

test("leaving the zone clears the highlight", () => {
  render(<DropZone title={TITLE} onFiles={vi.fn()} />);
  const zone = screen.getByRole("button", { name: TITLE });
  const payload = { dataTransfer: { types: ["Files"], files: [] } };
  fireEvent.dragEnter(zone, payload);
  expect(zone).toHaveAttribute("data-over");
  fireEvent.dragLeave(zone, payload);
  expect(zone).not.toHaveAttribute("data-over");
});

test("Enter and Space open the file picker", async () => {
  const { container } = render(<DropZone title={TITLE} onFiles={vi.fn()} />);
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  const click = vi.spyOn(input, "click");
  screen.getByRole("button", { name: TITLE }).focus();
  await userEvent.keyboard("{Enter}");
  expect(click).toHaveBeenCalled();
  click.mockClear();
  await userEvent.keyboard(" ");
  expect(click).toHaveBeenCalled();
});
