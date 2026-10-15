# burpweb UI Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the React control page that `burpweb ui` serves: unlock the encrypted library, drop or upload Burp XML exports into named snapshots, start and stop the replay, open the preconfigured Firefox, and watch the live request feed and miss list.

**Architecture:** A small single-page React app in `frontend/`, built by Vite into `src/burpweb/static/` (committed, so Python users never need Node). It talks to the existing backend only through `fetch` (JSON API) and one WebSocket (`/api/events`). State is plain React (a reducer for the feed, hooks for the rest); no state library. Motion (`motion/react`) provides springs, layout and presence animations.

**Tech Stack:** React 19.3.1, TypeScript 7.0.2, Vite 8.3.4 + @vitejs/plugin-react 6.1.2, motion 14.2.0, Vitest 5.0.4 + jsdom 30.1.3 + Testing Library, @fontsource (Schibsted Grotesk, JetBrains Mono). Toolchain verified together in a scratch project: `tsc --noEmit`, `vite build` and `vitest run` all pass with these versions.

**Spec:** `docs/superpowers/specs/2026-10-15-burpweb-ui-design.md` (Frontend section); backend contract in `docs/superpowers/plans/2026-10-15-burpweb-ui-backend.md`.

## Global Constraints

- Every dependency is pinned to an exact version (`--save-exact`); no `^` or `~`.
- **No network at runtime:** fonts are bundled (`@fontsource/*/latin-*.css`, latin subset only), nothing loads from a CDN, the page makes requests only to its own origin.
- **No gradients anywhere.** Depth comes from the surface steps `--bg` → `--panel` → `--raised`, 1px `--line` borders, and the single soft shadow `0 12px 32px rgba(0,0,0,.45)` on floating elements only.
- Colour tokens are exactly: `--bg #0b0c0e`, `--panel #121418`, `--raised #191c21`, `--line #262a31`, `--text #e7e5e1`, `--muted #8b9099`, `--accent #8b7cf6`, `--exact #3fcf8e`, `--fallback #e8b44c`, `--head #6cb6ff`, `--miss #f2667a`, `--blocked #9198a1`.
- Fonts: Schibsted Grotesk 400/500/700 for UI, JetBrains Mono 400/600 for URLs, counts and badges; 13px base; tabular figures for every number. Radii: 10px cards/inputs, 14px drop zone, 6px badges.
- Springs (stiffness/damping): layout 380/32, screen 260/28, feed 420/34, drop zone 500/30, progress bar 200/30. Under `prefers-reduced-motion: reduce` motion collapses to short opacity fades and the drop-zone breathing loop stops.
- The passphrase is never stored: not in `localStorage`, `sessionStorage`, URL, or React state after submit.
- All server-provided strings (snapshot names, file names, URLs, error messages) are rendered as text, never as HTML.
- Layout: three columns `280px | 1fr | 360px`, full viewport height; the page is a desktop tool, so no mobile layout is required.
- Build output goes to `src/burpweb/static/` with `base: "/static/"` (Tornado serves that directory under `/static/` and `index.html` at `/`).

## Review Focus

1. **Thousands of feed rows or very long URLs must not freeze or overflow the page.** The feed keeps at most 500 rows (counters keep counting) and URLs ellipsize on one line. Pinned by `test_feed_caps_rows_but_keeps_counting` and `test_long_url_is_one_ellipsized_line` (Tasks 4, 10).
2. **The passphrase must not linger or persist.** Pinned by `test_passphrase_is_cleared_and_never_stored` (Task 6).
3. **A drag of non-files (selected text, a link) or a drop that includes a folder or a 0-byte file must not break the page.** Pinned by `test_non_file_drags_are_ignored` and `test_empty_file_is_reported_not_uploaded` (Tasks 5, 8).
4. **The WebSocket dropping, and the library being locked from elsewhere (a 423 or 403), must be handled.** The feed reconnects with backoff and shows a "reconnecting" pill; a 423 from any call returns the user to the unlock screen without losing the page. Pinned by `test_reconnects_with_backoff` and `test_locked_response_returns_to_unlock` (Tasks 4, 6).
5. **Server-provided names must not be able to inject markup.** Pinned by `test_snapshot_name_is_rendered_as_text` (Task 7).
6. **Double-clicking Start, Stop or Create must not send twice.** Pinned by `test_start_button_is_disabled_while_pending` (Task 9).

## File Structure

```
frontend/
  package.json  vite.config.ts  tsconfig.json  index.html
  src/
    main.tsx  App.tsx  vite-env.d.ts  test-setup.ts
    types.ts          # API and event types (Task 3)
    api.ts            # typed fetch wrapper + ApiError (Task 3)
    format.ts         # bytes, dates, URL helpers (Task 3)
    motion.ts         # spring presets (Task 2)
    feed.ts           # pure reducer for the live feed + misses (Task 4)
    useEvents.ts      # WebSocket hook with backoff (Task 4)
    uploads.ts        # XHR upload with progress (Task 5)
    useUploads.ts     # upload chips state (Task 5)
    styles/tokens.css  styles/base.css
    components/
      Unlock.tsx  Library.tsx  SnapshotCard.tsx  DropZone.tsx  UploadChip.tsx
      NewSnapshot.tsx  SnapshotView.tsx  Feed.tsx  Toasts.tsx  ConfirmDialog.tsx
      (each with a sibling .css and .test.tsx)
src/burpweb/static/          # build output, committed
tests/test_ui_e2e.py         # headless Firefox end-to-end (Task 11)
```

---

### Task 1: Backend — per-origin table in snapshot stats

The spec's snapshot screen shows an origins table (items, paths, origin). The backend's `stats` only carries counts, so the table needs `stats.by_origin`.

**Files:**
- Modify: `src/burpweb/library.py` (the `stats` dict in `_write_snapshot`)
- Test: `tests/test_library.py`

**Interfaces:**
- Consumes: `Library`, `make_item`, `make_xml`
- Produces: `Snapshot.stats["by_origin"]: list[{"origin": str, "items": int, "paths": int}]`, sorted by `items` descending (ties keep first-seen order). Existing keys (`items`, `origins`, `skipped`, `malformed`) are unchanged.

- [ ] **Step 1: Write the failing test** — append to `tests/test_library.py`:

```python
def test_stats_include_origin_table(lib):
    other = b"GET /q HTTP/1.1\r\nHost: shop.invalid\r\n\r\n"
    api = b"GET /a HTTP/1.1\r\nHost: api.invalid:8080\r\n\r\n"
    xml = make_xml([
        make_item(host="shop.invalid", request=REQ, response=OK),
        make_item(host="shop.invalid", request=other, response=OK),
        make_item(host="api.invalid", port=8080, protocol="http", request=api, response=OK),
    ]).encode()
    snap = lib.create("s", [xml], ["a.xml"])
    expected = [
        {"origin": "https://shop.invalid", "items": 2, "paths": 2},
        {"origin": "http://api.invalid:8080", "items": 1, "paths": 1},
    ]
    assert snap.stats["by_origin"] == expected
    assert lib.list()[0].stats["by_origin"] == expected
    assert snap.stats["origins"] == 2  # the existing count is untouched
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_library.py::test_stats_include_origin_table -q -W ignore`
Expected: FAIL with `KeyError: 'by_origin'`.

- [ ] **Step 3: Implement** — in `Library._write_snapshot`, replace the `stats = {...}` block with:

```python
        rows: dict[str, dict] = {}
        for r in result.records:
            row = rows.setdefault(r.origin, {"items": 0, "paths": set()})
            row["items"] += 1
            row["paths"].add(r.path)
        by_origin = sorted(
            ({"origin": o, "items": v["items"], "paths": len(v["paths"])} for o, v in rows.items()),
            key=lambda row: -row["items"],  # sorted() is stable, so ties keep first-seen order
        )
        stats = {"items": len(result.records),
                 "origins": len(rows),
                 "skipped": result.skipped_no_response,
                 "malformed": result.malformed,
                 "by_origin": by_origin}
```

- [ ] **Step 4: Run the library tests**

Run: `uv run pytest tests/test_library.py -q -W ignore`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/burpweb/library.py tests/test_library.py
git commit -m "feat: per-origin table in snapshot stats"
```

---

### Task 2: Frontend scaffold, design tokens, motion presets, static serving

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`
- Create: `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/vite-env.d.ts`, `frontend/src/test-setup.ts`
- Create: `frontend/src/motion.ts`, `frontend/src/motion.test.ts`, `frontend/src/styles/tokens.css`, `frontend/src/styles/base.css`
- Modify: `.gitignore`, `tests/test_webapp.py` (one new test class)
- Generated and committed: `src/burpweb/static/`

**Interfaces:**
- Consumes: the existing `make_app(..., static_dir=...)` and `TokenHandler._serve_index`
- Produces:
  - npm scripts `dev`, `build` (typecheck then Vite), `test`
  - `springs` in `motion.ts`: `{ layout, screen, feed, drop, bar }`, each `{type:"spring", stiffness, damping}`, plus `fade = { duration: 0.15 }`
  - CSS variables from the Global Constraints, defined on `:root` in `tokens.css`
  - the built app at `/` (HTML) and `/static/assets/*`

- [ ] **Step 1: Write the failing Python test** — append to `tests/test_webapp.py`:

```python
class TestStatic(Base):
    def get_app(self):
        self.library = Library(self.get_temp_dir() / "lib")
        self.session = ReplaySession(confdir=self.get_temp_dir() / "conf")
        static = self.get_temp_dir() / "static"
        (static / "assets").mkdir(parents=True)
        (static / "index.html").write_text("<!doctype html><title>burpweb</title>")
        (static / "assets" / "app.js").write_text("console.log(1)")
        return make_app(self.library, self.session, TOKEN, static_dir=str(static))

    def test_index_needs_the_token_but_assets_do_not_leak_data(self):
        assert self.fetch("/", headers={"Host": "127.0.0.1"}).code == 403
        page = self.fetch("/", headers=self.cookie())
        assert page.code == 200 and b"<title>burpweb</title>" in page.body
        asset = self.fetch("/static/assets/app.js", headers={"Host": "127.0.0.1"})
        assert asset.code == 200 and asset.body == b"console.log(1)"
```

- [ ] **Step 2: Run it** — `uv run pytest tests/test_webapp.py::TestStatic -q -W ignore`. It should already PASS (the backend serves static files). If it does, keep it as the regression guard for how the built app is served; if it fails, fix the backend before continuing.

- [ ] **Step 3: Create the project files**

`frontend/package.json`:
```json
{
  "name": "burpweb-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@fontsource/jetbrains-mono": "5.3.0",
    "@fontsource/schibsted-grotesk": "5.3.0",
    "motion": "14.2.0",
    "react": "19.3.1",
    "react-dom": "19.3.1"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "7.0.1",
    "@testing-library/react": "16.3.3",
    "@testing-library/user-event": "14.6.8",
    "@types/node": "26.6.5",
    "@types/react": "19.3.0",
    "@types/react-dom": "19.3.0",
    "@vitejs/plugin-react": "6.1.2",
    "jsdom": "30.1.3",
    "typescript": "7.0.2",
    "vite": "8.3.4",
    "vitest": "5.0.4"
  }
}
```

`frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "types": ["vitest/globals", "@testing-library/jest-dom", "node"]
  },
  "include": ["src"]
}
```

`frontend/vite.config.ts`:
```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: { outDir: "../src/burpweb/static", emptyOutDir: true },
  server: { proxy: { "/api": { target: "http://127.0.0.1:8765", ws: true } } },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});
```

`frontend/index.html`:
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="color-scheme" content="dark" />
    <title>burpweb</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/vite-env.d.ts`:
```ts
/// <reference types="vite/client" />
```

`frontend/src/test-setup.ts`:
```ts
import "@testing-library/jest-dom/vitest";
```

`frontend/src/motion.ts`:
```ts
export const springs = {
  layout: { type: "spring", stiffness: 380, damping: 32 },
  screen: { type: "spring", stiffness: 260, damping: 28 },
  feed: { type: "spring", stiffness: 420, damping: 34 },
  drop: { type: "spring", stiffness: 500, damping: 30 },
  bar: { type: "spring", stiffness: 200, damping: 30 },
} as const;

export const fade = { duration: 0.15 } as const;
```

`frontend/src/motion.test.ts`:
```ts
import { fade, springs } from "./motion";

test("spring presets match the spec", () => {
  expect(springs.layout).toEqual({ type: "spring", stiffness: 380, damping: 32 });
  expect(springs.screen).toEqual({ type: "spring", stiffness: 260, damping: 28 });
  expect(springs.feed).toEqual({ type: "spring", stiffness: 420, damping: 34 });
  expect(springs.drop).toEqual({ type: "spring", stiffness: 500, damping: 30 });
  expect(springs.bar).toEqual({ type: "spring", stiffness: 200, damping: 30 });
  expect(fade.duration).toBe(0.15);
});
```

`frontend/src/styles/tokens.css`:
```css
:root {
  --bg: #0b0c0e;
  --panel: #121418;
  --raised: #191c21;
  --line: #262a31;
  --text: #e7e5e1;
  --muted: #8b9099;
  --accent: #8b7cf6;
  --exact: #3fcf8e;
  --fallback: #e8b44c;
  --head: #6cb6ff;
  --miss: #f2667a;
  --blocked: #9198a1;

  --font-ui: "Schibsted Grotesk", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;

  --radius: 10px;
  --radius-drop: 14px;
  --radius-badge: 6px;
  --shadow-float: 0 12px 32px rgba(0, 0, 0, 0.45);
}
```

`frontend/src/styles/base.css`:
```css
*, *::before, *::after { box-sizing: border-box; }

html, body, #root { height: 100%; margin: 0; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 13px;
  line-height: 1.45;
  -webkit-font-smoothing: antialiased;
}

/* Tabular figures for data only: applied to the whole body they also widen commas and periods. */
.mono, table, .tile-value { font-variant-numeric: tabular-nums; }

button, input { font: inherit; color: inherit; }
button { cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: 0.5; }

:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.mono { font-family: var(--font-mono); }
.muted { color: var(--muted); }

::selection { background: color-mix(in srgb, var(--accent) 35%, transparent); }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; }
}
```

`frontend/src/main.tsx`:
```tsx
import "@fontsource/schibsted-grotesk/latin-400.css";
import "@fontsource/schibsted-grotesk/latin-500.css";
import "@fontsource/schibsted-grotesk/latin-700.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-600.css";
import "./styles/tokens.css";
import "./styles/base.css";
import { createRoot } from "react-dom/client";
import { MotionConfig } from "motion/react";
import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <MotionConfig reducedMotion="user">
    <App />
  </MotionConfig>,
);
```

`frontend/src/App.tsx` (a shell for now; Task 6 replaces it):
```tsx
export function App() {
  return <main className="mono">burpweb</main>;
}
```

`frontend/src/App.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { App } from "./App";

test("the shell renders", () => {
  render(<App />);
  expect(screen.getByText("burpweb")).toBeInTheDocument();
});
```

Add to the root `.gitignore`:
```
frontend/node_modules/
```

- [ ] **Step 4: Install, test, build**

Run: `cd frontend && npm install --save-exact && npm test && npm run build`
Expected: both tests PASS; `tsc` is clean; Vite prints `✓ built` and writes `index.html` and `assets/` into `src/burpweb/static/`. The built `index.html` references `/static/assets/...`. The build is small (≈0.5 MB, five latin font files).

- [ ] **Step 5: Verify the built page is served by the real server**

Run: `uv run pytest tests/test_webapp.py::TestStatic -q -W ignore` (PASS), then start `uv run burpweb ui --no-open` in the background with `HOME` set to a temporary directory, request the printed URL with `curl -sL -c jar`, and confirm the HTML contains `/static/assets/` and each referenced asset returns `200`. Stop the server and delete the temporary home.

- [ ] **Step 6: Commit**

```bash
git add .gitignore frontend/package.json frontend/package-lock.json frontend/vite.config.ts \
  frontend/tsconfig.json frontend/index.html frontend/src tests/test_webapp.py src/burpweb/static
git commit -m "feat: frontend scaffold, design tokens and built shell"
```

---

### Task 3: Types, API client, formatting helpers

**Files:**
- Create: `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/format.ts`
- Test: `frontend/src/api.test.ts`, `frontend/src/format.test.ts`

**Interfaces:**
- Consumes: the backend JSON API (shapes below)
- Produces:
  - types: `Snapshot`, `Stats`, `OriginRow`, `FileInfo`, `AppState`, `VaultState`, `ReplayState`, `Tier`, `EventMsg`
  - `ApiError(status, message)`; `setAuthHandlers({ locked?, forbidden? })`; `notifyAuthStatus(status: number): void` (calls `locked` for 423 and `forbidden` for 403)
  - `api.{state, createVault, unlock, lock, snapshots, createSnapshot, addFiles, rename, remove, startReplay, stopReplay, openBrowser}`
  - `formatBytes(n)`, `formatDate(iso, now?, timeZone?)`, `splitUrl(url)`

- [ ] **Step 1: Write the failing tests**

`frontend/src/api.test.ts`:
```ts
import { ApiError, api, setAuthHandlers } from "./api";

function respond(status: number, body?: unknown, statusText = "") {
  const res = new Response(body === undefined ? null : JSON.stringify(body), { status, statusText });
  return vi.fn().mockResolvedValue(res);
}

afterEach(() => {
  vi.unstubAllGlobals();
  setAuthHandlers({});
});

test("sends JSON with a content type and returns the parsed body", async () => {
  const fetchMock = respond(200, { vault: "new", replay: null });
  vi.stubGlobal("fetch", fetchMock);
  await expect(api.state()).resolves.toEqual({ vault: "new", replay: null });
  await api.createVault("correct horse battery");
  const [url, init] = fetchMock.mock.calls[1];
  expect(url).toBe("/api/vault/create");
  expect(init.method).toBe("POST");
  expect(init.headers).toEqual({ "Content-Type": "application/json" });
  expect(JSON.parse(init.body)).toEqual({ passphrase: "correct horse battery" });
});

test("a 204 resolves to undefined", async () => {
  vi.stubGlobal("fetch", respond(204));
  await expect(api.remove("abc")).resolves.toBeUndefined();
});

test("errors carry the server's message and status", async () => {
  vi.stubGlobal("fetch", respond(422, { error: "no usable items" }));
  const err = await api.createSnapshot("n", ["u1"]).catch((e) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err).toMatchObject({ status: 422, message: "no usable items" });
});

test("a non-JSON error falls back to the status text", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 502, statusText: "Bad Gateway" })));
  await expect(api.state()).rejects.toMatchObject({ status: 502, message: "Bad Gateway" });
});

test("a 423 notifies the locked handler and still throws", async () => {
  const locked = vi.fn();
  setAuthHandlers({ locked });
  vi.stubGlobal("fetch", respond(423, { error: "library locked" }));
  await expect(api.snapshots()).rejects.toMatchObject({ status: 423 });
  expect(locked).toHaveBeenCalledTimes(1);
});

test("a 403 notifies the forbidden handler; a 401 notifies neither", async () => {
  const locked = vi.fn();
  const forbidden = vi.fn();
  setAuthHandlers({ locked, forbidden });
  vi.stubGlobal("fetch", respond(403, { error: "missing or bad token" }));
  await expect(api.state()).rejects.toMatchObject({ status: 403 });
  vi.stubGlobal("fetch", respond(401, { error: "wrong passphrase" }));
  await expect(api.unlock("nope")).rejects.toMatchObject({ status: 401 });
  expect(forbidden).toHaveBeenCalledTimes(1);
  expect(locked).not.toHaveBeenCalled();
});

test("endpoints use the documented paths and verbs", async () => {
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200 })));
  vi.stubGlobal("fetch", fetchMock);
  await api.rename("s1", "New name");
  await api.addFiles("s1", ["u1", "u2"]);
  await api.startReplay("s1", 9000);
  await api.stopReplay();
  await api.openBrowser();
  await api.lock();
  const calls = fetchMock.mock.calls.map(([url, init]) => `${init.method} ${url}`);
  expect(calls).toEqual([
    "PATCH /api/snapshots/s1",
    "POST /api/snapshots/s1/files",
    "POST /api/replay",
    "DELETE /api/replay",
    "POST /api/browser",
    "POST /api/vault/lock",
  ]);
});
```

`frontend/src/format.test.ts`:
```ts
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/api.test.ts src/format.test.ts`
Expected: FAIL (cannot resolve `./api` and `./format`).

- [ ] **Step 3: Implement**

`frontend/src/types.ts`:
```ts
export interface FileInfo { name: string; size: number }
export interface OriginRow { origin: string; items: number; paths: number }
export interface Stats {
  items: number;
  origins: number;
  skipped: number;
  malformed: [number, string][];
  by_origin?: OriginRow[];
}
export interface Snapshot {
  id: string;
  name: string;
  created: string;
  files: FileInfo[];
  stats: Stats;
  damaged: boolean;
}

export type VaultState = "new" | "locked" | "unlocked";
export interface ReplayState { running: boolean; port: number | null; snapshot_id: string | null }
export interface AppState { vault: VaultState; replay: ReplayState | null }

export type Tier = "EXACT" | "FALLBACK" | "HEAD" | "MISS" | "BLOCKED";

export type EventMsg =
  | { type: "request"; tier: Tier; method: string; url: string; status: number; item: string | null; ts: number }
  | { type: "blocked"; address: string; ts: number }
  | { type: "replay"; running: boolean; snapshot_id: string | null; port: number | null; ts: number }
  | { type: "misses"; misses: { key: string; count: number }[]; ts: number }
  | { type: "toast"; level: "error" | "info"; message: string; ts: number };
```

`frontend/src/api.ts`:
```ts
import type { AppState, Snapshot } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

interface AuthHandlers { locked?: () => void; forbidden?: () => void }
let handlers: AuthHandlers = {};

export function setAuthHandlers(next: AuthHandlers): void {
  handlers = next;
}

/** 423 means the library was locked elsewhere; 403 means this page's token is no longer valid. */
export function notifyAuthStatus(status: number): void {
  if (status === 423) handlers.locked?.();
  else if (status === 403) handlers.forbidden?.();
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (res.status === 204) return undefined as T;
  let data: { error?: string } | null = null;
  try {
    data = await res.json();
  } catch {
    // not JSON; fall back to the status text below
  }
  if (!res.ok) {
    notifyAuthStatus(res.status);
    throw new ApiError(res.status, data?.error ?? (res.statusText || `HTTP ${res.status}`));
  }
  return data as T;
}

export const api = {
  state: () => request<AppState>("GET", "/api/state"),
  createVault: (passphrase: string) => request<{ ok: true }>("POST", "/api/vault/create", { passphrase }),
  unlock: (passphrase: string) => request<{ ok: true }>("POST", "/api/vault/unlock", { passphrase }),
  lock: () => request<{ ok: true }>("POST", "/api/vault/lock", {}),
  snapshots: () => request<Snapshot[]>("GET", "/api/snapshots"),
  createSnapshot: (name: string, uploads: string[]) =>
    request<Snapshot>("POST", "/api/snapshots", { name, uploads }),
  addFiles: (id: string, uploads: string[]) =>
    request<Snapshot>("POST", `/api/snapshots/${id}/files`, { uploads }),
  rename: (id: string, name: string) => request<Snapshot>("PATCH", `/api/snapshots/${id}`, { name }),
  remove: (id: string) => request<void>("DELETE", `/api/snapshots/${id}`),
  startReplay: (snapshot_id: string, port?: number) =>
    request<{ snapshot_id: string; port: number; running: boolean }>("POST", "/api/replay", { snapshot_id, port }),
  stopReplay: () => request<void>("DELETE", "/api/replay"),
  openBrowser: () => request<{ ok: true }>("POST", "/api/browser", {}),
};
```

`frontend/src/format.ts`:
```ts
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
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run src/api.test.ts src/format.test.ts && npx tsc --noEmit`
Expected: all PASS, `tsc` clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/format.ts frontend/src/api.test.ts frontend/src/format.test.ts
git commit -m "feat: typed API client and formatting helpers"
```

---

### Task 4: Live feed reducer and WebSocket hook

**Files:**
- Create: `frontend/src/feed.ts`, `frontend/src/useEvents.ts`
- Test: `frontend/src/feed.test.ts`, `frontend/src/useEvents.test.tsx`

**Interfaces:**
- Consumes: `EventMsg`, `Tier` from `types.ts`
- Produces:
  - `feed.ts`: `MAX_ROWS = 500`, `TierFilter`, `FeedRow`, `MissEntry`, `FeedState`, `FeedAction`, `emptyFeed()`, `feedReducer(state, action)`, `visibleRows(rows, filter)`
  - `useEvents.ts`: `ConnectionStatus = "idle" | "connecting" | "open" | "reconnecting"`; `useEvents(enabled, { onEvent, onDisconnect? }, createSocket?) -> ConnectionStatus`

- [ ] **Step 1: Write the failing tests**

`frontend/src/feed.test.ts`:
```ts
import { MAX_ROWS, emptyFeed, feedReducer, visibleRows, type FeedState } from "./feed";
import type { EventMsg } from "./types";

const request = (n: number, tier: "EXACT" | "MISS" = "EXACT"): EventMsg => ({
  type: "request", tier, method: "GET", url: `https://shop.invalid/p${n}`, status: tier === "MISS" ? 404 : 200, item: null, ts: n,
});
const apply = (state: FeedState, event: EventMsg) => feedReducer(state, { type: "event", event });

test("rows are newest first", () => {
  let s = emptyFeed();
  s = apply(s, request(1));
  s = apply(s, request(2));
  expect(s.rows.map((r) => r.url)).toEqual(["https://shop.invalid/p2", "https://shop.invalid/p1"]);
  expect(s.rows[0].id).toBeGreaterThan(s.rows[1].id);
});

test("test_feed_caps_rows_but_keeps_counting", () => {
  let s = emptyFeed();
  for (let i = 0; i < MAX_ROWS + 120; i++) s = apply(s, request(i, i % 4 === 0 ? "MISS" : "EXACT"));
  expect(s.rows).toHaveLength(MAX_ROWS);
  expect(s.rows[0].url).toBe(`https://shop.invalid/p${MAX_ROWS + 119}`);
  expect(s.counts.ALL).toBe(MAX_ROWS + 120);
  expect(s.counts.MISS + s.counts.EXACT).toBe(MAX_ROWS + 120);
  expect(s.counts.MISS).toBe(155);
});

test("blocked events become BLOCKED rows", () => {
  const s = apply(emptyFeed(), { type: "blocked", address: "10.0.0.5:22", ts: 1 });
  expect(s.rows[0]).toMatchObject({ tier: "BLOCKED", method: "TCP", url: "10.0.0.5:22", status: null });
  expect(s.counts.BLOCKED).toBe(1);
});

test("misses events replace the list, and other events leave the feed alone", () => {
  let s = apply(emptyFeed(), { type: "misses", misses: [{ key: "GET https://x/a", count: 2 }], ts: 1 });
  expect(s.misses).toEqual([{ key: "GET https://x/a", count: 2 }]);
  s = apply(s, { type: "replay", running: true, snapshot_id: "a", port: 1, ts: 2 });
  s = apply(s, { type: "toast", level: "info", message: "x", ts: 3 });
  expect(s.rows).toHaveLength(0);
  expect(s.misses).toHaveLength(1);
});

test("clear resets everything", () => {
  let s = apply(emptyFeed(), request(1));
  s = feedReducer(s, { type: "clear" });
  expect(s).toEqual(emptyFeed());
});

test("visibleRows filters by tier", () => {
  let s = emptyFeed();
  s = apply(s, request(1, "EXACT"));
  s = apply(s, request(2, "MISS"));
  expect(visibleRows(s.rows, "ALL")).toHaveLength(2);
  expect(visibleRows(s.rows, "MISS").map((r) => r.tier)).toEqual(["MISS"]);
});
```

`frontend/src/useEvents.test.tsx`:
```tsx
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/feed.test.ts src/useEvents.test.tsx`
Expected: FAIL (cannot resolve `./feed` / `./useEvents`).

- [ ] **Step 3: Implement**

`frontend/src/feed.ts`:
```ts
import type { EventMsg, Tier } from "./types";

export const MAX_ROWS = 500;

export type TierFilter = "ALL" | Tier;

export interface FeedRow {
  id: number;
  tier: Tier;
  method: string;
  url: string;
  status: number | null;
  item: string | null;
  ts: number;
}
export interface MissEntry { key: string; count: number }

export interface FeedState {
  rows: FeedRow[]; // newest first, at most MAX_ROWS
  counts: Record<TierFilter, number>; // every event ever seen, not only the retained rows
  misses: MissEntry[];
  nextId: number;
}

export type FeedAction = { type: "event"; event: EventMsg } | { type: "clear" };

export const emptyFeed = (): FeedState => ({
  rows: [],
  counts: { ALL: 0, EXACT: 0, FALLBACK: 0, HEAD: 0, MISS: 0, BLOCKED: 0 },
  misses: [],
  nextId: 1,
});

type RowInput = Omit<FeedRow, "id">;

function addRow(state: FeedState, row: RowInput): FeedState {
  return {
    rows: [{ id: state.nextId, ...row }, ...state.rows].slice(0, MAX_ROWS),
    counts: { ...state.counts, ALL: state.counts.ALL + 1, [row.tier]: state.counts[row.tier] + 1 },
    misses: state.misses,
    nextId: state.nextId + 1,
  };
}

export function feedReducer(state: FeedState, action: FeedAction): FeedState {
  if (action.type === "clear") return emptyFeed();
  const e = action.event;
  switch (e.type) {
    case "request":
      return addRow(state, { tier: e.tier, method: e.method, url: e.url, status: e.status, item: e.item, ts: e.ts });
    case "blocked":
      return addRow(state, { tier: "BLOCKED", method: "TCP", url: e.address, status: null, item: null, ts: e.ts });
    case "misses":
      return { ...state, misses: e.misses };
    default:
      return state; // "replay" and "toast" are handled by the app shell
  }
}

export function visibleRows(rows: FeedRow[], filter: TierFilter): FeedRow[] {
  return filter === "ALL" ? rows : rows.filter((r) => r.tier === filter);
}
```

`frontend/src/useEvents.ts`:
```ts
import { useEffect, useRef, useState } from "react";
import type { EventMsg } from "./types";

export type ConnectionStatus = "idle" | "connecting" | "open" | "reconnecting";

interface Options {
  onEvent: (event: EventMsg) => void;
  /** Called every time the socket drops, so the app can re-check whether it was locked. */
  onDisconnect?: () => void;
}

const defaultSocket = (url: string) => new WebSocket(url);

export function useEvents(
  enabled: boolean,
  options: Options,
  createSocket: (url: string) => WebSocket = defaultSocket,
): ConnectionStatus {
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const latest = useRef(options);
  latest.current = options;

  useEffect(() => {
    if (!enabled) {
      setStatus("idle");
      return;
    }
    let stopped = false;
    let attempt = 0;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      socket = createSocket(`${scheme}://${window.location.host}/api/events`);
      socket.onopen = () => {
        attempt = 0;
        setStatus("open");
      };
      socket.onmessage = (message) => {
        try {
          latest.current.onEvent(JSON.parse(message.data as string) as EventMsg);
        } catch {
          // ignore messages that are not valid JSON
        }
      };
      socket.onclose = () => {
        if (stopped) return;
        setStatus("reconnecting");
        latest.current.onDisconnect?.();
        const delay = Math.min(500 * 2 ** attempt, 5000);
        attempt += 1;
        timer = setTimeout(connect, delay);
      };
    };

    setStatus("connecting");
    connect();
    return () => {
      stopped = true;
      if (timer !== undefined) clearTimeout(timer);
      socket?.close();
    };
  }, [enabled, createSocket]);

  return status;
}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run src/feed.test.ts src/useEvents.test.tsx && npx tsc --noEmit`
Expected: all PASS, `tsc` clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/feed.ts frontend/src/useEvents.ts frontend/src/feed.test.ts frontend/src/useEvents.test.tsx
git commit -m "feat: live feed reducer and reconnecting WebSocket hook"
```

---

### Task 5: Upload machinery (XHR with progress, chip state)

**Files:**
- Create: `frontend/src/uploads.ts`, `frontend/src/useUploads.ts`
- Test: `frontend/src/uploads.test.ts`, `frontend/src/useUploads.test.tsx`

**Interfaces:**
- Consumes: `notifyAuthStatus` from `api.ts`
- Produces:
  - `uploads.ts`: `UploadHandle { promise: Promise<void>; abort(): void }`; `uploadFile(id, file, onProgress(loaded, total), makeXhr?) -> UploadHandle`. The request is `PUT /api/uploads/<id>?name=<file name>` with the `File` as the raw body (the backend streams it to disk encrypted).
  - `useUploads.ts`: `UploadItem { id, name, size, loaded, status: "uploading"|"done"|"error", error? }`; `useUploads(makeUpload?) -> { items, add(files: File[]), remove(id), clear(), doneIds, busy }`. Upload ids are `crypto.randomUUID()` values.

- [ ] **Step 1: Write the failing tests**

`frontend/src/uploads.test.ts`:
```ts
import { setAuthHandlers } from "./api";
import { uploadFile } from "./uploads";

class FakeXhr {
  upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 0;
  responseText = "";
  opened: [string, string] | null = null;
  sent: unknown = null;
  aborted = false;
  open(method: string, url: string) {
    this.opened = [method, url];
  }
  send(body: unknown) {
    this.sent = body;
  }
  abort() {
    this.aborted = true;
    this.onabort?.();
  }
}
const make = (xhr: FakeXhr) => () => xhr as unknown as XMLHttpRequest;
const file = new File(["<items/>"], "my history.xml");

afterEach(() => setAuthHandlers({}));

test("PUTs the raw file to the upload endpoint with an encoded name", () => {
  const xhr = new FakeXhr();
  uploadFile("abc-123", file, () => {}, make(xhr));
  expect(xhr.opened).toEqual(["PUT", "/api/uploads/abc-123?name=my%20history.xml"]);
  expect(xhr.sent).toBe(file);
});

test("reports progress and resolves on a 2xx", async () => {
  const xhr = new FakeXhr();
  const progress = vi.fn();
  const handle = uploadFile("u1", file, progress, make(xhr));
  xhr.upload.onprogress?.({ lengthComputable: true, loaded: 4, total: 8 } as ProgressEvent);
  xhr.status = 200;
  xhr.onload?.();
  await expect(handle.promise).resolves.toBeUndefined();
  expect(progress).toHaveBeenNthCalledWith(1, 4, 8);
  expect(progress).toHaveBeenLastCalledWith(file.size, file.size);
});

test("rejects with the server's message on an error status", async () => {
  const xhr = new FakeXhr();
  const handle = uploadFile("u1", file, () => {}, make(xhr));
  xhr.status = 409;
  xhr.responseText = JSON.stringify({ error: "upload id already used" });
  xhr.onload?.();
  await expect(handle.promise).rejects.toThrow("upload id already used");
});

test("a 423 notifies the locked handler", async () => {
  const locked = vi.fn();
  setAuthHandlers({ locked });
  const xhr = new FakeXhr();
  const handle = uploadFile("u1", file, () => {}, make(xhr));
  xhr.status = 423;
  xhr.responseText = "{}";
  xhr.onload?.();
  await expect(handle.promise).rejects.toThrow("Upload failed (HTTP 423)");
  expect(locked).toHaveBeenCalledTimes(1);
});

test("network errors and aborts reject", async () => {
  const a = new FakeXhr();
  const failing = uploadFile("u1", file, () => {}, make(a));
  a.onerror?.();
  await expect(failing.promise).rejects.toThrow("Network error");
  const b = new FakeXhr();
  const cancelled = uploadFile("u2", file, () => {}, make(b));
  cancelled.abort();
  await expect(cancelled.promise).rejects.toThrow("cancelled");
  expect(b.aborted).toBe(true);
});
```

`frontend/src/useUploads.test.tsx`:
```tsx
import { act, renderHook } from "@testing-library/react";
import type { UploadHandle } from "./uploads";
import { useUploads } from "./useUploads";

interface Pending {
  id: string;
  file: File;
  progress: (loaded: number, total: number) => void;
  resolve: () => void;
  reject: (e: Error) => void;
  aborted: boolean;
}

function harness() {
  const pending: Pending[] = [];
  const makeUpload = (id: string, file: File, progress: (l: number, t: number) => void): UploadHandle => {
    let resolve!: () => void;
    let reject!: (e: Error) => void;
    const promise = new Promise<void>((res, rej) => {
      resolve = res;
      reject = rej;
    });
    const entry: Pending = { id, file, progress, resolve, reject, aborted: false };
    pending.push(entry);
    return {
      promise,
      abort: () => {
        entry.aborted = true;
        reject(new Error("Upload cancelled"));
      },
    };
  };
  return { pending, makeUpload };
}
const xml = (name: string, text = "<items/>") => new File([text], name);

test("adds chips, tracks progress and completion", async () => {
  const { pending, makeUpload } = harness();
  const { result } = renderHook(() => useUploads(makeUpload));
  act(() => result.current.add([xml("a.xml"), xml("b.xml")]));
  expect(result.current.items.map((i) => i.status)).toEqual(["uploading", "uploading"]);
  expect(result.current.busy).toBe(true);
  expect(pending[0].id).toMatch(/^[A-Za-z0-9_-]+$/); // valid for the backend's route

  act(() => pending[0].progress(3, 8));
  expect(result.current.items[0].loaded).toBe(3);

  await act(async () => pending[0].resolve());
  expect(result.current.items[0]).toMatchObject({ status: "done", loaded: result.current.items[0].size });
  expect(result.current.busy).toBe(true);
  await act(async () => pending[1].resolve());
  expect(result.current.busy).toBe(false);
  expect(result.current.doneIds).toEqual(pending.map((p) => p.id));
});

test("a failed upload is marked with its error", async () => {
  const { pending, makeUpload } = harness();
  const { result } = renderHook(() => useUploads(makeUpload));
  act(() => result.current.add([xml("a.xml")]));
  await act(async () => pending[0].reject(new Error("Network error while uploading")));
  expect(result.current.items[0]).toMatchObject({ status: "error", error: "Network error while uploading" });
  expect(result.current.doneIds).toEqual([]);
});

test("test_empty_file_is_reported_not_uploaded", () => {
  const { pending, makeUpload } = harness();
  const { result } = renderHook(() => useUploads(makeUpload));
  act(() => result.current.add([xml("empty.xml", "")]));
  expect(pending).toHaveLength(0);
  expect(result.current.items[0]).toMatchObject({ status: "error", error: "This file is empty" });
});

test("remove aborts an in-flight upload and drops the chip without an error", async () => {
  const { pending, makeUpload } = harness();
  const { result } = renderHook(() => useUploads(makeUpload));
  act(() => result.current.add([xml("a.xml")]));
  const id = result.current.items[0].id;
  await act(async () => result.current.remove(id));
  expect(pending[0].aborted).toBe(true);
  expect(result.current.items).toEqual([]);
});

test("clear aborts everything and empties the list", async () => {
  const { pending, makeUpload } = harness();
  const { result } = renderHook(() => useUploads(makeUpload));
  act(() => result.current.add([xml("a.xml"), xml("b.xml")]));
  await act(async () => result.current.clear());
  expect(pending.every((p) => p.aborted)).toBe(true);
  expect(result.current.items).toEqual([]);
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/uploads.test.ts src/useUploads.test.tsx`
Expected: FAIL (cannot resolve `./uploads` / `./useUploads`).

- [ ] **Step 3: Implement**

`frontend/src/uploads.ts`:
```ts
import { notifyAuthStatus } from "./api";

export interface UploadHandle {
  promise: Promise<void>;
  abort: () => void;
}

function errorMessage(xhr: XMLHttpRequest): string {
  try {
    const message = JSON.parse(xhr.responseText).error;
    if (message) return String(message);
  } catch {
    // not JSON
  }
  return `Upload failed (HTTP ${xhr.status})`;
}

/** Streams a file to the backend as the raw request body, so a 160+ MB export never sits in memory. */
export function uploadFile(
  id: string,
  file: File,
  onProgress: (loaded: number, total: number) => void,
  makeXhr: () => XMLHttpRequest = () => new XMLHttpRequest(),
): UploadHandle {
  const xhr = makeXhr();
  const promise = new Promise<void>((resolve, reject) => {
    xhr.open("PUT", `/api/uploads/${encodeURIComponent(id)}?name=${encodeURIComponent(file.name)}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded, event.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(file.size, file.size);
        resolve();
        return;
      }
      notifyAuthStatus(xhr.status);
      reject(new Error(errorMessage(xhr)));
    };
    xhr.onerror = () => reject(new Error("Network error while uploading"));
    xhr.onabort = () => reject(new Error("Upload cancelled"));
    xhr.send(file);
  });
  return { promise, abort: () => xhr.abort() };
}
```

`frontend/src/useUploads.ts`:
```ts
import { useCallback, useRef, useState } from "react";
import { uploadFile, type UploadHandle } from "./uploads";

export type UploadStatus = "uploading" | "done" | "error";

export interface UploadItem {
  id: string;
  name: string;
  size: number;
  loaded: number;
  status: UploadStatus;
  error?: string;
}

type MakeUpload = (id: string, file: File, onProgress: (loaded: number, total: number) => void) => UploadHandle;

export function useUploads(makeUpload: MakeUpload = uploadFile) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const handles = useRef(new Map<string, UploadHandle>());

  const patch = useCallback((id: string, change: (item: UploadItem) => UploadItem) => {
    setItems((all) => all.map((item) => (item.id === id ? change(item) : item)));
  }, []);

  const add = useCallback(
    (files: File[]) => {
      for (const file of files) {
        const id = crypto.randomUUID();
        if (file.size === 0) {
          setItems((all) => [
            ...all,
            { id, name: file.name, size: 0, loaded: 0, status: "error", error: "This file is empty" },
          ]);
          continue;
        }
        setItems((all) => [...all, { id, name: file.name, size: file.size, loaded: 0, status: "uploading" }]);
        const handle = makeUpload(id, file, (loaded) => patch(id, (item) => ({ ...item, loaded })));
        handles.current.set(id, handle);
        handle.promise
          .then(() => patch(id, (item) => ({ ...item, status: "done", loaded: item.size })))
          .catch((error: Error) =>
            patch(id, (item) => (item.status === "uploading" ? { ...item, status: "error", error: error.message } : item)),
          )
          .finally(() => handles.current.delete(id));
      }
    },
    [makeUpload, patch],
  );

  const remove = useCallback((id: string) => {
    handles.current.get(id)?.abort();
    handles.current.delete(id);
    setItems((all) => all.filter((item) => item.id !== id));
  }, []);

  const clear = useCallback(() => {
    handles.current.forEach((handle) => handle.abort());
    handles.current.clear();
    setItems([]);
  }, []);

  return {
    items,
    add,
    remove,
    clear,
    doneIds: items.filter((item) => item.status === "done").map((item) => item.id),
    busy: items.some((item) => item.status === "uploading"),
  };
}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run src/uploads.test.ts src/useUploads.test.tsx && npx tsc --noEmit`
Expected: all PASS, `tsc` clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/uploads.ts frontend/src/useUploads.ts frontend/src/uploads.test.ts frontend/src/useUploads.test.tsx
git commit -m "feat: streamed XHR uploads with progress and chip state"
```

---

### Task 6: Unlock screen and app shell

**Files:**
- Create: `frontend/src/styles/controls.css`
- Create: `frontend/src/components/Unlock.tsx`, `Unlock.css`, `Unlock.test.tsx`
- Create: `frontend/src/components/Notice.tsx`, `frontend/src/components/Main.tsx`, `Main.css`
- Modify: `frontend/src/App.tsx`, `frontend/src/App.test.tsx`, `frontend/src/main.tsx`

**Interfaces:**
- Consumes: `api`, `ApiError`, `setAuthHandlers`, `springs`
- Produces:
  - `Unlock({ mode: "new" | "locked", onUnlocked })` and `passphraseStrength(p) -> { level: 0|1|2|3, label }`, `MIN_PASSPHRASE = 10`
  - `Notice({ title, children })` — a centred message card
  - `Main({ onLocked })` — the three-column grid shell (Library `aria-label="Library"`, stage `aria-label="Stage"`, feed `aria-label="Live feed"`); later tasks fill the columns
  - `App` phases: `loading | forbidden | offline | new | locked | unlocked`

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/Unlock.test.tsx`:
```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, api } from "../api";
import { Unlock, passphraseStrength } from "./Unlock";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

test("strength labels", () => {
  expect(passphraseStrength("short")).toEqual({ level: 0, label: "Too short" });
  expect(passphraseStrength("abcdefghij").label).toBe("Fair");
  expect(passphraseStrength("abcdefghijkl").label).toBe("Good");
  expect(passphraseStrength("Abcdefghijk1").label).toBe("Good");
  expect(passphraseStrength("Abcdefghijklmnop1!").label).toBe("Strong");
});

test("creating needs a long enough, matching passphrase and shows the warning", async () => {
  const create = vi.spyOn(api, "createVault").mockResolvedValue({ ok: true });
  const onUnlocked = vi.fn();
  render(<Unlock mode="new" onUnlocked={onUnlocked} />);
  expect(screen.getByText(/can't be recovered/)).toBeInTheDocument();
  const submit = screen.getByRole("button", { name: "Create library" });
  expect(submit).toBeDisabled();
  await userEvent.type(screen.getByLabelText("Passphrase"), "correct horse battery");
  expect(submit).toBeDisabled();
  await userEvent.type(screen.getByLabelText("Confirm passphrase"), "correct horse batterX");
  expect(screen.getByRole("alert")).toHaveTextContent("Passphrases don't match");
  await userEvent.clear(screen.getByLabelText("Confirm passphrase"));
  await userEvent.type(screen.getByLabelText("Confirm passphrase"), "correct horse battery");
  expect(submit).toBeEnabled();
  await userEvent.click(submit);
  expect(create).toHaveBeenCalledWith("correct horse battery");
  await waitFor(() => expect(onUnlocked).toHaveBeenCalled());
});

test("a passphrase shorter than the minimum cannot be submitted", async () => {
  render(<Unlock mode="new" onUnlocked={vi.fn()} />);
  await userEvent.type(screen.getByLabelText("Passphrase"), "short");
  await userEvent.type(screen.getByLabelText("Confirm passphrase"), "short");
  expect(screen.getByRole("button", { name: "Create library" })).toBeDisabled();
});

test("a wrong passphrase shows an error and empties the field", async () => {
  vi.spyOn(api, "unlock").mockRejectedValue(new ApiError(401, "wrong passphrase"));
  render(<Unlock mode="locked" onUnlocked={vi.fn()} />);
  const field = screen.getByLabelText("Passphrase");
  await userEvent.type(field, "nope-nope-nope{Enter}");
  expect(await screen.findByRole("alert")).toHaveTextContent("Wrong passphrase");
  expect(field).toHaveValue("");
});

test("test_passphrase_is_cleared_and_never_stored", async () => {
  vi.spyOn(api, "unlock").mockResolvedValue({ ok: true });
  const { container } = render(<Unlock mode="locked" onUnlocked={() => {}} />);
  const field = screen.getByLabelText("Passphrase");
  expect(field).toHaveAttribute("type", "password");
  await userEvent.type(field, "my secret passphrase");
  await userEvent.click(screen.getByRole("button", { name: "Unlock" }));
  expect(field).toHaveValue("");
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
  expect(window.location.href).not.toContain("secret");
  expect(container.innerHTML).not.toContain("my secret passphrase");
});

test("a second submit while the first is pending is ignored", async () => {
  let release!: () => void;
  const unlock = vi.spyOn(api, "unlock").mockImplementation(
    () => new Promise((resolve) => { release = () => resolve({ ok: true }); }),
  );
  render(<Unlock mode="locked" onUnlocked={vi.fn()} />);
  await userEvent.type(screen.getByLabelText("Passphrase"), "my secret passphrase{Enter}");
  await userEvent.type(screen.getByLabelText("Passphrase"), "again again again{Enter}");
  expect(unlock).toHaveBeenCalledTimes(1);
  release();
});
```

`frontend/src/App.test.tsx` (replaces the shell test):
```tsx
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/components/Unlock.test.tsx src/App.test.tsx`
Expected: FAIL (cannot resolve `./Unlock`; `App` has no phases yet).

- [ ] **Step 3: Implement**

`frontend/src/styles/controls.css`:
```css
input[type="text"],
input[type="password"],
input[type="number"] {
  width: 100%;
  background: var(--raised);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 9px 12px;
  color: var(--text);
  transition: border-color 0.15s, box-shadow 0.15s;
}
input::placeholder { color: var(--muted); }
input:focus-visible {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent);
}

button { transition: background-color 0.15s, border-color 0.15s, transform 0.1s; }
button:active:not(:disabled) { transform: scale(0.97); }

button.primary {
  background: var(--accent);
  color: #0b0c0e;
  border: 0;
  border-radius: var(--radius);
  padding: 10px 16px;
  font-weight: 700;
}
button.primary:hover:not(:disabled) { background: #9d90f8; }

button.ghost {
  background: transparent;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 8px 12px;
}
button.ghost:hover:not(:disabled) { background: var(--raised); border-color: #343943; }
button.ghost.small { padding: 4px 10px; font-size: 12px; }

button.danger {
  background: transparent;
  color: var(--miss);
  border: 1px solid color-mix(in srgb, var(--miss) 45%, var(--line));
  border-radius: var(--radius);
  padding: 8px 12px;
}
button.danger:hover:not(:disabled) { background: color-mix(in srgb, var(--miss) 14%, transparent); }

.col-title {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
}
.live-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--exact);
  animation: live-pulse 2s ease-in-out infinite;
}
@keyframes live-pulse { 50% { opacity: 0.35; } }
```

`frontend/src/components/Unlock.css`:
```css
.unlock { min-height: 100%; display: grid; place-items: center; padding: 24px; }
.unlock-card {
  width: min(420px, 100%);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-drop);
  padding: 32px;
  box-shadow: var(--shadow-float);
}
.unlock-body { display: grid; gap: 14px; }
.brand { display: flex; align-items: center; gap: 8px; font-size: 12px; letter-spacing: 0.08em; color: var(--muted); }
.brand-dot { width: 8px; height: 8px; border-radius: 2px; background: var(--accent); }
.unlock-card h1 { margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.01em; }
.unlock-card p { margin: 0; }
.unlock-card label { display: grid; gap: 6px; color: var(--muted); font-size: 12px; }
.strength { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--muted); }
.strength-track { flex: 1; height: 4px; border-radius: 2px; background: var(--raised); overflow: hidden; }
.strength-bar { height: 100%; width: 8%; background: var(--miss); transition: width 0.25s, background-color 0.25s; }
.strength-bar[data-level="1"] { width: 38%; background: var(--fallback); }
.strength-bar[data-level="2"] { width: 68%; background: var(--head); }
.strength-bar[data-level="3"] { width: 100%; background: var(--exact); }
.warning {
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-left: 3px solid var(--fallback);
  border-radius: 8px;
  color: var(--muted);
  font-size: 12px;
}
.field-error { color: var(--miss); font-size: 12px; }
```

`frontend/src/components/Unlock.tsx`:
```tsx
import { useState, type FormEvent } from "react";
import { motion, useAnimationControls } from "motion/react";
import { ApiError, api } from "../api";
import { springs } from "../motion";
import "./Unlock.css";

export const MIN_PASSPHRASE = 10;

export function passphraseStrength(p: string): { level: 0 | 1 | 2 | 3; label: string } {
  if (p.length < MIN_PASSPHRASE) return { level: 0, label: "Too short" };
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((re) => re.test(p)).length;
  if (p.length >= 16 && classes >= 3) return { level: 3, label: "Strong" };
  if (p.length >= 12 || classes >= 3) return { level: 2, label: "Good" };
  return { level: 1, label: "Fair" };
}

interface Props {
  mode: "new" | "locked";
  onUnlocked: () => void;
}

export function Unlock({ mode, onUnlocked }: Props) {
  const [passphrase, setPassphrase] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const shake = useAnimationControls();
  const creating = mode === "new";
  const strength = passphraseStrength(passphrase);
  const mismatch = creating && confirm !== "" && confirm !== passphrase;
  const canSubmit =
    !pending && passphrase !== "" && (!creating || (passphrase.length >= MIN_PASSPHRASE && confirm === passphrase));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    setPending(true);
    setError(null);
    const secret = passphrase;
    setPassphrase(""); // the secret lives in state only until the request is sent
    setConfirm("");
    try {
      if (creating) await api.createVault(secret);
      else await api.unlock(secret);
      onUnlocked();
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 401 ? "Wrong passphrase" : e instanceof Error ? e.message : "Something went wrong",
      );
      void shake.start({ x: [0, -8, 8, -5, 5, 0], transition: { duration: 0.38 } });
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="unlock">
      <motion.form
        className="unlock-card"
        onSubmit={submit}
        aria-labelledby="unlock-title"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.screen}
      >
        <motion.div className="unlock-body" animate={shake}>
          <div className="brand mono">
            <span className="brand-dot" />
            burpweb
          </div>
          <h1 id="unlock-title">{creating ? "Create your library passphrase" : "Unlock your library"}</h1>
          <p className="muted">
            {creating
              ? "Snapshots are encrypted with this passphrase. It never leaves this machine."
              : "Enter your passphrase to open your snapshots."}
          </p>
          <label>
            Passphrase
            <input
              type="password"
              autoFocus
              autoComplete={creating ? "new-password" : "current-password"}
              value={passphrase}
              onChange={(e) => setPassphrase(e.target.value)}
            />
          </label>
          {creating && (
            <>
              <div className="strength" aria-live="polite">
                <div className="strength-track">
                  <div className="strength-bar" data-level={strength.level} />
                </div>
                <span>{strength.label}</span>
              </div>
              <label>
                Confirm passphrase
                <input
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                />
              </label>
              {mismatch && (
                <p className="field-error" role="alert">
                  Passphrases don't match
                </p>
              )}
              <p className="warning">If you forget this passphrase, stored snapshots can't be recovered.</p>
            </>
          )}
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="primary" disabled={!canSubmit}>
            {pending ? "Working…" : creating ? "Create library" : "Unlock"}
          </button>
        </motion.div>
      </motion.form>
    </main>
  );
}
```

`frontend/src/components/Notice.tsx`:
```tsx
import type { ReactNode } from "react";
import { motion } from "motion/react";
import { springs } from "../motion";
import "./Unlock.css";

export function Notice({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="unlock">
      <motion.div
        className="unlock-card"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.screen}
      >
        <div className="unlock-body">
          <div className="brand mono">
            <span className="brand-dot" />
            burpweb
          </div>
          <h1>{title}</h1>
          <div className="muted">{children}</div>
        </div>
      </motion.div>
    </main>
  );
}
```

`frontend/src/components/Main.css`:
```css
.main-grid {
  height: 100%;
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr) 360px;
  background: var(--bg);
}
.col { min-height: 0; display: flex; flex-direction: column; background: var(--panel); }
.col.library { border-right: 1px solid var(--line); }
.col.feed { border-left: 1px solid var(--line); }
.col.stage { background: var(--bg); overflow: auto; padding: 28px 32px; }
.col-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}
```

`frontend/src/components/Main.tsx` (the grid shell; Tasks 7–10 mount the real columns):
```tsx
import { api } from "../api";
import "./Main.css";

export function Main({ onLocked }: { onLocked: () => void }) {
  const lock = async () => {
    await api.lock().catch(() => {});
    onLocked();
  };
  return (
    <div className="main-grid">
      <aside className="col library" aria-label="Library">
        <header className="col-head">
          <span className="col-title">Library</span>
          <button className="ghost small" onClick={lock}>
            Lock
          </button>
        </header>
      </aside>
      <section className="col stage" aria-label="Stage" />
      <aside className="col feed" aria-label="Live feed" />
    </div>
  );
}
```

`frontend/src/App.tsx`:
```tsx
import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { ApiError, api, setAuthHandlers } from "./api";
import { Main } from "./components/Main";
import { Notice } from "./components/Notice";
import { Unlock } from "./components/Unlock";
import { springs } from "./motion";

type Phase = "loading" | "forbidden" | "offline" | "new" | "locked" | "unlocked";

export function App() {
  const [phase, setPhase] = useState<Phase>("loading");

  useEffect(() => {
    setAuthHandlers({
      locked: () => setPhase((p) => (p === "unlocked" ? "locked" : p)),
      forbidden: () => setPhase("forbidden"),
    });
    api
      .state()
      .then((state) => setPhase(state.vault))
      .catch((e) => setPhase(e instanceof ApiError && e.status === 403 ? "forbidden" : "offline"));
    return () => setAuthHandlers({});
  }, []);

  const screen = phase === "new" || phase === "locked" ? "unlock" : phase;
  return (
    <motion.div
      key={screen}
      className="screen"
      style={{ height: "100%" }}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springs.screen}
    >
      {phase === "loading" && <p className="muted" style={{ padding: 24 }}>Loading…</p>}
      {(phase === "new" || phase === "locked") && <Unlock mode={phase} onUnlocked={() => setPhase("unlocked")} />}
      {phase === "unlocked" && <Main onLocked={() => setPhase("locked")} />}
      {phase === "forbidden" && (
        <Notice title="Session expired">
          <p>This page's access token is no longer valid. Open the URL printed in the terminal where burpweb is running.</p>
        </Notice>
      )}
      {phase === "offline" && (
        <Notice title="Can't reach burpweb">
          <p>The server didn't answer. Check that burpweb is still running in your terminal, then reload this page.</p>
        </Notice>
      )}
    </motion.div>
  );
}
```

In `frontend/src/main.tsx`, add `import "./styles/controls.css";` after the `base.css` import.

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS, `tsc` clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: unlock screen, app phases and grid shell"
```

---

### Task 7: Library column (cards, rename, delete, lock)

**Files:**
- Modify: `frontend/src/types.ts` (add `View`), `frontend/src/components/Main.tsx`, `frontend/src/App.test.tsx`
- Create: `frontend/src/components/ConfirmDialog.tsx`, `ConfirmDialog.css`
- Create: `frontend/src/components/SnapshotCard.tsx`, `Library.tsx`, `Library.css`
- Test: `frontend/src/components/Library.test.tsx`, `frontend/src/components/Main.test.tsx`

**Interfaces:**
- Consumes: `Snapshot`, `ReplayState`, `api`, `formatDate`, `springs`, `fade`
- Produces:
  - `View = { kind: "new" } | { kind: "snapshot"; id: string }` (in `types.ts`)
  - `Library({ snapshots, view, replayingId, onSelect(view), onRename(id, name): Promise<void>, onDelete(id): Promise<void>, onLock() })`
  - `ConfirmDialog({ open, title, body, confirmLabel, onConfirm, onCancel })`
  - `Main` now loads snapshots and replay state, owns `view`, and handles rename, delete and lock

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/Library.test.tsx`:
```tsx
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Snapshot, View } from "../types";
import { Library } from "./Library";

const snap = (id: string, name: string, extra: Partial<Snapshot> = {}): Snapshot => ({
  id,
  name,
  created: "2026-10-15T10:00:00Z",
  files: [{ name: "a.xml", size: 10 }],
  stats: { items: 617, origins: 4, skipped: 30, malformed: [] },
  damaged: false,
  ...extra,
});

function setup(overrides: Partial<React.ComponentProps<typeof Library>> = {}) {
  const props = {
    snapshots: [snap("a", "Treasury"), snap("b", "Acme portal")],
    view: { kind: "snapshot", id: "a" } as View,
    replayingId: null as string | null,
    onSelect: vi.fn(),
    onRename: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn().mockResolvedValue(undefined),
    onLock: vi.fn(),
    ...overrides,
  };
  render(<Library {...props} />);
  return props;
}

test("lists snapshots with their stats and marks the selected one", () => {
  setup();
  const treasury = screen.getByRole("button", { name: /Treasury/ });
  expect(treasury).toHaveTextContent("617 items · 4 origins");
  expect(treasury.closest("li")).toHaveAttribute("aria-current", "true");
  expect(screen.getByRole("button", { name: /Acme portal/ }).closest("li")).not.toHaveAttribute("aria-current");
});

test("test_snapshot_name_is_rendered_as_text", () => {
  const evil = '<img src=x onerror="alert(1)">';
  setup({ snapshots: [snap("a", evil)] });
  expect(screen.getByText(evil)).toBeInTheDocument();
  expect(document.querySelector("img")).toBeNull();
});

test("selecting a snapshot and the new-snapshot button report the view", async () => {
  const { onSelect } = setup();
  await userEvent.click(screen.getByRole("button", { name: /Acme portal/ }));
  expect(onSelect).toHaveBeenCalledWith({ kind: "snapshot", id: "b" });
  await userEvent.click(screen.getByRole("button", { name: "+ New snapshot" }));
  expect(onSelect).toHaveBeenCalledWith({ kind: "new" });
});

test("rename saves on Enter and cancels on Escape", async () => {
  const { onRename } = setup();
  await userEvent.click(screen.getByRole("button", { name: "Rename" }));
  const field = screen.getByLabelText("Snapshot name");
  await userEvent.clear(field);
  await userEvent.type(field, "Treasury Q3{Enter}");
  expect(onRename).toHaveBeenCalledWith("a", "Treasury Q3");
  await waitFor(() => expect(screen.queryByLabelText("Snapshot name")).toBeNull());

  vi.mocked(onRename).mockClear();
  await userEvent.click(screen.getByRole("button", { name: "Rename" }));
  await userEvent.type(screen.getByLabelText("Snapshot name"), "x{Escape}");
  expect(onRename).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("Snapshot name")).toBeNull();
});

test("a failed rename keeps the editor open with the error", async () => {
  setup({ onRename: vi.fn().mockRejectedValue(new Error("snapshot damaged")) });
  await userEvent.click(screen.getByRole("button", { name: "Rename" }));
  await userEvent.type(screen.getByLabelText("Snapshot name"), "x{Enter}");
  expect(await screen.findByRole("alert")).toHaveTextContent("snapshot damaged");
  expect(screen.getByLabelText("Snapshot name")).toBeInTheDocument();
});

test("delete asks first, naming the snapshot, and only then deletes", async () => {
  const { onDelete } = setup();
  await userEvent.click(screen.getByRole("button", { name: "Delete" }));
  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveTextContent("Treasury");
  await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(onDelete).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

  await userEvent.click(screen.getByRole("button", { name: "Delete" }));
  await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }));
  expect(onDelete).toHaveBeenCalledWith("a");
});

test("damaged snapshots are flagged and cannot be renamed", () => {
  setup({ snapshots: [snap("a", "Broken", { damaged: true, stats: { items: 0, origins: 0, skipped: 0, malformed: [] } })] });
  expect(screen.getByText("Damaged")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Rename" })).toBeNull();
  expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
});

test("the replaying snapshot shows a live dot, and Lock is wired", async () => {
  const { onLock } = setup({ replayingId: "b" });
  expect(screen.getAllByRole("img", { name: "Replaying" })).toHaveLength(1);
  expect(screen.getByRole("button", { name: /Acme portal/ })).toContainElement(screen.getByRole("img", { name: "Replaying" }));
  await userEvent.click(screen.getByRole("button", { name: "Lock" }));
  expect(onLock).toHaveBeenCalled();
});

test("an empty library explains what to do", () => {
  setup({ snapshots: [], view: { kind: "new" } });
  expect(screen.getByText(/No snapshots yet/)).toBeInTheDocument();
});
```

`frontend/src/components/Main.test.tsx`:
```tsx
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api";
import type { Snapshot } from "../types";
import { Main } from "./Main";

const snap = (id: string, name: string): Snapshot => ({
  id, name, created: "2026-10-15T10:00:00Z", files: [{ name: "a.xml", size: 10 }],
  stats: { items: 5, origins: 1, skipped: 0, malformed: [] }, damaged: false,
});

afterEach(() => vi.restoreAllMocks());

function mockApi(list: Snapshot[]) {
  vi.spyOn(api, "snapshots").mockResolvedValue(list);
  vi.spyOn(api, "state").mockResolvedValue({ vault: "unlocked", replay: null });
}

test("loads the library and shows each snapshot", async () => {
  mockApi([snap("a", "Treasury"), snap("b", "Acme")]);
  render(<Main onLocked={vi.fn()} />);
  expect(await screen.findByRole("button", { name: /Treasury/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Acme/ })).toBeInTheDocument();
});

test("deleting a snapshot removes it from the library", async () => {
  mockApi([snap("a", "Treasury"), snap("b", "Acme")]);
  const remove = vi.spyOn(api, "remove").mockResolvedValue(undefined);
  render(<Main onLocked={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: /Acme/ }));
  await userEvent.click(screen.getByRole("button", { name: "Delete" }));
  await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete" }));
  expect(remove).toHaveBeenCalledWith("b");
  await waitFor(() => expect(screen.queryByRole("button", { name: /Acme/ })).toBeNull());
  expect(screen.getByRole("button", { name: /Treasury/ })).toBeInTheDocument();
});

test("renaming updates the card", async () => {
  mockApi([snap("a", "Treasury")]);
  vi.spyOn(api, "rename").mockResolvedValue({ ...snap("a", "Treasury Q3") });
  render(<Main onLocked={vi.fn()} />);
  await screen.findByRole("button", { name: /Treasury/ });
  await userEvent.click(screen.getByRole("button", { name: "Rename" }));
  const field = screen.getByLabelText("Snapshot name");
  await userEvent.clear(field);
  await userEvent.type(field, "Treasury Q3{Enter}");
  expect(await screen.findByRole("button", { name: /Treasury Q3/ })).toBeInTheDocument();
});

test("Lock locks the library and reports it", async () => {
  mockApi([]);
  const lock = vi.spyOn(api, "lock").mockResolvedValue({ ok: true });
  const onLocked = vi.fn();
  render(<Main onLocked={onLocked} />);
  await userEvent.click(await screen.findByRole("button", { name: "Lock" }));
  await waitFor(() => expect(onLocked).toHaveBeenCalled());
  expect(lock).toHaveBeenCalled();
});

test("a failed load is shown instead of an empty library", async () => {
  vi.spyOn(api, "snapshots").mockRejectedValue(new Error("boom"));
  vi.spyOn(api, "state").mockResolvedValue({ vault: "unlocked", replay: null });
  render(<Main onLocked={vi.fn()} />);
  expect(await screen.findByText(/Couldn't load the library/)).toBeInTheDocument();
});
```

Also update `frontend/src/App.test.tsx`: in the two tests that render an unlocked `App`, add `vi.spyOn(api, "snapshots").mockResolvedValue([]);` before `render(<App />)` (the main screen now loads the library).

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/components/Library.test.tsx src/components/Main.test.tsx`
Expected: FAIL (cannot resolve `./Library`; `Main` loads nothing yet).

- [ ] **Step 3: Implement**

Append to `frontend/src/types.ts`:
```ts
export type View = { kind: "new" } | { kind: "snapshot"; id: string };
```

`frontend/src/components/ConfirmDialog.css`:
```css
.dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  background: rgba(11, 12, 14, 0.72);
}
.dialog {
  width: min(400px, calc(100vw - 32px));
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-drop);
  padding: 24px;
  box-shadow: var(--shadow-float);
}
.dialog h2 { margin: 0 0 8px; font-size: 16px; }
.dialog p { margin: 0 0 20px; color: var(--muted); }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
```

`frontend/src/components/ConfirmDialog.tsx`:
```tsx
import { useEffect, useRef } from "react";
import { AnimatePresence, motion } from "motion/react";
import { fade, springs } from "../motion";
import "./ConfirmDialog.css";

interface Props {
  open: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({ open, title, body, confirmLabel, onConfirm, onCancel }: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    cancelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="dialog-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={fade}
          onClick={onCancel}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="dialog-title"
            className="dialog"
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0 }}
            transition={springs.screen}
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="dialog-title">{title}</h2>
            <p>{body}</p>
            <div className="dialog-actions">
              <button ref={cancelRef} className="ghost" onClick={onCancel}>
                Cancel
              </button>
              <button className="danger" onClick={onConfirm}>
                {confirmLabel}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
```

`frontend/src/components/Library.css`:
```css
.library .new-snapshot {
  margin: 12px 12px 4px;
  text-align: left;
  padding: 10px 12px;
  background: transparent;
  border: 1px dashed var(--line);
  border-radius: var(--radius);
  color: var(--muted);
}
.library .new-snapshot:hover { background: var(--raised); color: var(--text); }
.library .new-snapshot[data-active="true"] { border-style: solid; border-color: var(--accent); color: var(--text); }

.cards { list-style: none; margin: 0; padding: 8px 12px 12px; display: grid; gap: 6px; overflow: auto; }
.card { position: relative; border-radius: var(--radius); background: transparent; border: 1px solid transparent; }
.card:hover { background: var(--raised); }
.card[data-selected="true"] { background: var(--raised); border-color: var(--line); }
.card[data-selected="true"]::before {
  content: "";
  position: absolute;
  left: -1px; top: 10px; bottom: 10px;
  width: 3px;
  border-radius: 2px;
  background: var(--accent);
}
.card-main {
  display: grid;
  gap: 2px;
  width: 100%;
  padding: 10px 12px;
  background: none;
  border: 0;
  text-align: left;
}
.card-name { display: flex; align-items: center; gap: 8px; font-weight: 500; overflow-wrap: anywhere; }
.card-meta { font-size: 11px; color: var(--muted); }
.badge-damaged {
  font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
  padding: 1px 6px; border-radius: var(--radius-badge);
  background: color-mix(in srgb, var(--miss) 16%, transparent); color: var(--miss);
}
.card-actions { display: flex; gap: 6px; padding: 0 12px 10px; }
.card-edit { padding: 8px 12px 10px; display: grid; gap: 6px; }
.empty { padding: 16px; }
```

`frontend/src/components/SnapshotCard.tsx`:
```tsx
import { useState } from "react";
import { motion } from "motion/react";
import { formatDate } from "../format";
import { springs } from "../motion";
import type { Snapshot } from "../types";

interface Props {
  snapshot: Snapshot;
  selected: boolean;
  live: boolean;
  onSelect: () => void;
  onRename: (name: string) => Promise<void>;
  onDelete: () => void;
}

export function SnapshotCard({ snapshot, selected, live, onSelect, onRename, onDelete }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(snapshot.name);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    const name = draft.trim();
    if (!name || name === snapshot.name) {
      setEditing(false);
      return;
    }
    try {
      await onRename(name);
      setError(null);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not rename");
    }
  }

  function startEditing() {
    setDraft(snapshot.name);
    setError(null);
    setEditing(true);
  }

  return (
    <motion.li
      layout
      className="card"
      data-selected={selected}
      aria-current={selected ? "true" : undefined}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={springs.layout}
    >
      {editing ? (
        <div className="card-edit">
          <input
            type="text"
            aria-label="Snapshot name"
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void save();
              if (e.key === "Escape") setEditing(false);
            }}
          />
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
        </div>
      ) : (
        <button className="card-main" onClick={onSelect}>
          <span className="card-name">
            {snapshot.name}
            {live && <span className="live-dot" role="img" aria-label="Replaying" />}
            {snapshot.damaged && <span className="badge-damaged">Damaged</span>}
          </span>
          {!snapshot.damaged && (
            <span className="card-meta mono">
              {snapshot.stats.items.toLocaleString("en-US")} items · {snapshot.stats.origins} origins ·{" "}
              {formatDate(snapshot.created)}
            </span>
          )}
        </button>
      )}
      {selected && !editing && (
        <div className="card-actions">
          {!snapshot.damaged && (
            <button className="ghost small" onClick={startEditing}>
              Rename
            </button>
          )}
          <button className="danger small ghost" onClick={onDelete}>
            Delete
          </button>
        </div>
      )}
    </motion.li>
  );
}
```

`frontend/src/components/Library.tsx`:
```tsx
import { useState } from "react";
import { AnimatePresence } from "motion/react";
import type { Snapshot, View } from "../types";
import { ConfirmDialog } from "./ConfirmDialog";
import { SnapshotCard } from "./SnapshotCard";
import "./Library.css";

interface Props {
  snapshots: Snapshot[];
  view: View;
  replayingId: string | null;
  onSelect: (view: View) => void;
  onRename: (id: string, name: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onLock: () => void;
}

export function Library({ snapshots, view, replayingId, onSelect, onRename, onDelete, onLock }: Props) {
  const [pendingDelete, setPendingDelete] = useState<Snapshot | null>(null);

  return (
    <aside className="col library" aria-label="Library">
      <header className="col-head">
        <span className="col-title">Library</span>
        <button className="ghost small" onClick={onLock}>
          Lock
        </button>
      </header>
      <button className="new-snapshot" data-active={view.kind === "new"} onClick={() => onSelect({ kind: "new" })}>
        + New snapshot
      </button>
      <ul className="cards">
        <AnimatePresence initial={false}>
          {snapshots.map((snapshot) => (
            <SnapshotCard
              key={snapshot.id}
              snapshot={snapshot}
              selected={view.kind === "snapshot" && view.id === snapshot.id}
              live={replayingId === snapshot.id}
              onSelect={() => onSelect({ kind: "snapshot", id: snapshot.id })}
              onRename={(name) => onRename(snapshot.id, name)}
              onDelete={() => setPendingDelete(snapshot)}
            />
          ))}
        </AnimatePresence>
      </ul>
      {snapshots.length === 0 && <p className="muted empty">No snapshots yet. Drop a Burp export to create one.</p>}
      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete snapshot?"
        body={`“${pendingDelete?.name ?? ""}” will be permanently removed from the encrypted library.`}
        confirmLabel="Delete"
        onCancel={() => setPendingDelete(null)}
        onConfirm={async () => {
          const target = pendingDelete;
          setPendingDelete(null);
          if (target) await onDelete(target.id);
        }}
      />
    </aside>
  );
}
```

`frontend/src/components/Main.tsx` (replaces the Task 6 shell):
```tsx
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ReplayState, Snapshot, View } from "../types";
import { Library } from "./Library";
import "./Main.css";

export function Main({ onLocked }: { onLocked: () => void }) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [view, setView] = useState<View>({ kind: "new" });
  const [replay, setReplay] = useState<ReplayState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.snapshots(), api.state()])
      .then(([list, state]) => {
        if (cancelled) return;
        setSnapshots(list);
        setReplay(state.replay);
        const open = state.replay?.snapshot_id ?? list.at(-1)?.id;
        if (open) setView({ kind: "snapshot", id: open });
      })
      .catch((e: Error) => {
        if (!cancelled) setLoadError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rename = useCallback(async (id: string, name: string) => {
    const updated = await api.rename(id, name);
    setSnapshots((all) => all.map((s) => (s.id === id ? updated : s)));
  }, []);

  const remove = useCallback(async (id: string) => {
    await api.remove(id);
    setSnapshots((all) => all.filter((s) => s.id !== id));
    setView((v) => (v.kind === "snapshot" && v.id === id ? { kind: "new" } : v));
    setReplay((r) => (r?.snapshot_id === id ? null : r));
  }, []);

  const lock = useCallback(async () => {
    await api.lock().catch(() => {});
    onLocked();
  }, [onLocked]);

  return (
    <div className="main-grid">
      <Library
        snapshots={snapshots}
        view={view}
        replayingId={replay?.snapshot_id ?? null}
        onSelect={setView}
        onRename={rename}
        onDelete={remove}
        onLock={lock}
      />
      <section className="col stage" aria-label="Stage">
        {loadError && <p className="field-error" role="alert">Couldn't load the library: {loadError}</p>}
      </section>
      <aside className="col feed" aria-label="Live feed" />
    </div>
  );
}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS, `tsc` clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: library column with rename, delete and lock"
```

---

### Task 8: New-snapshot stage (drop zone, upload chips, window-wide drag)

**Files:**
- Create: `frontend/src/dnd.ts`, `frontend/src/dnd.test.tsx`
- Create: `frontend/src/components/DropZone.tsx`, `DropZone.css`, `DropZone.test.tsx`
- Create: `frontend/src/components/UploadChip.tsx`, `UploadChip.css`
- Create: `frontend/src/components/DragOverlay.tsx`, `DragOverlay.css`
- Create: `frontend/src/components/NewSnapshot.tsx`, `NewSnapshot.css`, `NewSnapshot.test.tsx`
- Create: `frontend/src/components/Main.drop.test.tsx`
- Modify: `frontend/src/components/Main.tsx`

**Interfaces:**
- Consumes: `useUploads` (return type `Uploads = ReturnType<typeof useUploads>`), `UploadItem`, `api`, `ApiError`, `formatBytes`, `springs`
- Produces:
  - `hasFiles(dt) -> boolean`; `useWindowDrop(onFiles, enabled?) -> dragging: boolean`. It always cancels file drops that no drop zone took, so the browser never navigates to a dropped file.
  - `DropZone({ onFiles, title, hint?, compact? })` — a `role="button"` zone with a hidden multi-file input
  - `UploadChip({ item, index, onRemove })`, `DragOverlay({ visible })`
  - `NewSnapshot({ uploads, onCreated(snapshot) })`
  - `Main` owns one `useUploads()`; a file dropped anywhere in the window switches to the new-snapshot stage and adds the files

- [ ] **Step 1: Write the failing tests**

`frontend/src/dnd.test.tsx`:
```tsx
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
```

`frontend/src/components/DropZone.test.tsx`:
```tsx
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
```

`frontend/src/components/NewSnapshot.test.tsx`:
```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, api } from "../api";
import type { UploadItem } from "../useUploads";
import { NewSnapshot } from "./NewSnapshot";

type Uploads = React.ComponentProps<typeof NewSnapshot>["uploads"];

const done = (id: string, name: string): UploadItem => ({ id, name, size: 100, loaded: 100, status: "done" });
const uploading = (id: string, name: string): UploadItem => ({ id, name, size: 100, loaded: 40, status: "uploading" });

function uploadsWith(items: UploadItem[]): Uploads {
  return {
    items,
    add: vi.fn(),
    remove: vi.fn(),
    clear: vi.fn(),
    doneIds: items.filter((i) => i.status === "done").map((i) => i.id),
    busy: items.some((i) => i.status === "uploading"),
  };
}

afterEach(() => vi.restoreAllMocks());

test("starts with the drop zone and a disabled Create button", () => {
  render(<NewSnapshot uploads={uploadsWith([])} onCreated={vi.fn()} />);
  expect(screen.getByRole("button", { name: /Drop Burp XML exports/ })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create snapshot" })).toBeDisabled();
});

test("files picked in the drop zone are handed to the uploads", async () => {
  const uploads = uploadsWith([]);
  const { container } = render(<NewSnapshot uploads={uploads} onCreated={vi.fn()} />);
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  await userEvent.upload(input, new File(["<items/>"], "history.xml"));
  expect(uploads.add).toHaveBeenCalledTimes(1);
});

test("the name is prefilled from the first file and stays editable", async () => {
  render(<NewSnapshot uploads={uploadsWith([done("u1", "history.xml")])} onCreated={vi.fn()} />);
  const name = screen.getByLabelText("Snapshot name");
  expect(name).toHaveValue("history");
  await userEvent.clear(name);
  await userEvent.type(name, "Treasury");
  expect(name).toHaveValue("Treasury");
});

test("Create sends the name and finished uploads, once, then clears and reports", async () => {
  let finish!: (s: unknown) => void;
  const create = vi.spyOn(api, "createSnapshot").mockImplementation(
    () => new Promise((resolve) => { finish = resolve as (s: unknown) => void; }),
  );
  const uploads = uploadsWith([done("u1", "a.xml"), done("u2", "b.xml")]);
  const onCreated = vi.fn();
  render(<NewSnapshot uploads={uploads} onCreated={onCreated} />);
  const button = screen.getByRole("button", { name: "Create snapshot" });
  await userEvent.dblClick(button);
  expect(create).toHaveBeenCalledTimes(1);
  expect(create).toHaveBeenCalledWith("a", ["u1", "u2"]);
  expect(screen.getByRole("button", { name: "Validating…" })).toBeDisabled();
  const snapshot = { id: "s1", name: "a" };
  finish(snapshot);
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(snapshot));
  expect(uploads.clear).toHaveBeenCalled();
});

test("Create waits for uploads that are still running", () => {
  render(<NewSnapshot uploads={uploadsWith([done("u1", "a.xml"), uploading("u2", "b.xml")])} onCreated={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Create snapshot" })).toBeDisabled();
});

test("a validation error is shown, and the stale uploads are discarded", async () => {
  vi.spyOn(api, "createSnapshot").mockRejectedValue(new ApiError(422, "no usable items in the uploaded export(s)"));
  const uploads = uploadsWith([done("u1", "a.xml")]);
  const onCreated = vi.fn();
  render(<NewSnapshot uploads={uploads} onCreated={onCreated} />);
  await userEvent.click(screen.getByRole("button", { name: "Create snapshot" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("no usable items in the uploaded export(s)");
  expect(screen.getByText(/uploads were discarded/)).toBeInTheDocument();
  expect(uploads.clear).toHaveBeenCalled();
  expect(onCreated).not.toHaveBeenCalled();
});

test("chips show progress and errors, and can be removed", async () => {
  const items: UploadItem[] = [
    uploading("u1", "big.xml"),
    { id: "u2", name: "empty.xml", size: 0, loaded: 0, status: "error", error: "This file is empty" },
  ];
  const uploads = uploadsWith(items);
  render(<NewSnapshot uploads={uploads} onCreated={vi.fn()} />);
  expect(screen.getByRole("progressbar", { name: "Upload progress for big.xml" })).toHaveAttribute("aria-valuenow", "40");
  expect(screen.getByText("This file is empty")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Remove big.xml" }));
  expect(uploads.remove).toHaveBeenCalledWith("u1");
});

test("with several files, the order hint explains that later files win", () => {
  render(<NewSnapshot uploads={uploadsWith([done("u1", "a.xml"), done("u2", "b.xml")])} onCreated={vi.fn()} />);
  expect(screen.getByText(/later files override earlier ones/i)).toBeInTheDocument();
});
```

`frontend/src/components/Main.drop.test.tsx`:
```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { api } from "../api";
import type { Snapshot } from "../types";
import { Main } from "./Main";

class FakeXhr {
  upload = { onprogress: null };
  onload = null;
  onerror = null;
  onabort = null;
  open() {}
  send() {}
  abort() {}
}

const snap: Snapshot = {
  id: "a", name: "Treasury", created: "2026-10-15T10:00:00Z", files: [{ name: "a.xml", size: 10 }],
  stats: { items: 5, origins: 1, skipped: 0, malformed: [] }, damaged: false,
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("a file dropped anywhere in the window starts a new snapshot", async () => {
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  vi.spyOn(api, "snapshots").mockResolvedValue([snap]);
  vi.spyOn(api, "state").mockResolvedValue({ vault: "unlocked", replay: null });
  render(<Main onLocked={vi.fn()} />);
  await screen.findByRole("button", { name: /Treasury/ }); // the library is showing a snapshot
  const dropped = new File(["<items/>"], "history.xml");
  fireEvent.dragEnter(window, { dataTransfer: { types: ["Files"], files: [dropped] } });
  expect(screen.getByText("Drop Burp XML exports")).toBeInTheDocument(); // the full-window overlay
  fireEvent.drop(window, { dataTransfer: { types: ["Files"], files: [dropped] } });
  expect(await screen.findByText("history.xml")).toBeInTheDocument(); // a chip on the new-snapshot stage
  expect(screen.getByRole("button", { name: "Create snapshot" })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/dnd.test.tsx src/components/DropZone.test.tsx src/components/NewSnapshot.test.tsx src/components/Main.test.tsx`
Expected: FAIL (cannot resolve `./dnd`, `./DropZone`, `./NewSnapshot`).

- [ ] **Step 3: Implement**

`frontend/src/dnd.ts`:
```ts
import { useEffect, useRef, useState } from "react";

export function hasFiles(dt: DataTransfer | null | undefined): boolean {
  return !!dt && Array.from(dt.types ?? []).includes("Files");
}

/**
 * Window-wide file drag handling. It also cancels file drops that no drop zone took:
 * without that, Firefox would navigate to the dropped XML file and unload the page.
 */
export function useWindowDrop(onFiles: (files: File[]) => void, enabled = true): boolean {
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);
  const latest = useRef(onFiles);
  latest.current = onFiles;

  useEffect(() => {
    if (!enabled) {
      depth.current = 0;
      setDragging(false);
      return;
    }
    const enter = (e: DragEvent) => {
      if (!hasFiles(e.dataTransfer)) return;
      depth.current += 1;
      setDragging(true);
    };
    const over = (e: DragEvent) => {
      if (hasFiles(e.dataTransfer)) e.preventDefault(); // required for the drop event to fire
    };
    const leave = (e: DragEvent) => {
      if (!hasFiles(e.dataTransfer)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e.dataTransfer)) return;
      depth.current = 0;
      setDragging(false);
      if (e.defaultPrevented) return; // a drop zone already took these files
      e.preventDefault();
      const dropped = Array.from(e.dataTransfer?.files ?? []);
      if (dropped.length) latest.current(dropped);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [enabled]);

  return dragging;
}
```

`frontend/src/components/DropZone.css`:
```css
.dropzone {
  display: grid;
  place-items: center;
  align-content: center;
  gap: 6px;
  min-height: 220px;
  padding: 28px;
  text-align: center;
  background: var(--panel);
  border: 1.5px dashed color-mix(in srgb, var(--accent) 55%, var(--line));
  border-radius: var(--radius-drop);
  cursor: pointer;
  animation: dropzone-breathe 2.4s ease-in-out infinite;
}
.dropzone[data-compact] { min-height: 84px; padding: 14px; }
.dropzone[data-over] {
  animation: none;
  border-style: solid;
  border-color: var(--accent);
  background: var(--raised);
}
.dropzone-icon { font-size: 22px; line-height: 1; color: var(--accent); }
.dropzone-title { font-size: 15px; font-weight: 700; }
.dropzone-hint { color: var(--muted); }
@keyframes dropzone-breathe {
  0%, 100% { border-color: color-mix(in srgb, var(--accent) 40%, var(--line)); }
  50% { border-color: color-mix(in srgb, var(--accent) 70%, var(--line)); }
}
```

`frontend/src/components/DropZone.tsx`:
```tsx
import { useRef, useState } from "react";
import { motion } from "motion/react";
import { hasFiles } from "../dnd";
import { springs } from "../motion";
import "./DropZone.css";

interface Props {
  title: string;
  hint?: string;
  compact?: boolean;
  onFiles: (files: File[]) => void;
}

export function DropZone({ title, hint, compact, onFiles }: Props) {
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  const input = useRef<HTMLInputElement>(null);

  const report = (list: FileList | null) => {
    if (list && list.length > 0) onFiles(Array.from(list));
  };

  return (
    <motion.div
      className="dropzone"
      data-compact={compact || undefined}
      data-over={over || undefined}
      role="button"
      tabIndex={0}
      aria-label={title}
      animate={{ scale: over ? 1.015 : 1 }}
      transition={springs.drop}
      onClick={() => input.current?.click()}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          input.current?.click();
        }
      }}
      onDragEnter={(e) => {
        if (!hasFiles(e.dataTransfer)) return;
        depth.current += 1;
        setOver(true);
      }}
      onDragOver={(e) => {
        if (hasFiles(e.dataTransfer)) e.preventDefault();
      }}
      onDragLeave={(e) => {
        if (!hasFiles(e.dataTransfer)) return;
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setOver(false);
      }}
      onDrop={(e) => {
        if (!hasFiles(e.dataTransfer)) return;
        e.preventDefault(); // the window-level handler sees this and does not deliver the files twice
        depth.current = 0;
        setOver(false);
        report(e.dataTransfer.files);
      }}
    >
      <input
        ref={input}
        type="file"
        multiple
        hidden
        onChange={(e) => {
          report(e.target.files);
          e.target.value = "";
        }}
      />
      <span className="dropzone-icon" aria-hidden>
        ⬆
      </span>
      <span className="dropzone-title">{compact ? "Add more files" : "Drop Burp XML exports"}</span>
      {hint && <span className="dropzone-hint">{hint}</span>}
    </motion.div>
  );
}
```

`frontend/src/components/UploadChip.css`:
```css
.chips { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.chip {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.chip[data-status="error"] { border-color: color-mix(in srgb, var(--miss) 50%, var(--line)); }
.chip-order { color: var(--muted); font-size: 11px; text-align: center; }
.chip-body { min-width: 0; display: grid; gap: 6px; }
.chip-line { display: flex; justify-content: space-between; gap: 12px; }
.chip-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.chip-size { color: var(--muted); font-size: 11px; }
.chip-track { height: 4px; border-radius: 2px; background: var(--raised); overflow: hidden; }
.chip-bar { height: 100%; width: 0; background: var(--accent); }
.chip[data-status="done"] .chip-bar { background: var(--exact); }
.chip-error { color: var(--miss); font-size: 12px; }
.chip-state { font-size: 13px; width: 16px; text-align: center; }
.chip[data-status="done"] .chip-state { color: var(--exact); }
.chip[data-status="error"] .chip-state { color: var(--miss); }
.chip-remove {
  width: 24px; height: 24px; line-height: 1; padding: 0;
  background: none; border: 0; border-radius: 6px; color: var(--muted); font-size: 16px;
}
.chip-remove:hover { background: var(--raised); color: var(--text); }
```

`frontend/src/components/UploadChip.tsx`:
```tsx
import { motion } from "motion/react";
import { formatBytes } from "../format";
import { springs } from "../motion";
import type { UploadItem } from "../useUploads";
import "./UploadChip.css";

interface Props {
  item: UploadItem;
  index: number;
  onRemove: () => void;
}

export function UploadChip({ item, index, onRemove }: Props) {
  const percent = item.size ? Math.min(100, (item.loaded / item.size) * 100) : 0;
  return (
    <motion.li
      layout
      className="chip"
      data-status={item.status}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={springs.layout}
    >
      <span className="chip-order mono">{index + 1}</span>
      <div className="chip-body">
        <div className="chip-line">
          <span className="chip-name">{item.name}</span>
          <span className="chip-size mono">{formatBytes(item.size)}</span>
        </div>
        {item.status === "error" ? (
          <span className="chip-error" role="alert">
            {item.error}
          </span>
        ) : (
          <div
            className="chip-track"
            role="progressbar"
            aria-label={`Upload progress for ${item.name}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(percent)}
          >
            <motion.div className="chip-bar" animate={{ width: `${percent}%` }} transition={springs.bar} />
          </div>
        )}
      </div>
      <span className="chip-state" aria-hidden>
        {item.status === "done" ? "✓" : item.status === "error" ? "!" : ""}
      </span>
      <button className="chip-remove" aria-label={`Remove ${item.name}`} onClick={onRemove}>
        ×
      </button>
    </motion.li>
  );
}
```

`frontend/src/components/DragOverlay.css`:
```css
.drag-overlay {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: grid;
  place-items: center;
  background: rgba(11, 12, 14, 0.82);
  pointer-events: none; /* drag events must keep reaching the page underneath */
}
.drag-overlay-frame {
  display: grid;
  gap: 6px;
  place-items: center;
  width: calc(100vw - 48px);
  height: calc(100vh - 48px);
  align-content: center;
  border: 2px dashed var(--accent);
  border-radius: 20px;
  box-shadow: var(--shadow-float);
}
.drag-overlay-title { font-size: 28px; font-weight: 700; letter-spacing: -0.01em; }
```

`frontend/src/components/DragOverlay.tsx`:
```tsx
import { AnimatePresence, motion } from "motion/react";
import "./DragOverlay.css";

export function DragOverlay({ visible }: { visible: boolean }) {
  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          className="drag-overlay"
          aria-hidden
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.12 }}
        >
          <div className="drag-overlay-frame">
            <div className="drag-overlay-title">Drop Burp XML exports</div>
            <div className="muted">to create a new snapshot</div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
```

`frontend/src/components/NewSnapshot.css`:
```css
.stage-page { max-width: 760px; display: grid; gap: 20px; }
.stage-title { margin: 0; font-size: 28px; font-weight: 700; letter-spacing: -0.02em; }
.stage-sub { margin: 4px 0 0; color: var(--muted); }
.field { display: grid; gap: 6px; color: var(--muted); font-size: 12px; }
.hint { color: var(--muted); font-size: 12px; margin: 0; }
.create-row { display: flex; align-items: center; gap: 14px; }
.validating-bar { flex: 1; height: 3px; border-radius: 2px; background: var(--raised); overflow: hidden; }
.validating-bar::after {
  content: "";
  display: block;
  height: 100%;
  width: 35%;
  background: var(--accent);
  animation: validating 1.1s ease-in-out infinite;
}
@keyframes validating { from { transform: translateX(-100%); } to { transform: translateX(290%); } }
```

`frontend/src/components/NewSnapshot.tsx`:
```tsx
import { useEffect, useRef, useState } from "react";
import { AnimatePresence } from "motion/react";
import { api } from "../api";
import type { Snapshot } from "../types";
import type { useUploads } from "../useUploads";
import { DropZone } from "./DropZone";
import { UploadChip } from "./UploadChip";
import "./NewSnapshot.css";

type Uploads = ReturnType<typeof useUploads>;

interface Props {
  uploads: Uploads;
  onCreated: (snapshot: Snapshot) => void;
}

export function NewSnapshot({ uploads, onCreated }: Props) {
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const touched = useRef(false);

  const firstName = uploads.items[0]?.name;
  useEffect(() => {
    if (!touched.current) setName(firstName ? firstName.replace(/\.[^.]+$/, "") : "");
  }, [firstName]);

  const canCreate = !creating && !uploads.busy && uploads.doneIds.length > 0 && name.trim() !== "";

  async function create() {
    if (!canCreate) return;
    setCreating(true);
    setError(null);
    try {
      const snapshot = await api.createSnapshot(name.trim(), uploads.doneIds);
      uploads.clear();
      onCreated(snapshot);
    } catch (e) {
      // The server discards every staged upload when it rejects a request, so the chips are stale.
      uploads.clear();
      setError(e instanceof Error ? e.message : "Could not create the snapshot");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="stage-page">
      <header>
        <h1 className="stage-title">New snapshot</h1>
        <p className="stage-sub">
          Drop the Burp XML exports from Proxy → HTTP history → Save items. Keep “Base64-encode requests and
          responses” ticked.
        </p>
      </header>

      <DropZone
        title="Drop Burp XML exports or click to browse"
        hint="You can add several files — frontend captures, later sessions."
        compact={uploads.items.length > 0}
        onFiles={uploads.add}
      />

      <ul className="chips" aria-label="Files to import">
        <AnimatePresence initial={false}>
          {uploads.items.map((item, index) => (
            <UploadChip key={item.id} item={item} index={index} onRemove={() => uploads.remove(item.id)} />
          ))}
        </AnimatePresence>
      </ul>
      {uploads.items.length > 1 && (
        <p className="hint">Order matters: later files override earlier ones for identical requests.</p>
      )}

      <label className="field">
        Snapshot name
        <input
          type="text"
          value={name}
          placeholder="e.g. Treasury portal, Oct 2026"
          onChange={(e) => {
            touched.current = true;
            setName(e.target.value);
          }}
        />
      </label>

      {error && (
        <div>
          <p className="field-error" role="alert">
            {error}
          </p>
          <p className="hint">The uploads were discarded; add the files again.</p>
        </div>
      )}

      <div className="create-row">
        <button className="primary" disabled={!canCreate} onClick={create} aria-busy={creating}>
          {creating ? "Validating…" : "Create snapshot"}
        </button>
        {creating && <div className="validating-bar" aria-hidden />}
      </div>
    </div>
  );
}
```

`frontend/src/components/Main.tsx` (replaces the Task 7 version):
```tsx
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useWindowDrop } from "../dnd";
import type { ReplayState, Snapshot, View } from "../types";
import { useUploads } from "../useUploads";
import { DragOverlay } from "./DragOverlay";
import { Library } from "./Library";
import { NewSnapshot } from "./NewSnapshot";
import "./Main.css";

export function Main({ onLocked }: { onLocked: () => void }) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [view, setView] = useState<View>({ kind: "new" });
  const [replay, setReplay] = useState<ReplayState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const uploads = useUploads();
  const dragging = useWindowDrop((files) => {
    setView({ kind: "new" });
    uploads.add(files);
  });

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.snapshots(), api.state()])
      .then(([list, state]) => {
        if (cancelled) return;
        setSnapshots(list);
        setReplay(state.replay);
        const open = state.replay?.snapshot_id ?? list.at(-1)?.id;
        if (open) setView({ kind: "snapshot", id: open });
      })
      .catch((e: Error) => {
        if (!cancelled) setLoadError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rename = useCallback(async (id: string, name: string) => {
    const updated = await api.rename(id, name);
    setSnapshots((all) => all.map((s) => (s.id === id ? updated : s)));
  }, []);

  const remove = useCallback(async (id: string) => {
    await api.remove(id);
    setSnapshots((all) => all.filter((s) => s.id !== id));
    setView((v) => (v.kind === "snapshot" && v.id === id ? { kind: "new" } : v));
    setReplay((r) => (r?.snapshot_id === id ? null : r));
  }, []);

  const created = useCallback((snapshot: Snapshot) => {
    setSnapshots((all) => [...all, snapshot]);
    setView({ kind: "snapshot", id: snapshot.id });
  }, []);

  const lock = useCallback(async () => {
    await api.lock().catch(() => {});
    onLocked();
  }, [onLocked]);

  return (
    <div className="main-grid">
      <Library
        snapshots={snapshots}
        view={view}
        replayingId={replay?.snapshot_id ?? null}
        onSelect={setView}
        onRename={rename}
        onDelete={remove}
        onLock={lock}
      />
      <section className="col stage" aria-label="Stage">
        {loadError && (
          <p className="field-error" role="alert">
            Couldn't load the library: {loadError}
          </p>
        )}
        {view.kind === "new" && <NewSnapshot uploads={uploads} onCreated={created} />}
      </section>
      <aside className="col feed" aria-label="Live feed" />
      <DragOverlay visible={dragging} />
    </div>
  );
}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS, `tsc` clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: new-snapshot stage with drop zone, chips and window-wide drag"
```

---

### Task 9: Toasts, snapshot view and replay controls

**Files:**
- Create: `frontend/src/useToasts.ts`, `frontend/src/useToasts.test.tsx`
- Create: `frontend/src/components/Toasts.tsx`, `Toasts.css`, `Toasts.test.tsx`
- Create: `frontend/src/components/SnapshotView.tsx`, `SnapshotView.css`, `SnapshotView.test.tsx`
- Create: `frontend/src/components/Main.snapshot.test.tsx`
- Modify: `frontend/src/components/Main.tsx`, `frontend/src/useUploads.ts` (export `MakeUpload`)

**Interfaces:**
- Consumes: `api`, `ReplayState`, `Snapshot`, `useUploads`/`MakeUpload`, `DropZone`, `UploadChip`, `formatBytes`, `formatDate`
- Produces:
  - `useToasts(autoDismissMs = 6000) -> { toasts, push(level, message), dismiss(id) }`. `info` toasts auto-dismiss, `error` toasts stay until dismissed, and an identical level+message already showing is not duplicated.
  - `Toasts({ toasts, onDismiss })`
  - `SnapshotView({ snapshot, replay, onStart(port), onStop(), onOpenBrowser(), onUpdated(snapshot), makeUpload? })`
  - `Main` now shows the snapshot view, starts/stops the replay and opens Firefox, and reports failures as toasts

- [ ] **Step 1: Write the failing tests**

`frontend/src/useToasts.test.tsx`:
```tsx
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
```

`frontend/src/components/Toasts.test.tsx`:
```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toasts } from "./Toasts";

test("errors are announced as alerts and info as status, both as text", () => {
  render(
    <Toasts
      toasts={[
        { id: 1, level: "error", message: "<b>address already in use</b>" },
        { id: 2, level: "info", message: "Opened Firefox" },
      ]}
      onDismiss={vi.fn()}
    />,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("<b>address already in use</b>");
  expect(document.querySelector("b")).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent("Opened Firefox");
});

test("the dismiss button reports the toast id", async () => {
  const onDismiss = vi.fn();
  render(<Toasts toasts={[{ id: 7, level: "error", message: "boom" }]} onDismiss={onDismiss} />);
  await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  await waitFor(() => expect(onDismiss).toHaveBeenCalledWith(7));
});
```

`frontend/src/components/SnapshotView.test.tsx`:
```tsx
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, api } from "../api";
import type { ReplayState, Snapshot } from "../types";
import type { MakeUpload } from "../useUploads";
import { SnapshotView } from "./SnapshotView";

const base: Snapshot = {
  id: "s1",
  name: "Treasury",
  created: "2026-10-15T10:00:00Z",
  files: [
    { name: "history.xml", size: 164518301 },
    { name: "frontend.xml", size: 346037 },
  ],
  stats: {
    items: 617,
    origins: 2,
    skipped: 30,
    malformed: [[1, "bad status line 'junk'"]],
    by_origin: [
      { origin: "https://shop.invalid", items: 600, paths: 72 },
      { origin: "https://fonts.gstatic.com", items: 17, paths: 3 },
    ],
  },
  damaged: false,
};

type Props = React.ComponentProps<typeof SnapshotView>;
function setup(overrides: Partial<Props> = {}) {
  const props: Props = {
    snapshot: base,
    replay: null,
    onStart: vi.fn().mockResolvedValue(undefined),
    onStop: vi.fn().mockResolvedValue(undefined),
    onOpenBrowser: vi.fn().mockResolvedValue(undefined),
    onUpdated: vi.fn(),
    ...overrides,
  };
  const view = render(<SnapshotView {...props} />);
  return { props, ...view };
}
const running = (id = "s1", port = 8081): ReplayState => ({ running: true, port, snapshot_id: id });
const instantUpload: MakeUpload = (_id, file, progress) => {
  progress(file.size, file.size);
  return { promise: Promise.resolve(), abort: () => {} };
};

afterEach(() => vi.restoreAllMocks());

test("shows the stats, the origins table and the files in order", () => {
  setup();
  expect(screen.getByRole("heading", { name: "Treasury" })).toBeInTheDocument();
  expect(screen.getByText("617")).toBeInTheDocument();
  expect(screen.getByText("30")).toBeInTheDocument();
  const rows = within(screen.getByRole("table")).getAllByRole("row");
  expect(rows).toHaveLength(3); // header + two origins
  expect(rows[1]).toHaveTextContent("600");
  expect(rows[1]).toHaveTextContent("https://shop.invalid");
  const files = screen.getAllByRole("listitem").filter((li) => li.closest("ol.files"));
  expect(files[0]).toHaveTextContent("history.xml");
  expect(files[0]).toHaveTextContent("164.5 MB");
  expect(files[1]).toHaveTextContent("frontend.xml");
});

test("malformed items are listed with their reasons", async () => {
  setup();
  const details = screen.getByText(/1 malformed item skipped/);
  await userEvent.click(details);
  expect(screen.getByText(/bad status line 'junk'/)).toBeInTheDocument();
});

test("Start uses the default port, or the one typed", async () => {
  const { props } = setup();
  await userEvent.click(screen.getByRole("button", { name: "Start replay" }));
  expect(props.onStart).toHaveBeenLastCalledWith(8081);
  const port = screen.getByLabelText("Replay port");
  await userEvent.clear(port);
  await userEvent.type(port, "9000");
  await userEvent.click(screen.getByRole("button", { name: "Start replay" }));
  expect(props.onStart).toHaveBeenLastCalledWith(9000);
});

test.each(["", "abc", "0", "70000", "80.5"])("an invalid port (%s) disables Start", async (value) => {
  setup();
  const port = screen.getByLabelText("Replay port");
  await userEvent.clear(port);
  if (value) await userEvent.type(port, value);
  expect(screen.getByRole("button", { name: "Start replay" })).toBeDisabled();
});

test("test_start_button_is_disabled_while_pending", async () => {
  let finish!: () => void;
  const onStart = vi.fn().mockImplementation(() => new Promise<void>((resolve) => { finish = resolve; }));
  setup({ onStart });
  const button = screen.getByRole("button", { name: "Start replay" });
  await userEvent.dblClick(button);
  expect(onStart).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Starting…" })).toBeDisabled();
  finish();
  await waitFor(() => expect(screen.getByRole("button", { name: "Start replay" })).toBeEnabled());
});

test("a running replay shows its address with Open Firefox and Stop", async () => {
  const { props } = setup({ replay: running() });
  expect(screen.getByText("Replaying on 127.0.0.1:8081")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Start replay" })).toBeNull();
  expect(screen.queryByLabelText("Replay port")).toBeNull(); // the address replaces the port field
  await userEvent.click(screen.getByRole("button", { name: "Open Firefox" }));
  expect(props.onOpenBrowser).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "Stop" }));
  expect(props.onStop).toHaveBeenCalledTimes(1);
});

test("when another snapshot is replaying, starting this one says it will switch", () => {
  setup({ replay: running("other") });
  expect(screen.getByText(/another snapshot is replaying/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Start replay" })).toBeEnabled();
});

test("a damaged snapshot cannot be started", () => {
  setup({ snapshot: { ...base, damaged: true } });
  expect(screen.getByText(/damaged and can't be replayed/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Start replay" })).toBeDisabled();
});

test("added files are sent to the snapshot and the updated snapshot is reported", async () => {
  const updated = { ...base, stats: { ...base.stats, items: 700 } };
  const addFiles = vi.spyOn(api, "addFiles").mockResolvedValue(updated);
  const { props, container } = setup({ makeUpload: instantUpload, replay: running() });
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  await userEvent.upload(input, new File(["<items/>"], "later.xml"));
  expect(await screen.findByText(/restart the replay/i)).toBeInTheDocument();
  const button = screen.getByRole("button", { name: "Add to snapshot" });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
  await waitFor(() => expect(props.onUpdated).toHaveBeenCalledWith(updated));
  expect(addFiles).toHaveBeenCalledWith("s1", [expect.any(String)]);
});

test("a rejected add shows the error and discards the stale uploads", async () => {
  vi.spyOn(api, "addFiles").mockRejectedValue(new ApiError(422, "no usable items"));
  const { container } = setup({ makeUpload: instantUpload });
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  await userEvent.upload(input, new File(["<items/>"], "bad.xml"));
  const button = await screen.findByRole("button", { name: "Add to snapshot" });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
  expect(await screen.findByRole("alert")).toHaveTextContent("no usable items");
  await waitFor(() => expect(screen.queryByText("bad.xml")).toBeNull()); // after the chip's exit animation
});
```

`frontend/src/components/Main.snapshot.test.tsx`:
```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, api } from "../api";
import type { Snapshot } from "../types";
import { Main } from "./Main";

const snap = (id: string, name: string): Snapshot => ({
  id, name, created: "2026-10-15T10:00:00Z", files: [{ name: "a.xml", size: 10 }],
  stats: { items: 5, origins: 1, skipped: 0, malformed: [] }, damaged: false,
});

beforeEach(() => {
  vi.spyOn(api, "snapshots").mockResolvedValue([snap("a", "Treasury"), snap("b", "Acme")]);
  vi.spyOn(api, "state").mockResolvedValue({ vault: "unlocked", replay: null });
});
afterEach(() => vi.restoreAllMocks());

test("the newest snapshot opens first, and selecting another switches the stage", async () => {
  render(<Main onLocked={vi.fn()} />);
  expect(await screen.findByRole("heading", { name: "Acme" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Treasury/ }));
  expect(await screen.findByRole("heading", { name: "Treasury" })).toBeInTheDocument();
});

test("Start replay calls the API and marks the snapshot live", async () => {
  const start = vi.spyOn(api, "startReplay").mockResolvedValue({ snapshot_id: "b", port: 8081, running: true });
  render(<Main onLocked={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Start replay" }));
  expect(start).toHaveBeenCalledWith("b", 8081);
  expect(await screen.findByText("Replaying on 127.0.0.1:8081")).toBeInTheDocument();
  expect(screen.getAllByRole("img", { name: "Replaying" }).length).toBeGreaterThan(0);
});

test("a failed start is shown as a toast and the button comes back", async () => {
  vi.spyOn(api, "startReplay").mockRejectedValue(new ApiError(409, "address already in use"));
  render(<Main onLocked={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Start replay" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("address already in use");
  await waitFor(() => expect(screen.getByRole("button", { name: "Start replay" })).toBeEnabled());
});

test("Stop and Open Firefox call the API", async () => {
  vi.spyOn(api, "state").mockResolvedValue({
    vault: "unlocked",
    replay: { running: true, port: 8081, snapshot_id: "b" },
  });
  const stop = vi.spyOn(api, "stopReplay").mockResolvedValue(undefined);
  const open = vi.spyOn(api, "openBrowser").mockResolvedValue({ ok: true });
  render(<Main onLocked={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Open Firefox" }));
  expect(open).toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Stop" }));
  expect(stop).toHaveBeenCalled();
  expect(await screen.findByRole("button", { name: "Start replay" })).toBeInTheDocument();
});

test("a missing Firefox is reported with the server's message", async () => {
  vi.spyOn(api, "state").mockResolvedValue({
    vault: "unlocked",
    replay: { running: true, port: 8081, snapshot_id: "b" },
  });
  vi.spyOn(api, "openBrowser").mockRejectedValue(new ApiError(409, "firefox/certutil not available"));
  render(<Main onLocked={vi.fn()} />);
  await userEvent.click(await screen.findByRole("button", { name: "Open Firefox" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("firefox/certutil not available");
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/useToasts.test.tsx src/components/Toasts.test.tsx src/components/SnapshotView.test.tsx src/components/Main.snapshot.test.tsx`
Expected: FAIL (cannot resolve `./useToasts`, `./Toasts`, `./SnapshotView`).

- [ ] **Step 3: Implement**

In `frontend/src/useUploads.ts`, change `type MakeUpload = ...` to `export type MakeUpload = ...`.

`frontend/src/useToasts.ts`:
```ts
import { useCallback, useEffect, useRef, useState } from "react";

export interface Toast {
  id: number;
  level: "error" | "info";
  message: string;
}

export function useToasts(autoDismissMs = 6000) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const current = useRef<Toast[]>([]); // mirrors state so push() can de-duplicate without side effects in an updater
  const nextId = useRef(1);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    current.current = current.current.filter((t) => t.id !== id);
    setToasts(current.current);
  }, []);

  const push = useCallback(
    (level: Toast["level"], message: string) => {
      if (current.current.some((t) => t.level === level && t.message === message)) return;
      const toast = { id: nextId.current++, level, message };
      current.current = [...current.current, toast];
      setToasts(current.current);
      if (level === "info") timers.current.set(toast.id, setTimeout(() => dismiss(toast.id), autoDismissMs));
    },
    [autoDismissMs, dismiss],
  );

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach((timer) => clearTimeout(timer));
  }, []);

  return { toasts, push, dismiss };
}
```

`frontend/src/components/Toasts.css`:
```css
.toasts {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 60;
  display: grid;
  gap: 8px;
  width: min(380px, calc(100vw - 40px));
}
.toast {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  background: var(--raised);
  border: 1px solid var(--line);
  border-left: 3px solid var(--head);
  border-radius: var(--radius);
  box-shadow: var(--shadow-float);
  overflow-wrap: anywhere;
}
.toast[data-level="error"] { border-left-color: var(--miss); }
.toast button { background: none; border: 0; color: var(--muted); font-size: 16px; line-height: 1; padding: 0 2px; }
.toast button:hover { color: var(--text); }
```

`frontend/src/components/Toasts.tsx`:
```tsx
import { AnimatePresence, motion } from "motion/react";
import { springs } from "../motion";
import type { Toast } from "../useToasts";
import "./Toasts.css";

interface Props {
  toasts: Toast[];
  onDismiss: (id: number) => void;
}

export function Toasts({ toasts, onDismiss }: Props) {
  return (
    <div className="toasts" aria-live="polite">
      <AnimatePresence>
        {toasts.map((toast) => (
          <motion.div
            key={toast.id}
            layout
            className="toast"
            data-level={toast.level}
            role={toast.level === "error" ? "alert" : "status"}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={springs.screen}
          >
            <span>{toast.message}</span>
            <button aria-label="Dismiss" onClick={() => onDismiss(toast.id)}>
              ×
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
```

`frontend/src/components/SnapshotView.css`:
```css
.replay-panel {
  display: grid;
  gap: 12px;
  padding: 16px 18px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-drop);
}
.replay-panel[data-running="true"] { border-color: color-mix(in srgb, var(--exact) 45%, var(--line)); }
.replay-status { display: flex; align-items: center; gap: 10px; font-weight: 500; }
.replay-controls { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
.port-field { width: 120px; display: grid; gap: 6px; color: var(--muted); font-size: 12px; }
.tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.tile { padding: 14px 16px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); }
.tile-value { font-family: var(--font-mono); font-size: 22px; font-weight: 600; }
.tile-label { color: var(--muted); font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; }
.section-title { margin: 0 0 8px; }
.origins { width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); }
.origins th {
  text-align: left; font-weight: 500; color: var(--muted); font-size: 11px;
  letter-spacing: 0.06em; text-transform: uppercase; padding: 8px 12px;
}
.origins td { padding: 8px 12px; border-top: 1px solid var(--line); }
.origins td.origin { overflow-wrap: anywhere; }
.files { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.files li {
  display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; gap: 12px; align-items: center;
  padding: 8px 12px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius);
}
.files .order { color: var(--muted); font-size: 11px; text-align: center; }
.malformed summary { cursor: pointer; color: var(--fallback); }
.malformed ul { margin: 8px 0 0; padding-left: 18px; color: var(--muted); }
.add-files { display: grid; gap: 12px; }
```

`frontend/src/components/SnapshotView.tsx`:
```tsx
import { useState } from "react";
import { AnimatePresence } from "motion/react";
import { api } from "../api";
import { formatBytes, formatDate } from "../format";
import type { ReplayState, Snapshot } from "../types";
import { useUploads, type MakeUpload } from "../useUploads";
import { DropZone } from "./DropZone";
import { UploadChip } from "./UploadChip";
import "./NewSnapshot.css"; // shared stage layout
import "./SnapshotView.css";

interface Props {
  snapshot: Snapshot;
  replay: ReplayState | null;
  onStart: (port: number) => Promise<void>;
  onStop: () => Promise<void>;
  onOpenBrowser: () => Promise<void>;
  onUpdated: (snapshot: Snapshot) => void;
  makeUpload?: MakeUpload;
}

export function SnapshotView({ snapshot, replay, onStart, onStop, onOpenBrowser, onUpdated, makeUpload }: Props) {
  const [port, setPort] = useState("8081");
  const [busy, setBusy] = useState<"start" | "stop" | "browser" | null>(null);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const uploads = useUploads(makeUpload);

  const portNumber = /^\d{1,5}$/.test(port) ? Number(port) : NaN;
  const portValid = portNumber >= 1 && portNumber <= 65535;
  const running = !!replay?.running && replay.snapshot_id === snapshot.id;
  const elsewhere = !!replay?.running && replay.snapshot_id !== snapshot.id;
  const { stats } = snapshot;

  async function run(kind: "start" | "stop" | "browser", action: () => Promise<void>) {
    if (busy) return;
    setBusy(kind);
    try {
      await action();
    } finally {
      setBusy(null);
    }
  }

  async function addFiles() {
    if (adding || uploads.busy || uploads.doneIds.length === 0) return;
    setAdding(true);
    setAddError(null);
    try {
      const updated = await api.addFiles(snapshot.id, uploads.doneIds);
      uploads.clear();
      onUpdated(updated);
    } catch (e) {
      uploads.clear(); // the server discards staged uploads when it rejects a request
      setAddError(e instanceof Error ? e.message : "Could not add the files");
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className="stage-page">
      <header>
        <h1 className="stage-title">{snapshot.name}</h1>
        <p className="stage-sub">
          Created {formatDate(snapshot.created)} · {snapshot.files.length} file{snapshot.files.length === 1 ? "" : "s"}
        </p>
      </header>

      <section className="replay-panel" data-running={running} aria-label="Replay">
        {running ? (
          <>
            <div className="replay-status">
              <span className="live-dot" aria-hidden />
              <span>Replaying on 127.0.0.1:{replay?.port}</span>
            </div>
            <div className="replay-controls">
              <button className="primary" disabled={busy !== null} onClick={() => run("browser", onOpenBrowser)}>
                Open Firefox
              </button>
              <button className="danger" disabled={busy !== null} onClick={() => run("stop", onStop)}>
                Stop
              </button>
            </div>
          </>
        ) : (
          <>
            {snapshot.damaged && (
              <p className="field-error">This snapshot is damaged and can't be replayed. You can still delete it.</p>
            )}
            {elsewhere && <p className="hint">Another snapshot is replaying — starting this one will switch the replay.</p>}
            <div className="replay-controls">
              <label className="port-field">
                Replay port
                <input
                  type="text"
                  inputMode="numeric"
                  aria-label="Replay port"
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                />
              </label>
              <button
                className="primary"
                disabled={snapshot.damaged || !portValid || busy !== null}
                onClick={() => run("start", () => onStart(portNumber))}
              >
                {busy === "start" ? "Starting…" : "Start replay"}
              </button>
            </div>
          </>
        )}
      </section>

      <section className="tiles" aria-label="Snapshot statistics">
        <Tile value={stats.items} label="Items" />
        <Tile value={stats.origins} label="Origins" />
        <Tile value={stats.skipped} label="No response" />
        <Tile value={stats.malformed.length} label="Malformed" />
      </section>

      {stats.malformed.length > 0 && (
        <details className="malformed">
          <summary>
            {stats.malformed.length} malformed item{stats.malformed.length === 1 ? "" : "s"} skipped
          </summary>
          <ul>
            {stats.malformed.map(([index, reason]) => (
              <li key={index}>
                <span className="mono">#{index}</span> {reason}
              </li>
            ))}
          </ul>
        </details>
      )}

      {stats.by_origin && stats.by_origin.length > 0 && (
        <section>
          <h2 className="col-title section-title">Origins</h2>
          <table className="origins">
            <thead>
              <tr>
                <th>Items</th>
                <th>Paths</th>
                <th>Origin</th>
              </tr>
            </thead>
            <tbody>
              {stats.by_origin.map((row) => (
                <tr key={row.origin}>
                  <td className="mono">{row.items.toLocaleString("en-US")}</td>
                  <td className="mono">{row.paths.toLocaleString("en-US")}</td>
                  <td className="mono origin">{row.origin}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section>
        <h2 className="col-title section-title">Files</h2>
        <ol className="files">
          {snapshot.files.map((file, index) => (
            <li key={`${file.name}-${index}`}>
              <span className="order mono">{index + 1}</span>
              <span>{file.name}</span>
              <span className="muted mono">{formatBytes(file.size)}</span>
            </li>
          ))}
        </ol>
      </section>

      <section className="add-files" aria-label="Add files">
        <DropZone compact title="Add more files to this snapshot" hint="Later files override earlier ones" onFiles={uploads.add} />
        <ul className="chips" aria-label="Files to add">
          <AnimatePresence initial={false}>
            {uploads.items.map((item, index) => (
              <UploadChip key={item.id} item={item} index={index} onRemove={() => uploads.remove(item.id)} />
            ))}
          </AnimatePresence>
        </ul>
        {uploads.items.length > 0 && running && (
          <p className="hint">Restart the replay afterwards to use the new files.</p>
        )}
        {addError && (
          <p className="field-error" role="alert">
            {addError}
          </p>
        )}
        {uploads.items.length > 0 && (
          <div>
            <button
              className="primary"
              disabled={adding || uploads.busy || uploads.doneIds.length === 0}
              onClick={addFiles}
            >
              {adding ? "Adding…" : "Add to snapshot"}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}

function Tile({ value, label }: { value: number; label: string }) {
  return (
    <div className="tile">
      <div className="tile-value">{value.toLocaleString("en-US")}</div>
      <div className="tile-label">{label}</div>
    </div>
  );
}
```

`frontend/src/components/Main.tsx` (replaces the Task 8 version):
```tsx
import { useCallback, useEffect, useState } from "react";
import { motion } from "motion/react";
import { api } from "../api";
import { useWindowDrop } from "../dnd";
import { springs } from "../motion";
import type { ReplayState, Snapshot, View } from "../types";
import { useToasts } from "../useToasts";
import { useUploads } from "../useUploads";
import { DragOverlay } from "./DragOverlay";
import { Library } from "./Library";
import { NewSnapshot } from "./NewSnapshot";
import { SnapshotView } from "./SnapshotView";
import { Toasts } from "./Toasts";
import "./Main.css";

const messageOf = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export function Main({ onLocked }: { onLocked: () => void }) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [view, setView] = useState<View>({ kind: "new" });
  const [replay, setReplay] = useState<ReplayState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const { toasts, push, dismiss } = useToasts();
  const uploads = useUploads();
  const dragging = useWindowDrop((files) => {
    setView({ kind: "new" });
    uploads.add(files);
  });

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.snapshots(), api.state()])
      .then(([list, state]) => {
        if (cancelled) return;
        setSnapshots(list);
        setReplay(state.replay);
        const open = state.replay?.snapshot_id ?? list.at(-1)?.id;
        if (open) setView({ kind: "snapshot", id: open });
      })
      .catch((e: Error) => {
        if (!cancelled) setLoadError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rename = useCallback(async (id: string, name: string) => {
    const updated = await api.rename(id, name);
    setSnapshots((all) => all.map((s) => (s.id === id ? updated : s)));
  }, []);

  const remove = useCallback(async (id: string) => {
    await api.remove(id);
    setSnapshots((all) => all.filter((s) => s.id !== id));
    setView((v) => (v.kind === "snapshot" && v.id === id ? { kind: "new" } : v));
    setReplay((r) => (r?.snapshot_id === id ? null : r));
  }, []);

  const created = useCallback((snapshot: Snapshot) => {
    setSnapshots((all) => [...all, snapshot]);
    setView({ kind: "snapshot", id: snapshot.id });
  }, []);

  const updated = useCallback((snapshot: Snapshot) => {
    setSnapshots((all) => all.map((s) => (s.id === snapshot.id ? snapshot : s)));
  }, []);

  const start = useCallback(
    async (id: string, port: number) => {
      try {
        const result = await api.startReplay(id, port);
        setReplay({ running: true, port: result.port, snapshot_id: id });
      } catch (e) {
        push("error", messageOf(e));
      }
    },
    [push],
  );

  const stop = useCallback(async () => {
    try {
      await api.stopReplay();
      setReplay(null);
    } catch (e) {
      push("error", messageOf(e));
    }
  }, [push]);

  const openBrowser = useCallback(async () => {
    try {
      await api.openBrowser();
      push("info", "Opened Firefox with the replay proxy");
    } catch (e) {
      push("error", messageOf(e));
    }
  }, [push]);

  const lock = useCallback(async () => {
    await api.lock().catch(() => {});
    onLocked();
  }, [onLocked]);

  const selected = view.kind === "snapshot" ? snapshots.find((s) => s.id === view.id) : undefined;

  return (
    <div className="main-grid">
      <Library
        snapshots={snapshots}
        view={view}
        replayingId={replay?.snapshot_id ?? null}
        onSelect={setView}
        onRename={rename}
        onDelete={remove}
        onLock={lock}
      />
      <section className="col stage" aria-label="Stage">
        {loadError && (
          <p className="field-error" role="alert">
            Couldn't load the library: {loadError}
          </p>
        )}
        <motion.div
          key={view.kind === "snapshot" ? view.id : "new"}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={springs.screen}
        >
          {view.kind === "new" && <NewSnapshot uploads={uploads} onCreated={created} />}
          {selected && (
            <SnapshotView
              snapshot={selected}
              replay={replay}
              onStart={(port) => start(selected.id, port)}
              onStop={stop}
              onOpenBrowser={openBrowser}
              onUpdated={updated}
            />
          )}
        </motion.div>
      </section>
      <aside className="col feed" aria-label="Live feed" />
      <DragOverlay visible={dragging} />
      <Toasts toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS, `tsc` clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: snapshot view, replay controls and toasts"
```

---

### Task 10: Live feed, misses tab and event wiring

**Files:**
- Create: `frontend/src/test-utils.ts`, `frontend/src/components/Feed.tsx`, `Feed.css`, `Feed.test.tsx`
- Create: `frontend/src/components/Main.events.test.tsx`
- Modify: `frontend/src/test-setup.ts`, `frontend/src/components/Main.tsx`

**Interfaces:**
- Consumes: `FeedState`, `feedReducer`, `emptyFeed`, `visibleRows`, `TierFilter`, `useEvents`, `ConnectionStatus`, `splitUrl`, `EventMsg`
- Produces:
  - `FakeWebSocket` (test utility: `instances`, `open()`, `emit(event)`, `drop()`), installed as the global `WebSocket` for every test by `test-setup.ts`
  - `Feed({ state, status, running, onCopied?(count) })` — the whole `aria-label="Live feed"` column: Live and Misses tabs, tier filters with counts, a "Reconnecting…" pill
  - `Main` connects the WebSocket and routes events: request/blocked/misses → feed, `replay` → replay state (and clears the feed on start), `toast` → toast, a dropped socket → re-check the library state (a locked library returns to the unlock screen)

- [ ] **Step 1: Write the failing tests**

`frontend/src/test-utils.ts`:
```ts
/** Stands in for the browser WebSocket in every test; see test-setup.ts. */
export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  close() {
    this.closed = true;
  }
  open() {
    this.onopen?.();
  }
  emit(event: unknown) {
    this.onmessage?.({ data: JSON.stringify(event) });
  }
  drop() {
    this.onclose?.();
  }
}
```

`frontend/src/test-setup.ts` (replaces the Task 2 version):
```ts
import "@testing-library/jest-dom/vitest";
import { FakeWebSocket } from "./test-utils";

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});
afterEach(() => {
  vi.unstubAllGlobals();
});
```

`frontend/src/components/Feed.test.tsx`:
```tsx
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { emptyFeed, feedReducer, type FeedState } from "../feed";
import type { EventMsg } from "../types";
import { Feed } from "./Feed";

// Vitest stubs CSS imports (even ?raw gives an empty string), so read the stylesheet from disk.
const feedCss = readFileSync(join(process.cwd(), "src/components/Feed.css"), "utf8"); // tests run from frontend/

const request = (n: number, tier: "EXACT" | "FALLBACK" | "MISS", url = `https://shop.invalid/p${n}`): EventMsg => ({
  type: "request", tier, method: "GET", url, status: tier === "MISS" ? 404 : 200,
  item: tier === "FALLBACK" ? "trjs #4" : null, ts: n,
});
const build = (events: EventMsg[]): FeedState =>
  events.reduce((state, event) => feedReducer(state, { type: "event", event }), emptyFeed());

function setup(overrides: Partial<React.ComponentProps<typeof Feed>> = {}) {
  const props = { state: emptyFeed(), status: "open" as const, running: true, onCopied: vi.fn(), ...overrides };
  render(<Feed {...props} />);
  return props;
}

afterEach(() => vi.restoreAllMocks());

test("empty states say what to do", () => {
  setup({ running: false });
  expect(screen.getByText(/Start a replay to see requests here/)).toBeInTheDocument();
});

test("a running replay with no traffic yet waits for requests", () => {
  setup({ running: true });
  expect(screen.getByText(/Waiting for requests/)).toBeInTheDocument();
});

test("rows are newest first and show badge, method, url, status and source item", () => {
  setup({ state: build([request(1, "EXACT"), request(2, "FALLBACK")]) });
  const rows = within(screen.getByRole("list", { name: "Requests" })).getAllByRole("listitem");
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent("FALLBACK");
  expect(rows[0]).toHaveTextContent("https://shop.invalid/p2");
  expect(rows[0]).toHaveTextContent("trjs #4");
  expect(rows[1]).toHaveTextContent("EXACT");
  expect(rows[1]).toHaveTextContent("200");
});

test("blocked connections appear as BLOCKED rows", () => {
  setup({ state: build([{ type: "blocked", address: "10.0.0.5:22", ts: 1 }]) });
  const row = screen.getByRole("listitem");
  expect(row).toHaveTextContent("BLOCKED");
  expect(row).toHaveTextContent("10.0.0.5:22");
});

test("filter chips show counts and narrow the list", async () => {
  setup({ state: build([request(1, "EXACT"), request(2, "MISS"), request(3, "EXACT")]) });
  expect(screen.getByRole("button", { name: "ALL 3" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "EXACT 2" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "MISS 1" }));
  const rows = within(screen.getByRole("list", { name: "Requests" })).getAllByRole("listitem");
  expect(rows).toHaveLength(1);
  expect(rows[0]).toHaveTextContent("MISS");
  expect(screen.getByRole("button", { name: "MISS 1" })).toHaveAttribute("aria-pressed", "true");
});

test("test_long_url_is_one_ellipsized_line", () => {
  const long = "https://shop.invalid/" + "a".repeat(600) + "?token=" + "b".repeat(300);
  setup({ state: build([request(1, "EXACT", long)]) });
  const url = document.querySelector(".row-url") as HTMLElement;
  expect(url).toHaveAttribute("title", long); // the full URL is one hover away
  const rule = /\.row-url\s*\{[^}]*\}/.exec(feedCss)![0];
  expect(rule).toMatch(/white-space:\s*nowrap/);
  expect(rule).toMatch(/overflow:\s*hidden/);
  expect(rule).toMatch(/text-overflow:\s*ellipsis/);
});

test("the Misses tab lists urls with counts and copies them all", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  const state = feedReducer(emptyFeed(), {
    type: "event",
    event: { type: "misses", ts: 1, misses: [{ key: "GET https://x.invalid/a", count: 3 }, { key: "GET https://x.invalid/b", count: 1 }] },
  });
  const { onCopied } = setup({ state });
  expect(screen.getByRole("tab", { name: /Misses/ })).toHaveTextContent("2");
  await userEvent.click(screen.getByRole("tab", { name: /Misses/ }));
  const rows = screen.getAllByRole("listitem");
  expect(rows[0]).toHaveTextContent("GET https://x.invalid/a");
  expect(rows[0]).toHaveTextContent("3");
  await userEvent.click(screen.getByRole("button", { name: "Copy all" }));
  expect(writeText).toHaveBeenCalledWith("GET https://x.invalid/a\nGET https://x.invalid/b");
  expect(onCopied).toHaveBeenCalledWith(2);
});

test("the Misses tab is reassuring when empty", async () => {
  setup();
  await userEvent.click(screen.getByRole("tab", { name: /Misses/ }));
  expect(screen.getByText(/everything so far came from the snapshot/i)).toBeInTheDocument();
});

test("a reconnecting pill appears while the socket is down", () => {
  setup({ status: "reconnecting" });
  expect(screen.getByRole("status")).toHaveTextContent("Reconnecting…");
});
```

`frontend/src/components/Main.events.test.tsx`:
```tsx
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api";
import type { Snapshot } from "../types";
import { FakeWebSocket } from "../test-utils";
import { Main } from "./Main";

const snap = (id: string, name: string): Snapshot => ({
  id, name, created: "2026-10-15T10:00:00Z", files: [{ name: "a.xml", size: 10 }],
  stats: { items: 5, origins: 1, skipped: 0, malformed: [] }, damaged: false,
});
const request = (url: string, tier = "EXACT") => ({
  type: "request", tier, method: "GET", url, status: 200, item: null, ts: 1,
});

beforeEach(() => {
  vi.spyOn(api, "snapshots").mockResolvedValue([snap("a", "Treasury"), snap("b", "Acme")]);
  vi.spyOn(api, "state").mockResolvedValue({ vault: "unlocked", replay: null });
});
afterEach(() => vi.restoreAllMocks());

async function mounted(onLocked = vi.fn()) {
  render(<Main onLocked={onLocked} />);
  await screen.findByRole("heading", { name: "Acme" });
  const socket = FakeWebSocket.instances[0];
  act(() => socket.open());
  return { socket, onLocked };
}

test("connects to the events socket and shows requests as they arrive", async () => {
  const { socket } = await mounted();
  expect(socket.url).toMatch(/\/api\/events$/);
  act(() => socket.emit(request("https://shop.invalid/one")));
  act(() => socket.emit(request("https://shop.invalid/two")));
  const feed = screen.getByLabelText("Live feed");
  const rows = within(feed).getAllByRole("listitem");
  expect(rows[0]).toHaveTextContent("https://shop.invalid/two");
  expect(rows[1]).toHaveTextContent("https://shop.invalid/one");
});

test("a replay event marks the snapshot live and clears the old feed", async () => {
  const { socket } = await mounted();
  act(() => socket.emit(request("https://shop.invalid/old")));
  act(() => socket.emit({ type: "replay", running: true, snapshot_id: "b", port: 8081, ts: 2 }));
  expect(await screen.findByText("Replaying on 127.0.0.1:8081")).toBeInTheDocument();
  expect(screen.getAllByRole("img", { name: "Replaying" }).length).toBeGreaterThan(0);
  expect(within(screen.getByLabelText("Live feed")).queryByText(/shop.invalid\/old/)).toBeNull();
  act(() => socket.emit({ type: "replay", running: false, snapshot_id: "b", port: null, ts: 3 }));
  expect(await screen.findByRole("button", { name: "Start replay" })).toBeInTheDocument();
});

test("server toasts are shown", async () => {
  const { socket } = await mounted();
  act(() => socket.emit({ type: "toast", level: "error", message: "address already in use (choose another port)", ts: 1 }));
  expect(await screen.findByRole("alert")).toHaveTextContent("address already in use");
});

test("misses events fill the Misses tab", async () => {
  const { socket } = await mounted();
  act(() => socket.emit({ type: "misses", misses: [{ key: "GET https://x.invalid/z", count: 2 }], ts: 1 }));
  await userEvent.click(screen.getByRole("tab", { name: /Misses/ }));
  expect(screen.getByText("GET https://x.invalid/z")).toBeInTheDocument();
});

test("a dropped socket re-checks the library: a locked one returns to the unlock screen", async () => {
  const { socket, onLocked } = await mounted();
  vi.mocked(api.state).mockResolvedValue({ vault: "locked", replay: null });
  act(() => socket.drop());
  await waitFor(() => expect(onLocked).toHaveBeenCalled());
});

test("a dropped socket on an unlocked library re-syncs the replay state", async () => {
  const { socket, onLocked } = await mounted();
  vi.mocked(api.state).mockResolvedValue({
    vault: "unlocked",
    replay: { running: true, port: 9001, snapshot_id: "b" },
  });
  act(() => socket.drop());
  expect(await screen.findByText("Replaying on 127.0.0.1:9001")).toBeInTheDocument();
  expect(onLocked).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd frontend && npx vitest run src/components/Feed.test.tsx src/components/Main.events.test.tsx`
Expected: FAIL (cannot resolve `./Feed`; `Main` has no feed yet).

- [ ] **Step 3: Implement**

`frontend/src/components/Feed.css`:
```css
.feed .col-head { gap: 12px; }
.tabs { display: flex; gap: 4px; }
.tab { background: none; border: 0; padding: 6px 10px; border-radius: 8px; color: var(--muted); font-weight: 500; }
.tab:hover { color: var(--text); }
.tab[aria-selected="true"] { color: var(--text); background: var(--raised); }
.tab-count { margin-left: 6px; color: var(--miss); font-size: 11px; }
.pill {
  font-size: 11px; padding: 3px 9px; border-radius: 999px;
  background: color-mix(in srgb, var(--fallback) 16%, transparent); color: var(--fallback);
}

.filters { display: flex; flex-wrap: wrap; gap: 6px; padding: 12px 16px; border-bottom: 1px solid var(--line); }
.filter {
  background: transparent; border: 1px solid var(--line); border-radius: 999px; padding: 3px 10px;
  font-family: var(--font-mono); font-size: 11px; color: var(--muted);
}
.filter:hover { color: var(--text); }
.filter[aria-pressed="true"] { color: var(--text); border-color: var(--accent); background: var(--raised); }

.rows { list-style: none; margin: 0; padding: 0; overflow-y: auto; flex: 1; min-height: 0; }
.feed-row {
  display: grid; grid-template-columns: auto auto 1fr auto; align-items: center; gap: 4px 8px;
  padding: 9px 16px; border-bottom: 1px solid var(--line);
}
.row-method { font-weight: 600; font-size: 11px; }
.row-status { color: var(--muted); font-size: 11px; text-align: right; }
.row-item { color: var(--muted); font-size: 10.5px; }
.row-url { grid-column: 1 / -1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11.5px; }
.row-origin { color: var(--muted); }

.badge { font-family: var(--font-mono); font-size: 10px; font-weight: 600; letter-spacing: 0.04em; padding: 2px 6px; border-radius: var(--radius-badge); }
.badge[data-tier="EXACT"] { color: var(--exact); background: color-mix(in srgb, var(--exact) 14%, var(--panel)); }
.badge[data-tier="FALLBACK"] { color: var(--fallback); background: color-mix(in srgb, var(--fallback) 14%, var(--panel)); }
.badge[data-tier="HEAD"] { color: var(--head); background: color-mix(in srgb, var(--head) 14%, var(--panel)); }
.badge[data-tier="MISS"] { color: var(--miss); background: color-mix(in srgb, var(--miss) 14%, var(--panel)); }
.badge[data-tier="BLOCKED"] { color: var(--blocked); background: color-mix(in srgb, var(--blocked) 18%, var(--panel)); }

.feed-empty { padding: 24px 16px; color: var(--muted); }
.misses-head { display: flex; justify-content: flex-end; padding: 10px 16px; border-bottom: 1px solid var(--line); }
.miss-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; padding: 9px 16px; border-bottom: 1px solid var(--line); }
.miss-key { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11.5px; }
.miss-count { color: var(--miss); font-size: 11.5px; }
```

`frontend/src/components/Feed.tsx`:
```tsx
import { memo, useState } from "react";
import { motion } from "motion/react";
import { visibleRows, type FeedRow, type FeedState, type TierFilter } from "../feed";
import { splitUrl } from "../format";
import { springs } from "../motion";
import type { ConnectionStatus } from "../useEvents";
import "./Feed.css";

const FILTERS: TierFilter[] = ["ALL", "EXACT", "FALLBACK", "HEAD", "MISS", "BLOCKED"];

interface Props {
  state: FeedState;
  status: ConnectionStatus;
  running: boolean;
  onCopied?: (count: number) => void;
}

const FeedRowView = memo(function FeedRowView({ row }: { row: FeedRow }) {
  const { origin, rest } = splitUrl(row.url);
  return (
    <motion.li
      className="feed-row"
      initial={{ opacity: 0, x: 12 }}
      animate={{ opacity: 1, x: 0 }}
      transition={springs.feed}
    >
      <span className="badge" data-tier={row.tier}>
        {row.tier}
      </span>
      <span className="row-method mono">{row.method}</span>
      <span className="row-status mono">{row.status ?? ""}</span>
      <span className="row-item mono">{row.item ?? ""}</span>
      <span className="row-url mono" title={row.url}>
        <span className="row-origin">{origin}</span>
        {rest}
      </span>
    </motion.li>
  );
});

export function Feed({ state, status, running, onCopied }: Props) {
  const [tab, setTab] = useState<"live" | "misses">("live");
  const [filter, setFilter] = useState<TierFilter>("ALL");
  const rows = visibleRows(state.rows, filter);

  async function copyAll() {
    try {
      await navigator.clipboard.writeText(state.misses.map((m) => m.key).join("\n"));
      onCopied?.(state.misses.length);
    } catch {
      // clipboard unavailable or denied: nothing to report
    }
  }

  return (
    <aside className="col feed" aria-label="Live feed">
      <header className="col-head">
        <div className="tabs" role="tablist">
          <button role="tab" className="tab" aria-selected={tab === "live"} onClick={() => setTab("live")}>
            Live
          </button>
          <button role="tab" className="tab" aria-selected={tab === "misses"} onClick={() => setTab("misses")}>
            Misses
            {state.misses.length > 0 && <span className="tab-count mono">{state.misses.length}</span>}
          </button>
        </div>
        {status === "reconnecting" && (
          <span className="pill" role="status">
            Reconnecting…
          </span>
        )}
      </header>

      {tab === "live" ? (
        <>
          <div className="filters">
            {FILTERS.map((name) => (
              <button
                key={name}
                className="filter"
                aria-pressed={filter === name}
                onClick={() => setFilter(name)}
              >
                {name} {state.counts[name]}
              </button>
            ))}
          </div>
          {rows.length === 0 ? (
            <p className="feed-empty">
              {state.counts.ALL > 0
                ? "No requests match this filter."
                : running
                  ? "Waiting for requests… browse the site through the proxy."
                  : "Start a replay to see requests here."}
            </p>
          ) : (
            <ul className="rows" aria-label="Requests">
              {rows.map((row) => (
                <FeedRowView key={row.id} row={row} />
              ))}
            </ul>
          )}
        </>
      ) : state.misses.length === 0 ? (
        <p className="feed-empty">No misses yet — everything so far came from the snapshot.</p>
      ) : (
        <>
          <div className="misses-head">
            <button className="ghost small" onClick={copyAll}>
              Copy all
            </button>
          </div>
          <ul className="rows" aria-label="Missed URLs">
            {state.misses.map((miss) => (
              <li key={miss.key} className="miss-row">
                <span className="miss-key mono" title={miss.key}>
                  {miss.key}
                </span>
                <span className="miss-count mono">{miss.count}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </aside>
  );
}
```

`frontend/src/components/Main.tsx` (replaces the Task 9 version):
```tsx
import { useCallback, useEffect, useReducer, useState } from "react";
import { motion } from "motion/react";
import { api } from "../api";
import { useWindowDrop } from "../dnd";
import { emptyFeed, feedReducer } from "../feed";
import { springs } from "../motion";
import type { EventMsg, ReplayState, Snapshot, View } from "../types";
import { useEvents } from "../useEvents";
import { useToasts } from "../useToasts";
import { useUploads } from "../useUploads";
import { DragOverlay } from "./DragOverlay";
import { Feed } from "./Feed";
import { Library } from "./Library";
import { NewSnapshot } from "./NewSnapshot";
import { SnapshotView } from "./SnapshotView";
import { Toasts } from "./Toasts";
import "./Main.css";

const messageOf = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export function Main({ onLocked }: { onLocked: () => void }) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [view, setView] = useState<View>({ kind: "new" });
  const [replay, setReplay] = useState<ReplayState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [feed, dispatchFeed] = useReducer(feedReducer, undefined, emptyFeed);
  const { toasts, push, dismiss } = useToasts();
  const uploads = useUploads();
  const dragging = useWindowDrop((files) => {
    setView({ kind: "new" });
    uploads.add(files);
  });

  const onEvent = useCallback(
    (event: EventMsg) => {
      if (event.type === "replay") {
        setReplay(event.running ? { running: true, port: event.port, snapshot_id: event.snapshot_id } : null);
        if (event.running) dispatchFeed({ type: "clear" });
      } else if (event.type === "toast") {
        push(event.level, event.message);
      } else {
        dispatchFeed({ type: "event", event });
      }
    },
    [push],
  );

  const onDisconnect = useCallback(() => {
    // A dropped socket may mean the library was locked elsewhere, or that events were missed.
    api
      .state()
      .then((state) => {
        if (state.vault !== "unlocked") onLocked();
        else setReplay(state.replay);
      })
      .catch(() => {});
  }, [onLocked]);

  const status = useEvents(true, { onEvent, onDisconnect });

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.snapshots(), api.state()])
      .then(([list, state]) => {
        if (cancelled) return;
        setSnapshots(list);
        setReplay(state.replay);
        const open = state.replay?.snapshot_id ?? list.at(-1)?.id;
        if (open) setView({ kind: "snapshot", id: open });
      })
      .catch((e: Error) => {
        if (!cancelled) setLoadError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rename = useCallback(async (id: string, name: string) => {
    const updated = await api.rename(id, name);
    setSnapshots((all) => all.map((s) => (s.id === id ? updated : s)));
  }, []);

  const remove = useCallback(async (id: string) => {
    await api.remove(id);
    setSnapshots((all) => all.filter((s) => s.id !== id));
    setView((v) => (v.kind === "snapshot" && v.id === id ? { kind: "new" } : v));
    setReplay((r) => (r?.snapshot_id === id ? null : r));
  }, []);

  const created = useCallback((snapshot: Snapshot) => {
    setSnapshots((all) => [...all, snapshot]);
    setView({ kind: "snapshot", id: snapshot.id });
  }, []);

  const updated = useCallback((snapshot: Snapshot) => {
    setSnapshots((all) => all.map((s) => (s.id === snapshot.id ? snapshot : s)));
  }, []);

  const start = useCallback(
    async (id: string, port: number) => {
      try {
        const result = await api.startReplay(id, port);
        setReplay({ running: true, port: result.port, snapshot_id: id });
      } catch (e) {
        push("error", messageOf(e));
      }
    },
    [push],
  );

  const stop = useCallback(async () => {
    try {
      await api.stopReplay();
      setReplay(null);
    } catch (e) {
      push("error", messageOf(e));
    }
  }, [push]);

  const openBrowser = useCallback(async () => {
    try {
      await api.openBrowser();
      push("info", "Opened Firefox with the replay proxy");
    } catch (e) {
      push("error", messageOf(e));
    }
  }, [push]);

  const lock = useCallback(async () => {
    await api.lock().catch(() => {});
    onLocked();
  }, [onLocked]);

  const selected = view.kind === "snapshot" ? snapshots.find((s) => s.id === view.id) : undefined;

  return (
    <div className="main-grid">
      <Library
        snapshots={snapshots}
        view={view}
        replayingId={replay?.snapshot_id ?? null}
        onSelect={setView}
        onRename={rename}
        onDelete={remove}
        onLock={lock}
      />
      <section className="col stage" aria-label="Stage">
        {loadError && (
          <p className="field-error" role="alert">
            Couldn't load the library: {loadError}
          </p>
        )}
        <motion.div
          key={view.kind === "snapshot" ? view.id : "new"}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={springs.screen}
        >
          {view.kind === "new" && <NewSnapshot uploads={uploads} onCreated={created} />}
          {selected && (
            <SnapshotView
              snapshot={selected}
              replay={replay}
              onStart={(port) => start(selected.id, port)}
              onStop={stop}
              onOpenBrowser={openBrowser}
              onUpdated={updated}
            />
          )}
        </motion.div>
      </section>
      <Feed
        state={feed}
        status={status}
        running={!!replay?.running}
        onCopied={(count) => push("info", `Copied ${count} missed URL${count === 1 ? "" : "s"}`)}
      />
      <DragOverlay visible={dragging} />
      <Toasts toasts={toasts} onDismiss={dismiss} />
    </div>
  );
}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS, `tsc` clean. (The earlier `Main*.test.tsx` files keep passing: `test-setup.ts` now supplies the fake WebSocket they need.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: live feed, misses tab and event wiring"
```

---

### Task 11: Build, end-to-end test in headless Firefox, visual review, docs

**Files:**
- Create: `tests/test_ui_e2e.py`
- Modify: `README.md`, and any `frontend/src/**/*.css` the visual review shows needs adjusting
- Regenerate and commit: `src/burpweb/static/`

**Interfaces:**
- Consumes: the built page served by `burpweb ui`, headless Firefox via WebDriver BiDi (driven with Tornado's WebSocket client, so no new dependency), `curl`
- Produces: a skipped-when-unavailable test that exercises the whole product through the real UI

- [ ] **Step 1: Build the app**

Run: `cd frontend && npm run build`
Expected: `tsc` is clean and Vite writes `index.html` and `assets/` into `src/burpweb/static/` (roughly 0.5 MB; only latin font files).

- [ ] **Step 2: Write the end-to-end test**

`tests/test_ui_e2e.py`:
```python
"""Drive the real control page in headless Firefox (WebDriver BiDi).

Create the library, drop an export onto the page, create a snapshot, start a replay, make a
request through the proxy, see it in the live feed, then lock and confirm the proxy is closed.

Skipped when Firefox or curl is missing or the frontend has not been built.
Set BURPWEB_E2E_SHOTS=<dir> to save a screenshot after each step (used for the visual review).
"""

import asyncio
import base64
import json
import os
import select
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import tornado.websocket

from burpfixtures import make_item, make_xml

INDEX = Path(__file__).resolve().parents[1] / "src" / "burpweb" / "static" / "index.html"
pytestmark = pytest.mark.skipif(
    shutil.which("firefox") is None or shutil.which("curl") is None or not INDEX.exists(),
    reason="needs firefox, curl and a built frontend (cd frontend && npm run build)",
)

PREFS = """
user_pref("app.update.auto", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("network.captive-portal-service.enabled", false);
user_pref("browser.safebrowsing.malware.enabled", false);
"""
REQUEST = b"GET /p HTTP/1.1\r\nHost: shop.invalid\r\n\r\n"
RESPONSE = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nhi"
PASSPHRASE = "e2e-test-passphrase"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def printed_url(proc: subprocess.Popen, timeout: float = 30) -> str:
    ready, _, _ = select.select([proc.stdout], [], [], timeout)
    if not ready:
        raise RuntimeError("burpweb ui did not print its URL")
    line = proc.stdout.readline()
    assert "control page:" in line, line
    return line.split("control page:")[1].strip()


class Bidi:
    def __init__(self, ws):
        self.ws = ws
        self.counter = 0

    @classmethod
    async def connect(cls, port: int) -> "Bidi":
        for _ in range(150):
            try:
                return cls(await tornado.websocket.websocket_connect(f"ws://127.0.0.1:{port}/session"))
            except Exception:
                await asyncio.sleep(0.2)
        raise RuntimeError("firefox did not start")

    async def call(self, method: str, **params):
        self.counter += 1
        mid = self.counter
        await self.ws.write_message(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            message = json.loads(await self.ws.read_message())
            if message.get("id") == mid:
                if message.get("type") == "error":
                    raise RuntimeError(message)
                return message["result"]

    async def js(self, ctx: str, expression: str):
        result = await self.call(
            "script.evaluate", expression=expression, target={"context": ctx}, awaitPromise=True
        )
        if result["type"] == "exception":
            raise RuntimeError(result["exceptionDetails"]["text"])
        return result["result"].get("value")

    async def wait_for(self, ctx: str, expression: str, timeout: float = 20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await self.js(ctx, f"Boolean({expression})"):
                return
            await asyncio.sleep(0.15)
        raise AssertionError(f"timed out waiting for: {expression}")


def click_button(label: str) -> str:
    """True (after clicking) once an enabled button with this exact text exists."""
    return (
        "(() => { const b = [...document.querySelectorAll('button')]"
        f".find(b => b.textContent.trim() === {json.dumps(label)});"
        " if (!b || b.disabled) return false; b.click(); return true; })()"
    )


def fill(selector: str, value: str) -> str:
    return (
        f"(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return false;"
        " Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set"
        f".call(el, {json.dumps(value)});"
        " el.dispatchEvent(new Event('input', {bubbles: true})); return true; })()"
    )


def drop_file(zone_selector: str, name: str, text: str) -> str:
    return (
        "(() => {"
        f" const zone = document.querySelector({json.dumps(zone_selector)}); if (!zone) return false;"
        f" const dt = new DataTransfer(); dt.items.add(new File([{json.dumps(text)}], {json.dumps(name)}));"
        " zone.dispatchEvent(new DragEvent('dragenter', {bubbles: true, cancelable: true, dataTransfer: dt}));"
        " zone.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: dt}));"
        " return true; })()"
    )


async def test_full_flow_through_the_real_page(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home)}
    profile = tmp_path / "firefox"
    profile.mkdir()
    (profile / "user.js").write_text(PREFS)
    shots = os.environ.get("BURPWEB_E2E_SHOTS")
    export = make_xml([make_item(host="shop.invalid", request=REQUEST, response=RESPONSE)])

    server = subprocess.Popen(
        [sys.executable, "-m", "burpweb", "ui", "--no-open", "--port", str(free_port())],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    bidi_port = free_port()
    firefox = subprocess.Popen(
        ["firefox", "--headless", "--remote-debugging-port", str(bidi_port), "-profile", str(profile),
         "-no-remote", "--window-size=1440,900"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        url = printed_url(server)
        bidi = await Bidi.connect(bidi_port)
        await bidi.call("session.new", capabilities={})
        ctx = (await bidi.call("browsingContext.create", type="tab"))["context"]

        async def shot(name: str):
            if shots:
                await asyncio.sleep(0.8)  # let the entry animations settle
                Path(shots).mkdir(parents=True, exist_ok=True)
                png = (await bidi.call("browsingContext.captureScreenshot", context=ctx))["data"]
                (Path(shots) / f"{name}.png").write_bytes(base64.b64decode(png))

        async def until(expression: str):
            await bidi.wait_for(ctx, expression)

        await bidi.call("browsingContext.navigate", context=ctx, url=url, wait="complete")

        # 1. a new library: create the passphrase
        await until("document.querySelector('input[type=password]')")
        await shot("1-create-library")
        await until(fill("label:nth-of-type(1) input", PASSPHRASE))
        await until(fill("label:nth-of-type(2) input", PASSPHRASE))
        await until(click_button("Create library"))
        await until("document.querySelector('[aria-label=\"Live feed\"]')")
        await shot("2-new-snapshot")

        # 2. drop an export on the page
        await until(drop_file("[role=button][aria-label^='Drop Burp XML']", "history.xml", export))
        await until("document.querySelector('.chip[data-status=\"done\"]')")
        await shot("3-uploaded")
        await until(click_button("Create snapshot"))
        await until("[...document.querySelectorAll('.card-name')].some(e => e.textContent.includes('history'))")
        await until("document.querySelector('.replay-panel')")
        await shot("4-snapshot")

        # 3. replay it and request the page through the proxy
        replay_port = free_port()
        await until(fill("input[aria-label='Replay port']", str(replay_port)))
        await until(click_button("Start replay"))
        await until("document.body.textContent.includes('Replaying on 127.0.0.1:')")
        ca = home / ".mitmproxy" / "mitmproxy-ca-cert.pem"
        out = await asyncio.to_thread(
            subprocess.run,
            ["curl", "-s", "-x", f"http://127.0.0.1:{replay_port}", "--cacert", str(ca), "https://shop.invalid/p"],
            capture_output=True, timeout=30,
        )
        assert out.stdout == b"hi"
        await until("[...document.querySelectorAll('.feed-row')].some(r => r.textContent.includes('https://shop.invalid/p'))")
        await shot("5-replaying")

        # 4. design and privacy invariants, checked in the real browser
        assert not await bidi.js(
            ctx,
            "[...document.querySelectorAll('*')].some(e => getComputedStyle(e).backgroundImage.includes('gradient'))",
        ), "no element may use a gradient"
        assert await bidi.js(
            ctx,
            "document.fonts.ready.then(() => document.fonts.check('13px \"Schibsted Grotesk\"')"
            " && document.fonts.check('13px \"JetBrains Mono\"'))",
        ), "the bundled fonts must be loaded"
        assert await bidi.js(
            ctx,
            "performance.getEntriesByType('resource').every(r => new URL(r.name).origin === location.origin)",
        ), "the page must only load resources from its own origin"

        # 5. lock: back to the unlock screen, and the replay proxy is gone
        await until(click_button("Lock"))
        await until("document.querySelector('input[type=password]')")
        await shot("6-locked")
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", replay_port), timeout=2).close()
    finally:
        firefox.terminate()
        server.terminate()
        for proc in (firefox, server):
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
```

- [ ] **Step 3: Run it**

Run: `uv run pytest tests/test_ui_e2e.py -q -W ignore`
Expected: PASS (about 20–40 s). If a step times out, rerun with `BURPWEB_E2E_SHOTS=/tmp/burpweb-shots` and look at the last screenshot to see where the page was; fix the page (not the test) unless the selector itself is wrong.

- [ ] **Step 4: Visual review**

Run: `BURPWEB_E2E_SHOTS=/tmp/burpweb-shots uv run pytest tests/test_ui_e2e.py -q -W ignore`, then open each PNG in `/tmp/burpweb-shots/` and check it against this list. Fix any miss in the component's CSS (not by adding gradients or new colours), rebuild with `cd frontend && npm run build`, and rerun until every line holds:

1. `1-create-library`: the card is centred; brand mark, title, two labelled fields, strength bar, the warning with its amber left edge, and a violet "Create library" button that reads as disabled until the form is valid. No gradient or glow anywhere.
2. `2-new-snapshot`: three columns (library 280px, stage, feed 360px) separated by 1px lines; the library lists no snapshots and says so; the dashed drop zone is clearly the focal point; the feed says "Start a replay to see requests here."
3. `3-uploaded`: the drop zone has shrunk to its compact form; one chip shows its order number, name, size and a full green progress bar with a check; the name field is prefilled "history".
4. `4-snapshot`: the selected card has the violet left edge and Rename/Delete underneath; the stage shows the title, the replay panel, four stat tiles, the origins table and the file list; numbers use the mono face and line up.
5. `5-replaying`: the panel border is green with a pulsing dot and "Replaying on 127.0.0.1:<port>"; the library card shows the dot; the feed has an EXACT badge row with the URL on one dimmed-origin line.
6. `6-locked`: back on the unlock card; nothing from the library is visible.

Also check by eye, in each shot: text is never clipped or overlapping, no horizontal scrollbar, focus rings are visible when tabbing, and the type hierarchy is clear (28px title, 13px body, mono for data).

- [ ] **Step 5: Update the README**

In `README.md`, replace the "## 2. Serve it" heading and body with:

````markdown
## 2. Use it

### The control page (recommended)

```bash
uv run burpweb            # same as `burpweb ui`; prints a URL and opens your browser
```

On first run you choose a passphrase. Snapshots are stored encrypted in
`~/.local/share/burpweb/library/` and can only be opened with it. **If you forget the passphrase the
snapshots can't be recovered**; your original XML exports are unaffected.

- Drop one or more Burp XML exports anywhere on the page to create a named snapshot (a later
  frontend capture can be added to an existing snapshot).
- **Start replay** serves it on `127.0.0.1:8081` (changeable); **Open Firefox** launches a separate
  profile already set up for it.
- The live feed shows each request as EXACT, FALLBACK, HEAD, MISS or BLOCKED; the Misses tab lists
  what the capture lacks.
- **Lock** stops the replay and forgets the passphrase.

The control page listens on `127.0.0.1:8765` (not Burp's 8080) and only answers requests that carry
the random token in the printed URL.

### The command line

```bash
uv run burpweb list history.xml                    # what's in the capture
uv run burpweb serve history.xml frontend.xml --browser
```

`--browser` uses its own Firefox profile (`~/.local/share/burpweb/firefox-profile`) and trusts the
mitmproxy CA only there. Your normal browser and system trust store are not touched. Without
`--browser`, point any browser's HTTP and HTTPS proxy at `127.0.0.1:8081` and trust
`~/.mitmproxy/mitmproxy-ca-cert.pem`. Several exports are treated as one history in the order given;
for an identical request the later file wins.

## Developing the frontend

The page is a React app in `frontend/`; its build is committed to `src/burpweb/static/`, so running
burpweb never needs Node.

```bash
cd frontend
npm install
npm test            # Vitest
npm run dev         # Vite dev server; proxies /api to a running `burpweb ui --port 8765`
npm run build       # typecheck, then write src/burpweb/static/ (commit the result)
```
````

(Keep the existing "How requests are matched" section and everything after it unchanged.)

- [ ] **Step 6: Run everything**

Run: `uv run pytest -q -W ignore && cd frontend && npm test && npm run build`
Expected: the Python suite (including `test_ui_e2e.py`) and the frontend suite pass; the build succeeds. If the build changed `src/burpweb/static/`, that is expected.

- [ ] **Step 7: Commit**

```bash
git add README.md tests/test_ui_e2e.py frontend src/burpweb/static
git commit -m "feat: built frontend, end-to-end test and docs"
```

---

## Self-review notes

- **Spec coverage:** unlock/create screen (Task 6); three-column layout, library with rename/delete/lock/new (Task 7); drop zone, upload chips with progress, window-wide overlay, name field, create with validation errors (Task 8); snapshot stats, malformed list, origins table, files, add-files, port, Start/Stop/Open Firefox (Tasks 1, 9); live feed with filters, Misses tab with copy, reconnect pill, toasts (Tasks 9, 10); motion specs and reduced motion (Tasks 2, 6–10, `MotionConfig reducedMotion="user"` plus the CSS media query); no gradients, fonts, CDN-free (Task 11 asserts all three in a real browser).
- **Spec deviations, decided deliberately:** after a rejected create/add the server discards every staged upload, so the chips are cleared and the user re-adds the files, instead of leaving removable chips as the spec's wording suggests; a window-level drop always targets a *new* snapshot (adding to an existing one needs its own "add files" zone), so a stray drop can't silently modify a snapshot; screen transitions animate on entry only (no exit animation) to keep the app responsive and the tests deterministic.
- **Backend contract used:** `GET /api/state`, `POST /api/vault/{create,unlock,lock}`, `GET|POST /api/snapshots`, `PATCH|DELETE /api/snapshots/<id>`, `POST /api/snapshots/<id>/files`, `PUT /api/uploads/<id>?name=`, `POST|DELETE /api/replay`, `POST /api/browser`, `WS /api/events` — exactly as built and reviewed in the backend plan; the one backend change is `stats.by_origin` (Task 1).
- **Known limits (not in scope):** no mobile layout; the stage does not animate out; the feed shows the latest 500 requests only; snapshot order in the library is creation order.
