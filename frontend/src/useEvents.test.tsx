import { act, renderHook } from "@testing-library/react";
import { useEvents } from "./useEvents";

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  close() {
    this.closed = true;
  }
}
const make = (url: string) => new FakeSocket(url) as unknown as WebSocket;

beforeEach(() => {
  FakeSocket.instances = [];
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

test("connects to /api/events on the page's own host and delivers parsed events", () => {
  const onEvent = vi.fn();
  const { result } = renderHook(() => useEvents(true, { onEvent }, make));
  expect(FakeSocket.instances[0].url).toBe(`ws://${window.location.host}/api/events`);
  expect(result.current).toBe("connecting");
  act(() => FakeSocket.instances[0].onopen?.());
  expect(result.current).toBe("open");
  act(() => FakeSocket.instances[0].onmessage?.({ data: JSON.stringify({ type: "blocked", address: "a:1", ts: 5 }) }));
  expect(onEvent).toHaveBeenCalledWith({ type: "blocked", address: "a:1", ts: 5 });
});

test("malformed messages are ignored", () => {
  const onEvent = vi.fn();
  renderHook(() => useEvents(true, { onEvent }, make));
  act(() => FakeSocket.instances[0].onmessage?.({ data: "not json" }));
  expect(onEvent).not.toHaveBeenCalled();
});

test("test_reconnects_with_backoff", () => {
  const onDisconnect = vi.fn();
  const { result } = renderHook(() => useEvents(true, { onEvent: vi.fn(), onDisconnect }, make));
  act(() => FakeSocket.instances[0].onclose?.());
  expect(result.current).toBe("reconnecting");
  expect(onDisconnect).toHaveBeenCalledTimes(1);
  act(() => vi.advanceTimersByTime(499));
  expect(FakeSocket.instances).toHaveLength(1);
  act(() => vi.advanceTimersByTime(1));
  expect(FakeSocket.instances).toHaveLength(2);
  act(() => FakeSocket.instances[1].onclose?.());
  act(() => vi.advanceTimersByTime(999));
  expect(FakeSocket.instances).toHaveLength(2);
  act(() => vi.advanceTimersByTime(1));
  expect(FakeSocket.instances).toHaveLength(3);
  act(() => FakeSocket.instances[2].onopen?.());
  expect(result.current).toBe("open");
});

test("the delay is capped at five seconds", () => {
  renderHook(() => useEvents(true, { onEvent: vi.fn() }, make));
  for (let i = 0; i < 8; i++) {
    act(() => FakeSocket.instances.at(-1)!.onclose?.());
    act(() => vi.advanceTimersByTime(5000));
  }
  expect(FakeSocket.instances.length).toBe(9); // every close reconnected within 5 s
});

test("nothing connects while disabled, and unmounting closes the socket", () => {
  const { rerender, unmount } = renderHook(({ on }) => useEvents(on, { onEvent: vi.fn() }, make), {
    initialProps: { on: false },
  });
  expect(FakeSocket.instances).toHaveLength(0);
  rerender({ on: true });
  expect(FakeSocket.instances).toHaveLength(1);
  unmount();
  expect(FakeSocket.instances[0].closed).toBe(true);
  act(() => vi.advanceTimersByTime(10000));
  expect(FakeSocket.instances).toHaveLength(1);
});
