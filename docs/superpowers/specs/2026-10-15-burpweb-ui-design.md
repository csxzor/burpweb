# burpweb UI — Design Spec

Date: 2026-10-15
Status: Approved in conversation, pending written-spec review
Builds on: `docs/superpowers/specs/2026-10-15-burpweb-design.md` (replay engine, matcher, CLI)

## Purpose

Give the user a local web control page so they don't have to drive burpweb from the
CLI. On that page they can:

- drop or upload Burp XML exports;
- keep them as named, encrypted snapshots in a library;
- start and stop the replay proxy;
- open the preconfigured Firefox;
- watch the live request feed and the list of misses.

The existing `serve` and `list` CLI commands are unchanged.

## Usage

```
burpweb            # same as `burpweb ui`
burpweb ui [--port 8080] [--no-open]
```

`burpweb ui` starts the control server on `127.0.0.1`, prints the URL and opens
the default browser at `http://127.0.0.1:<port>/?token=<random>`. If the port
is busy, it tries the next ports, up to `<port>+20`, and prints the URL it
actually bound. The replay proxy runs in the same process and event loop, on
port 8081 by default, which can be changed in the UI.

## Architecture

The UI uses one asyncio event loop shared by Tornado (the control server) and
mitmproxy (the replay proxy).

| Module | Responsibility | Depends on |
|---|---|---|
| `vault.py` | Key derivation, chunked AES-256-GCM encryption and decryption, and the passphrase check. | `cryptography` |
| `library.py` | The snapshot store: create, list, rename, delete, add files, load records. Atomic writes. | `vault`, `burp_xml` |
| `session.py` | Runs one replay at a time: `start(records, port)`, `stop()`, `state`. Fans `Replay` events out to subscribers. | mitmproxy, `addon`, `matcher`, `browser` |
| `webapp.py` | Tornado application: auth middleware, JSON API, upload streaming, the WebSocket feed, and static file serving. | tornado, `library`, `session` |
| `cli.py` | Adds the `ui` subcommand, which is the default when no subcommand is given. | `webapp` |
| `frontend/` (source) → `src/burpweb/static/` (build output, committed) | React SPA. | Node only for development |

`Replay` gains an optional `on_event(dict)` callback. It is called for every
log line, using the same tiers as the terminal (`EXACT`, `FALLBACK`, `HEAD`,
`MISS`, `BLOCKED`), and also when the replay finishes, with the miss summary.
Terminal output is unchanged.

## Library storage

Root: `~/.local/share/burpweb/library/`. The directory is created with mode
`0700`, and every file is written with mode `0600`.

```
vault.json                 { "version": 1, "kdf": "scrypt", "n": 131072, "r": 8, "p": 1,
                             "salt": b64(16 bytes), "check": b64(encrypted "burpweb-vault-ok") }
<id>/meta.enc              encrypted JSON: { name, created (ISO 8601), files: [{name, size}],
                             stats: {items, origins, skipped, malformed: [[index, reason]]} }
<id>/files/<n>.enc         encrypted export n (0-based, in the order the files were added)
.tmp-<id>/                 in-progress snapshot; renamed to <id>/ when complete
```

- `<id>` is 16 random bytes in hex. File names on disk never reveal snapshot
  names or export file names.
- **Key:** scrypt(passphrase, salt, n=2^17, r=8, p=1) → 32 bytes. The key
  stays in memory only while the library is unlocked and is dropped on Lock or
  exit.
- **Chunked file format:**
  - A header holds the magic `BWV1` and a random 8-byte `file_nonce_prefix`.
  - It is followed by chunks. Each chunk is a 4-byte big-endian ciphertext
    length followed by the AES-256-GCM ciphertext and tag. Plaintext chunks are
    4 MiB.
  - **Nonce:** `file_nonce_prefix` (8 bytes) + `chunk_index` (4 bytes, big-endian).
  - **AAD:** `f"{snapshot_id}/{file_label}/{chunk_index}/{is_final}"`. This
    binds every chunk to its snapshot, its file and its position, and detects a
    reordered or truncated file. The last chunk is always written with
    `is_final=1`, even when it is empty.
- `meta.enc` uses the same format, with `file_label="meta"`.
- `check` in `vault.json` uses the same format, with snapshot id `vault` and
  `file_label="check"`.
- **Atomic writes:** a snapshot is fully written under `.tmp-<id>/`, then
  `os.rename` moves it to `<id>/`. Adding files to an existing snapshot writes
  the new `files/<n>.enc`, then rewrites `meta.enc` atomically via a temporary
  file and rename.
- Leftover `.tmp-*` directories are deleted when the library is unlocked.
- **Loading** decrypts each file chunk by chunk into memory (`BytesIO`) and
  runs the existing `load_many` logic over them in order. Decrypted plaintext
  is never written to disk.

## Control server (`webapp.py`)

### Access control

These rules apply to every request:

- The server binds to `127.0.0.1` only.
- **Host check:** the `Host` header must be `127.0.0.1:<port>` or
  `localhost:<port>`. Anything else gets a 403, which blocks DNS rebinding.
- **Token:** a first `GET /?token=<t>` with the correct token sets the cookie
  `bw_token=<t>` (`HttpOnly; SameSite=Strict; Path=/`) and redirects to `/`.
  Every other request needs that cookie, or it gets a 403. The token is 32
  random bytes, url-safe base64.
- Responses carry no CORS headers. Mutating requests are POST, PUT, PATCH and
  DELETE with JSON or raw bodies; `SameSite=Strict` together with the token
  covers CSRF.

### API

All JSON. Errors are `{ "error": "<message>" }` with a 4xx or 5xx status.

| Method & path | Body | Result |
|---|---|---|
| `GET /api/state` | — | `{ vault: "new"\|"locked"\|"unlocked", replay: {snapshot_id, port, running} \| null }` |
| `POST /api/vault/create` | `{passphrase}` (≥ 10 characters) | 200. Allowed only when `vault == "new"`. |
| `POST /api/vault/unlock` | `{passphrase}` | 200, or 401 `wrong passphrase` |
| `POST /api/vault/lock` | — | 200. Stops any replay and drops the key. |
| `GET /api/snapshots` | — | `[{id, name, created, files:[{name,size}], stats}]` |
| `PUT /api/uploads/<upload_id>?name=<file name>` | raw XML body, streamed | `{upload_id, size}`. The body is encrypted chunk by chunk as it arrives. |
| `POST /api/snapshots` | `{name, uploads:[upload_id…]}` | Validates, then returns the snapshot JSON (as in the list above), or 422 with the loader's error message |
| `POST /api/snapshots/<id>/files` | `{uploads:[upload_id…]}` | Updated snapshot JSON, or 422 |
| `PATCH /api/snapshots/<id>` | `{name}` | Updated snapshot JSON |
| `DELETE /api/snapshots/<id>` | — | 204. Stops the replay if it is using that snapshot. |
| `POST /api/replay` | `{snapshot_id, port?}` | `{snapshot_id, port, running:true}`. If another replay is running, it is stopped first. |
| `DELETE /api/replay` | — | 204 |
| `POST /api/browser` | — | 200, or 409 with the manual-setup instructions if Firefox or certutil is missing |
| `WS /api/events` | — | Server→client JSON messages (see below) |

All `/api/*` routes except `state`, `vault/create` and `vault/unlock` return
423 `library locked` while the vault is locked.

**Uploads:**

- Upload ids are client-generated UUIDv4s. An upload is held in
  `.tmp-upload-<upload_id>/`, encrypted, until a snapshot claims it.
- Unclaimed uploads are deleted on lock or exit.
- The maximum upload is 2 GiB per file, enforced while streaming.

**Validation:** the server decrypts the claimed uploads into memory and runs
`load_many` over them. It returns 422 in these cases:

- `BurpXmlError`, with its message, including the base64 hint;
- zero usable records, with the CLI's "no usable items" message.

On a 422 the uploads are deleted.

### WebSocket messages

```
{ "type": "request", "tier": "EXACT", "method": "GET", "url": "...", "status": 200,
  "item": "trjs #12" | null, "ts": <epoch ms> }
{ "type": "blocked", "address": "10.0.0.5:22", "ts": ... }
{ "type": "replay",  "running": true|false, "snapshot_id": "...", "port": 8081 }
{ "type": "misses",  "misses": [{ "key": "GET https://...", "count": 2 }] }   # on change, max once per 500 ms
{ "type": "toast",   "level": "error"|"info", "message": "..." }
```

## Session (`session.py`)

- **`start(records, port, confdir)`:** builds a `Matcher`, then creates the
  `DumpMaster` with the same options as `cli.run_proxy`: `lazy`,
  `upstream_cert=False`, `http3=False`, `rawtcp=False`, plus the
  `server_connect` block.
  - It runs `master.run()` as a task on the shared loop.
  - **Startup failure** (for example, the port is busy) is caught: mitmproxy's
    `SystemExit` or its errors become a `toast` message plus
    `replay running:false`. The server keeps running.
- **`stop()`:** calls `master.shutdown()` and awaits the task.
- **`open_browser()`:** uses `FirefoxLauncher` for the current port and confdir,
  with the start URL set to the first record's URL.
- The CA confdir is `~/.mitmproxy`. The Firefox profile is the existing
  `DEFAULT_PROFILE`.

## Frontend

- **Stack:**
  - React 19 + TypeScript.
  - Vite (build).
  - `motion` (Motion for React) for springs, layout and presence animations.
  - Fonts self-hosted via `@fontsource`, so the UI works with no network
    access. Nothing is loaded from a CDN.
- **Build output:** `src/burpweb/static/` is committed, so Python users don't
  need Node. The npm scripts are `dev` (Vite dev server proxying `/api` to the
  Tornado server) and `build`.

### Visual system: dark, flat, no gradients

Colour tokens (CSS variables):

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0b0c0e` | page |
| `--panel` | `#121418` | columns, cards |
| `--raised` | `#191c21` | hover and selected surfaces, inputs |
| `--line` | `#262a31` | 1px borders and dividers |
| `--text` | `#e7e5e1` | primary text |
| `--muted` | `#8b9099` | secondary text |
| `--accent` | `#8b7cf6` | single flat accent: primary button, focus ring, active card edge |
| `--exact` | `#3fcf8e` | EXACT badge |
| `--fallback` | `#e8b44c` | FALLBACK badge |
| `--head` | `#6cb6ff` | HEAD badge |
| `--miss` | `#f2667a` | MISS badge |
| `--blocked` | `#9198a1` | BLOCKED badge |

**Visual rules:**

- No gradients anywhere.
- Depth comes only from surface steps (`--bg` → `--panel` → `--raised`), 1px
  `--line` borders, and a soft shadow on floating elements (toasts, popovers,
  the drag overlay): `0 12px 32px rgba(0,0,0,.45)`.
- Badges are tinted fills: the badge colour at 14% opacity on `--panel`, with
  text in the badge colour.

**Typography:**

- **UI text:** Schibsted Grotesk, at 400 / 500 / 700.
- **Data:** JetBrains Mono at 400 / 600, for URLs, counts, badges and the feed.
- **Sizes:** 13px base; 28px / 700 for the snapshot title on the stage.
- **Tabular figures** for every number.

**Radii:** 10px for cards and inputs, 14px for the drop zone, 6px for badges.

### Motion

All motion uses `motion` springs unless stated otherwise.

| Element | Spec |
|---|---|
| Layout reflow (library cards, feed list) | `layout` with spring `stiffness 380, damping 32` |
| A new snapshot card entering the library | Shared `layoutId` from the stage's summary panel to the card |
| Page and screen transitions (unlock → main, stage views) | Opacity and 8px y; spring `stiffness 260, damping 28`; children stagger 40ms |
| Feed rows | Enter from x=12 with opacity 0; spring `stiffness 420, damping 34`. The list is capped at the latest 500 rows, and removed rows don't animate. |
| Drop zone | Idle: border breathes between 40% and 70% opacity, 2.4s ease-in-out loop. Drag-over: scale 1.015, border at 100% `--accent`, surface → `--raised`, spring `stiffness 500, damping 30`. |
| Full-window drag overlay | Fades in over 120ms when files enter the window |
| Upload chips | Progress bar width animated with `stiffness 200, damping 30`. On completion the chip settles with a check icon. |
| Wrong passphrase | x keyframes `[0, -8, 8, -5, 5, 0]` over 380ms |
| Buttons | Press scale 0.97; hover surface step to `--raised` |

With `prefers-reduced-motion: reduce`, every animation above becomes a
150ms opacity fade, and the drop-zone breathing loop is disabled.

### Screens

1. **Unlock**
   - Centered card.
   - If the vault is `new`: create a passphrase (two fields, at least 10
     characters, with a strength hint), plus the warning "If you forget this
     passphrase, stored snapshots can't be recovered."
   - Otherwise: a single passphrase field.
   - Enter submits the form.
2. **Main**: a three-column grid, 280px | 1fr | 360px.
   - **Library:** the snapshot cards (name, created date, items · origins);
     "New snapshot"; "Lock".
     - A card's menu offers Rename (inline edit) and Delete (confirmation
       dialog that names the snapshot).
     - The card with a running replay shows a live dot.
   - **Stage:** what it shows depends on what is selected.
     - **New:**
       - Drop zone, plus a hidden file input for click-to-browse (`.xml`, or
         any file type, because Burp exports often have no extension).
       - Upload chips with progress.
       - Name field, prefilled from the first file name.
       - A "Create snapshot" button, enabled once every upload has finished.
       - **After a 422:** the error is shown inline and the chips can be
         removed.
     - **Snapshot:**
       - The title, and stats (items, origins, skipped, malformed). Malformed
         items are expandable, with their reasons.
       - An origins table (items, paths, origin, sorted by items).
       - The file list, and a compact "add files" drop zone.
       - Controls: Start replay (primary) and the port field, or, while the
         replay is running, "Replaying on 127.0.0.1:<port>" with Open Firefox
         and Stop.
   - **Feed:** two tabs, Live and Misses.
     - **Live:** filter chips (All, EXACT, FALLBACK, HEAD, MISS, BLOCKED) with
       counts. Rows show badge · method · URL (one line, ellipsized; the full
       URL is in the title tooltip) · status · item.
     - **Misses:** a sorted list with counts and a copy-all button.
3. **Toasts:** bottom-right stack, auto-dismissed after 6 seconds; errors stay
   until dismissed.

## Error handling

| Situation | Behaviour |
|---|---|
| Wrong passphrase | 401 → shake animation plus an inline message |
| Upload fails validation | 422 → inline error on the stage (loader message); uploads deleted |
| `meta.enc` or a file fails authentication | The snapshot is listed as "damaged" (it can't be started, but it can be deleted); the rest of the library works |
| Replay port busy | `toast` with mitmproxy's message and "choose another port"; the replay stays stopped |
| Firefox or certutil missing | 409 → toast containing the manual-setup instructions |
| Control port busy | Tries the next port, up to 20 times, then exits with an error naming the range |
| WebSocket drops | The client reconnects with backoff (0.5s → 5s) and shows a "reconnecting" pill |

## Out of scope

- Multiple replays running at the same time
- Changing the passphrase (delete and recreate the vault instead)
- Remote or LAN access
- Editing or deleting individual requests inside a snapshot
- Viewing request or response bodies in the UI

## Testing

- **`test_vault.py`:**
  - Round-trip for empty, single-chunk and multi-chunk data (the chunk size is
    patched small).
  - A wrong passphrase is rejected.
  - Each of these is detected: a flipped ciphertext bit, swapped chunks, a
    truncated file (final chunk removed), and a chunk moved to another
    file label or snapshot.
- **`test_library.py`:**
  - Create, list, rename, delete, and add files.
  - Records load in file order (the later file wins in the matcher).
  - **No plaintext on disk:** after creating a snapshot from a fixture
    containing a unique marker string and its file name, the test walks the
    library directory and asserts that neither appears in any file or path.
  - `.tmp-*` directories are cleaned up on unlock.
  - A damaged snapshot is reported as damaged, and the others still load.
  - Files are created with mode `0600` and directories with `0700`.
- **`test_session.py`:**
  - Start, stop and switch replays.
  - Events reach subscribers.
  - A busy port produces a toast plus `running:false`.
- **`test_webapp.py`** (Tornado `AsyncHTTPTestCase`):
  - Access control: no token → 403; wrong `Host` → 403; the token handshake
    sets the cookie.
  - The vault create, lock and unlock flow; 423 while locked.
  - Streamed upload → create → snapshot listed.
  - A 422 with the base64 hint for invalid XML.
  - Starting a replay via the API makes a curl request through it get a
    captured response, and a `request` event arrives on the WebSocket.
  - All hosts use `.invalid`.
- **Frontend:**
  - Vitest + Testing Library for the upload chip state machine, the feed
    filter and the snapshot form validation.
  - **End-to-end:** headless Firefox over WebDriver BiDi (the same approach as
    the real-export check) drives unlock → drop a fixture file (via the file
    input) → create → start → open a captured URL through the proxy → assert
    the feed row appears.
- **Manual:** the user's three real exports are imported as one snapshot, the
  dashboard is replayed in Firefox from the UI, and the result is compared with
  the CLI result (617 items, 4 origins).
