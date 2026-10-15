import { act, renderHook } from "@testing-library/react";
import { useToasts } from "./useToasts";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

test("info toasts dismiss themselves after the delay; errors stay", () => {
  const { result } = renderHook(() => useToasts(6000));
  act(() => {
    result.current.push("info", "Opened Firefox");
    result.current.push("error", "address already in use");
  });
  expect(result.current.toasts.map((t) => t.message)).toEqual(["Opened Firefox", "address already in use"]);
  act(() => void vi.advanceTimersByTime(5999));
  expect(result.current.toasts).toHaveLength(2);
  act(() => void vi.advanceTimersByTime(1));
  expect(result.current.toasts.map((t) => t.message)).toEqual(["address already in use"]);
  act(() => void vi.advanceTimersByTime(60_000));
  expect(result.current.toasts).toHaveLength(1);
});

test("dismiss removes a toast and an identical one is not shown twice", () => {
  const { result } = renderHook(() => useToasts());
  act(() => {
    result.current.push("error", "boom");
    result.current.push("error", "boom"); // e.g. the API error and the server's own toast event
  });
  expect(result.current.toasts).toHaveLength(1);
  act(() => result.current.dismiss(result.current.toasts[0].id));
  expect(result.current.toasts).toHaveLength(0);
  act(() => result.current.push("error", "boom")); // allowed again once the first is gone
  expect(result.current.toasts).toHaveLength(1);
});

test("pending timers are cleared on unmount", () => {
  const { result, unmount } = renderHook(() => useToasts());
  act(() => result.current.push("info", "hello"));
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});
