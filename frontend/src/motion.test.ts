import { fade, springs } from "./motion";

test("spring presets match the spec", () => {
  expect(springs.layout).toEqual({ type: "spring", stiffness: 380, damping: 32 });
  expect(springs.screen).toEqual({ type: "spring", stiffness: 260, damping: 28 });
  expect(springs.feed).toEqual({ type: "spring", stiffness: 420, damping: 34 });
  expect(springs.drop).toEqual({ type: "spring", stiffness: 500, damping: 30 });
  expect(springs.bar).toEqual({ type: "spring", stiffness: 200, damping: 30 });
  expect(fade.duration).toBe(0.15);
});
