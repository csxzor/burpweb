const UNITS = ["B", "KB", "MB", "GB", "TB"];

export function formatBytes(n: number): string {
  if (n < 1000) return `${n} B`;
  let value = n;
  let unit = 0;
  while (value >= 1000 && unit < UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${value.toFixed(1)} ${UNITS[unit]}`;
}

export function formatDate(iso: string, now: Date = new Date(), timeZone?: string): string {
  const then = new Date(iso);
  const seconds = Math.round((now.getTime() - then.getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  const sameYear = then.getUTCFullYear() === now.getUTCFullYear();
  return then.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
    timeZone,
  });
}

export function splitUrl(url: string): { origin: string; rest: string } {
  try {
    const u = new URL(url);
    if (!u.host) throw new Error("no host");
    return { origin: u.origin, rest: u.pathname + u.search + u.hash };
  } catch {
    return { origin: "", rest: url };
  }
}
