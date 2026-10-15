import { formatBytes, formatDate, splitUrl } from "./format";

test("formatBytes uses SI units", () => {
  expect(formatBytes(0)).toBe("0 B");
  expect(formatBytes(999)).toBe("999 B");
  expect(formatBytes(1500)).toBe("1.5 KB");
  expect(formatBytes(164518301)).toBe("164.5 MB");
  expect(formatBytes(2_000_000_000)).toBe("2.0 GB");
});

test("formatDate is relative when recent and a date when old", () => {
  const now = new Date("2026-10-15T12:00:00Z");
  const f = (iso: string) => formatDate(iso, now, "UTC");
  expect(f("2026-10-15T11:59:40Z")).toBe("just now");
  expect(f("2026-10-15T11:55:00Z")).toBe("5 min ago");
  expect(f("2026-10-15T09:00:00Z")).toBe("3 h ago");
  expect(f("2026-10-13T12:00:00Z")).toBe("Oct 13");
  expect(f("2025-10-13T12:00:00Z")).toBe("Oct 13, 2025");
});

test("splitUrl separates the origin from the path and query", () => {
  expect(splitUrl("https://shop.invalid/a/b?x=1")).toEqual({ origin: "https://shop.invalid", rest: "/a/b?x=1" });
  expect(splitUrl("http://api.invalid:8080/v1")).toEqual({ origin: "http://api.invalid:8080", rest: "/v1" });
  expect(splitUrl("10.0.0.5:22")).toEqual({ origin: "", rest: "10.0.0.5:22" });
});
