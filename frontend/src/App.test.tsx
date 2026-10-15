import { act, render, screen } from "@testing-library/react";
import { ApiError, api, setAuthHandlers } from "./api";
import { App } from "./App";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  setAuthHandlers({});
});

test("a locked library shows the unlock form", async () => {
  vi.spyOn(api, "state").mockResolvedValue({ vault: "locked", replay: null });
  render(<App />);
  expect(await screen.findByRole("button", { name: "Unlock" })).toBeInTheDocument();
});

test("a new library shows the create form", async () => {
  vi.spyOn(api, "state").mockResolvedValue({ vault: "new", replay: null });
  render(<App />);
  expect(await screen.findByRole("button", { name: "Create library" })).toBeInTheDocument();
});

test("an unlocked library shows the main screen", async () => {
  vi.spyOn(api, "snapshots").mockResolvedValue([]);
  vi.spyOn(api, "state").mockResolvedValue({ vault: "unlocked", replay: null });
  render(<App />);
  expect(await screen.findByLabelText("Live feed")).toBeInTheDocument();
});

test("a rejected token explains how to get back in", async () => {
  vi.spyOn(api, "state").mockRejectedValue(new ApiError(403, "missing or bad token"));
  render(<App />);
  expect(await screen.findByText("Session expired")).toBeInTheDocument();
  expect(screen.getByText(/printed in the terminal/)).toBeInTheDocument();
});

test("an unreachable server is reported", async () => {
  vi.spyOn(api, "state").mockRejectedValue(new TypeError("Failed to fetch"));
  render(<App />);
  expect(await screen.findByText("Can't reach burpweb")).toBeInTheDocument();
});

test("test_locked_response_returns_to_unlock", async () => {
  vi.spyOn(api, "snapshots").mockResolvedValue([]);
  vi.spyOn(api, "state").mockResolvedValue({ vault: "unlocked", replay: null });
  render(<App />);
  expect(await screen.findByLabelText("Live feed")).toBeInTheDocument();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: "library locked" }), { status: 423 })),
  );
  await act(async () => {
    await api.stopReplay().catch(() => {}); // any real call that learns the library was locked elsewhere
  });
  expect(await screen.findByRole("button", { name: "Unlock" })).toBeInTheDocument();
});
