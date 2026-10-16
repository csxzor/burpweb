# burpweb

Browse a website you tested in Burp Suite **offline**, at its real URLs, straight from your HTTP history.

burpweb runs a local replay proxy (built on [mitmproxy](https://mitmproxy.org)) that answers every request
from your capture. It **never contacts the real target**: every upstream connection is blocked.

- **Drag-and-drop control page**: drop Burp exports, name a snapshot, press Start.
- **Encrypted at rest**: snapshots are AES-256-GCM encrypted with a passphrase-derived key (scrypt).
- **Live feed**: every request is tagged EXACT, FALLBACK, HEAD, MISS or BLOCKED; a Misses tab lists what the capture lacks.
- **One-click Firefox**: a separate profile that already trusts the replay CA; your normal browser is untouched.
- **CLI too**: `burpweb serve`, `burpweb list`.

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). Firefox is optional (used by *Open Firefox*).

```bash
git clone https://github.com/csxzor/burpweb.git && cd burpweb
uv sync
uv run burpweb          # prints a URL and opens the control page
```

1. **Export from Burp:** Proxy → HTTP history (filter: *Show all*) → select all → right-click → **Save items**.
   Keep **"Base64-encode requests and responses"** ticked. Raw exports lose every CR and break on binary bodies.
   For a `.burp` project, open it in Burp first and export the same way.
2. **Create your library** on first run by choosing a passphrase. **If you forget it, snapshots can't be recovered**
   (your original XML files are unaffected).
3. **Drop one or more exports** anywhere on the page, name the snapshot, **Create snapshot**.
4. **Start replay** (default `127.0.0.1:8081`), then **Open Firefox**. **Lock** stops the replay and forgets the passphrase.

A later capture (for example the frontend assets) can be added to an existing snapshot; for an identical request the later file wins.

## Command line

```bash
uv run burpweb list history.xml                              # what's in a capture
uv run burpweb serve history.xml frontend.xml --browser      # replay several exports as one history
```

Without `--browser`, point any browser's HTTP and HTTPS proxy at `127.0.0.1:8081` and trust
`~/.mitmproxy/mitmproxy-ca-cert.pem`.

## How requests are matched

| Tier | Rule |
|---|---|
| **EXACT** | Same scheme, host, port, method, path, query (any order) and body (form and JSON normalized). Most recent capture wins. |
| **FALLBACK** | Same path, ignoring query and body: the most recent capture with status < 400, else the most recent of any status. |
| **HEAD** | Answered from the GET capture, without a body. |
| **MISS** | A 404 page saying "Not in snapshot". |

304 and 206 responses are used only as a last resort. Not supported: WebSockets (Burp's XML export doesn't include them)
and native `.burp` files.

## Security notes

- Snapshots live in `~/.local/share/burpweb/library/`, files `0600`, encrypted with AES-256-GCM (names included),
  with tamper and truncation detection. The passphrase is never stored by the page or the server.
- The control page listens on `127.0.0.1:8765` only. It needs the random token from the printed URL, checks the `Host`
  header, and refuses cross-origin writes.
- Replays contain whatever was in your capture (session tokens, credentials). Treat exports and snapshots as sensitive,
  and keep them out of version control.

## Development

```bash
uv run pytest -q -W ignore          # Python tests; the end-to-end test needs Firefox and is skipped without it

cd frontend                          # React 19 + TypeScript + Vite; the build is committed to src/burpweb/static/
npm install
npm test                             # Vitest
npm run dev                          # dev server; proxies /api to a running `burpweb ui --port 8765`
npm run build                        # typecheck, then write src/burpweb/static/ (commit the result)
```

Design notes and implementation plans are in [`docs/superpowers/`](docs/superpowers/).

Use burpweb only on captures from systems you are authorized to test.
