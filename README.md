# burpweb

Browse a website you tested in Burp Suite **offline**, at its real URLs, from your Burp HTTP history.
burpweb runs a local replay proxy (built on mitmproxy) that answers every request from the capture.
It never contacts the real target.

## Install

```bash
uv sync            # inside this repo
uv run burpweb --help
```

## 1. Export from Burp

Proxy → HTTP history → select all (Ctrl-A) → right-click → **Save items**.
Keep **"Base64-encode requests and responses"** ticked. Raw exports lose every carriage-return
character (XML parsing turns CRLF into LF) and break on binary bodies, so replays from them are less exact.
Using a `.burp` project? Open it in Burp first, then export the same way.

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

## How requests are matched

1. **EXACT**: same scheme, host, port, method, path, query (any order) and body (form and JSON compared normalized). The most recent capture wins.
2. **FALLBACK**: same path, ignoring query and body. This uses the most recent capture with status < 400, else the most recent with any status.
3. **HEAD**: answered from the GET capture, with no body.
4. **MISS**: a 404 page saying "Not in snapshot". Misses are summarized when you press Ctrl-C.

Each request is logged as `EXACT`, `FALLBACK`, `HEAD` or `MISS`.
Not supported: WebSockets (not in Burp's XML export) and native `.burp` files.
