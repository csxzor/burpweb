# burpweb — Design Spec

Date: 2026-10-15
Status: Approved in conversation, pending written-spec review

## Purpose

Turn a Burp Suite HTTP history export into an offline, browsable snapshot of the
website that was tested. The user browses the real URLs (e.g.
`https://target.com/...`) in a browser, and every response comes from the
capture. The real target is never contacted.

## Input

Burp's XML export, made from **Proxy → HTTP history → select items → right-click
→ Save items**. Both the "base64-encode requests and responses" setting and the
raw (non-base64) setting are supported.

Native `.burp` project files are **out of scope**. Their format is proprietary
and undocumented. To use one, open it in Burp and export the history as above.

## Usage

```
burpweb serve history.xml               # replay proxy on 127.0.0.1:8081
burpweb serve history.xml --port 9000   # custom port
burpweb serve history.xml --browser     # also launch a preconfigured Firefox
burpweb serve history.xml --confdir DIR # mitmproxy CA/config dir (default ~/.mitmproxy)
burpweb list history.xml                # print captured hosts and URL counts
```

The tool is a Python package managed with `uv`, with mitmproxy as a project
dependency. It requires Python >= 3.12.

## Architecture

Data flow: Firefox → `127.0.0.1:<port>` (mitmproxy, HTTPS intercepted with the
mitmproxy CA) → replay addon → matcher → captured response → Firefox.

Package layout (`src/burpweb/`):

| Module        | Responsibility | Depends on |
|---------------|----------------|------------|
| `burp_xml.py` | Stream-parse the Burp XML (`iterparse`) into `Record` objects. Decode base64 and raw items. Skip items with no response and count them. | stdlib only |
| `matcher.py`  | Build an index from records and answer `match(request) -> (Record, tier)`, or a miss. | `burp_xml.Record` |
| `addon.py`    | mitmproxy addon. In the `request` hook it consults the matcher and sets `flow.response` directly, so no request ever goes upstream. Logs each result and prints a miss summary on exit. | mitmproxy, matcher |
| `browser.py`  | Create or reuse a Firefox profile at `~/.local/share/burpweb/firefox-profile`, write its proxy and noise-reduction prefs to `user.js`, import the mitmproxy CA into that profile only with `certutil`, and launch Firefox with `-profile ... -no-remote`. | firefox, certutil |
| `cli.py`      | Argument parsing for the `serve` and `list` subcommands. Loads records, builds the matcher, and runs mitmproxy (`DumpMaster`) in-process with the addon. | all of the above |

### Record

One per Burp `<item>` that has a response:

- `index`: position in the export, used as the recency order (higher means more recent)
- `time`: Burp's timestamp string, used only for display
- `scheme`, `host`, `port`
- `method`, `path`, `query`: the path and query split from the request line
- `request_body`: bytes
- `status`: int
- `response_headers`: list of (name, value) pairs, order preserved
- `response_body`: bytes

Burp's `<host>`, `<port>` and `<protocol>` elements are authoritative for scheme,
host and port. Method, path and query come from the request line. Status,
headers and body come from parsing the raw response bytes.

## Matching rules

Requests are matched in tiers, and the first tier that matches wins:

1. **EXACT.** The key is (scheme, host, port, method, path, normalized query,
   normalized body).
   - Normalized query: the parsed parameters, sorted. Repeated keys are kept.
   - Normalized body: for `application/x-www-form-urlencoded`, the parsed
     parameters, sorted. For JSON, the JSON re-serialized with sorted keys and
     compact separators. If parsing fails, the raw bytes are used. Any other
     content type uses the raw bytes.
   - If several records match, the most recent one wins, whatever its status.
2. **FALLBACK.** The key is (scheme, host, port, method, path). The most recent
   record with status < 400 wins. If there is none, the most recent record with
   any status wins.
3. **HEAD.** A HEAD request with no match in tier 1 or 2 is matched against GET
   using tiers 1 and 2. The response body is sent empty, and the headers are
   kept.
4. **MISS.** The tool returns a 404 with `Content-Type: text/html` and a short
   page saying "not in snapshot" that names the method and URL.

Host comparison is case-insensitive. The path is compared exactly; there is no
trailing-slash or case normalization. Cookies and other request headers are
**not** part of any key.

## Response cleanup

Captured responses are sent as captured except for these changes:

- **De-chunking.** If `Transfer-Encoding: chunked` is present, the body is
  de-chunked and the header is removed. If the body is not validly chunked, it
  is kept as is and the header is still removed.
- **Content-Encoding.** If the header says `gzip`, `deflate` or `br` but the body
  doesn't decode with that codec, the header is dropped. This covers Burp
  saving bodies already decoded. If the codec isn't available, the header is
  kept.
- **Content-Length** is recomputed from the final body.
- **Alt-Svc** is removed, so the browser doesn't attempt HTTP/3 around the proxy.

Everything else is left untouched, including `Set-Cookie`, CSP, CORS headers
and redirects.

## Firefox profile (`--browser`)

`user.js` sets:

- Manual proxy at `127.0.0.1:<port>` for HTTP and SSL, with no bypass list
  (`network.proxy.no_proxies_on` set to empty, and
  `network.proxy.allow_hijacking_localhost` set to true).
- Noise reduction: updates, telemetry and health reports off, Safe Browsing off,
  captive-portal and connectivity checks off, and DNS prefetch and speculative
  connections off.
- HTTP/3 disabled (`network.http.http3.enable` set to false).

The CA comes from `<confdir>/mitmproxy-ca-cert.pem`, which mitmproxy creates
on first start. `browser.py` waits for that file after the proxy starts, then
imports it with `certutil -A -d sql:<profile> -n burpweb-mitmproxy -t "C,," -i
<pem>`. This is idempotent and skipped if the cert is already present. Neither
the system trust store nor the user's normal Firefox profile is touched.

If `firefox` or `certutil` isn't on PATH, `--browser` prints manual setup
instructions and the proxy keeps running.

## Logging and visibility

- One line per request: `EXACT|FALLBACK|HEAD|MISS  METHOD URL  -> status`.
  `FALLBACK` and `HEAD` also print the index of the Burp item used.
- On startup: the number of records loaded, the number skipped, and the number
  of hosts.
- On exit (Ctrl-C): the unique missed URLs with their counts.
- `list` prints each host with its record count and number of unique paths,
  sorted by count.

## Error handling

- File missing, unreadable or not valid XML: the tool exits with a clear message
  and a non-zero code.
- A malformed individual item (bad base64, unparsable request or response line)
  is skipped, counted and reported in the startup summary with its index. It
  never aborts the load.
- Zero usable records: the tool exits with a message suggesting the user check
  the export settings.
- Port in use: mitmproxy's error is shown, with a hint to use `--port`.

## Out of scope

- Native `.burp` project file parsing
- WebSocket replay, since Burp's XML export doesn't include WebSocket history
  (WebSocket requests get MISS)
- Static file mirroring or link rewriting
- Live passthrough to real servers for misses
- Chromium launcher
- Selecting a time window or item range

## Testing

pytest, run with `uv run pytest`.

- **`test_burp_xml.py`**: hand-built fixture XMLs covering base64 items, raw
  items, a missing response, a malformed item, a chunked body, a gzip body,
  non-default ports and HTTP vs HTTPS.
- **`test_matcher.py`**: each tier; the most-recent tie-break; fallback that
  prefers < 400 and then any status; query order insensitivity; normalization of
  form and JSON bodies; invalid JSON falling back to raw bytes; HEAD → GET with
  an empty body; and a miss.
- **`test_cleanup.py`**: de-chunking; dropping a `Content-Encoding` header that
  doesn't match the body; keeping one that does; `Content-Length`
  recomputation; `Alt-Svc` removal.
- **`test_addon.py`**: using `mitmproxy.test.tflow`, a matched flow gets
  `flow.response` set in the `request` hook (so mitmproxy never connects
  upstream), and a missed flow gets the 404 snapshot page.
- **End-to-end smoke test** (`test_e2e.py`): start `burpweb serve` on a free port
  against a fixture with `--confdir` set to a temporary directory, so the
  user's real `~/.mitmproxy` is never touched. Then fetch an HTTPS and an HTTP
  URL through it with `curl -x ... --cacert <tmp>/mitmproxy-ca-cert.pem`. Assert the
  captured bodies come back and an unknown URL returns the snapshot 404. The
  test is skipped if `curl` is unavailable.
- If the user provides a real export, the tool is also run against it manually.
