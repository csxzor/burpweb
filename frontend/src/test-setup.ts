import "@testing-library/jest-dom/vitest";
import { FakeWebSocket } from "./test-utils";

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});
afterEach(() => {
  vi.unstubAllGlobals();
});
