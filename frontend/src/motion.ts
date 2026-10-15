export const springs = {
  layout: { type: "spring", stiffness: 380, damping: 32 },
  screen: { type: "spring", stiffness: 260, damping: 28 },
  feed: { type: "spring", stiffness: 420, damping: 34 },
  drop: { type: "spring", stiffness: 500, damping: 30 },
  bar: { type: "spring", stiffness: 200, damping: 30 },
} as const;

export const fade = { duration: 0.15 } as const;
