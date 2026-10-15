import { act, fireEvent, renderHook } from "@testing-library/react";
import { hasFiles, useWindowDrop } from "./dnd";

const files = (...names: string[]) => names.map((n) => new File(["<items/>"], n));
const withFiles = (list: File[] = []) => ({ dataTransfer: { types: ["Files"], files: list } });
const withText = { dataTransfer: { types: ["text/plain"], files: [] } };

test("hasFiles looks at the drag payload type", () => {
  expect(hasFiles({ types: ["Files"] } as unknown as DataTransfer)).toBe(true);
  expect(hasFiles({ types: ["text/plain"] } as unknown as DataTransfer)).toBe(false);
  expect(hasFiles(null)).toBe(false);
});

test("the overlay shows while files are over the window, including nested enters", () => {
  const { result } = renderHook(() => useWindowDrop(vi.fn()));
  act(() => void fireEvent.dragEnter(window, withFiles()));
  act(() => void fireEvent.dragEnter(window, withFiles()));
  expect(result.current).toBe(true);
  act(() => void fireEvent.dragLeave(window, withFiles()));
  expect(result.current).toBe(true);
  act(() => void fireEvent.dragLeave(window, withFiles()));
  expect(result.current).toBe(false);
});

test("test_non_file_drags_are_ignored", () => {
  const onFiles = vi.fn();
  const { result } = renderHook(() => useWindowDrop(onFiles));
  act(() => void fireEvent.dragEnter(window, withText));
  expect(result.current).toBe(false);
  // not cancelled, so selected text or a link keeps its normal behaviour
  expect(fireEvent.drop(window, withText)).toBe(true);
  expect(onFiles).not.toHaveBeenCalled();
});

test("dropping files delivers them and cancels the browser's own handling", () => {
  const onFiles = vi.fn();
  const { result } = renderHook(() => useWindowDrop(onFiles));
  const dropped = files("a.xml", "b.xml");
  act(() => void fireEvent.dragEnter(window, withFiles()));
  let notCancelled = true;
  act(() => {
    notCancelled = fireEvent.drop(window, withFiles(dropped));
  });
  expect(notCancelled).toBe(false); // preventDefault was called: Firefox will not open the file
  expect(onFiles).toHaveBeenCalledWith(dropped);
  expect(result.current).toBe(false);
});

test("a drop that a drop zone already handled is not delivered twice", () => {
  const onFiles = vi.fn();
  const { result } = renderHook(() => useWindowDrop(onFiles));
  const zone = document.body.appendChild(document.createElement("div"));
  zone.addEventListener("drop", (e) => e.preventDefault());
  act(() => void fireEvent.dragEnter(zone, withFiles()));
  act(() => void fireEvent.drop(zone, withFiles(files("a.xml"))));
  expect(onFiles).not.toHaveBeenCalled();
  expect(result.current).toBe(false); // but the overlay still goes away
  zone.remove();
});

test("a disabled hook ignores drags", () => {
  const onFiles = vi.fn();
  const { result } = renderHook(() => useWindowDrop(onFiles, false));
  act(() => void fireEvent.dragEnter(window, withFiles()));
  fireEvent.drop(window, withFiles(files("a.xml")));
  expect(result.current).toBe(false);
  expect(onFiles).not.toHaveBeenCalled();
});
