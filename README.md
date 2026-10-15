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

## 2. Serve it

```bash
uv run burpweb list history.xml               # what's in the capture
uv run burpweb serve history.xml --browser    # proxy on 127.0.0.1:8081 + preconfigured Firefox
```

Several exports (say, your main history plus a later frontend capture) can be combined:
`uv run burpweb serve history.xml frontend.xml`. They're treated as one history in the order given,
so for an identical request the later file wins.

`--browser` uses its own Firefox profile (`~/.local/share/burpweb/firefox-profile`) and trusts the mitmproxy CA
only there. Your normal browser and system trust store are not touched.
Without `--browser`, point any browser's HTTP and HTTPS proxy at `127.0.0.1:8081` and trust
`~/.mitmproxy/mitmproxy-ca-cert.pem`.

## How requests are matched

1. **EXACT**: same scheme, host, port, method, path, query (any order) and body (form and JSON compared normalized). The most recent capture wins.
2. **FALLBACK**: same path, ignoring query and body. This uses the most recent capture with status < 400, else the most recent with any status.
3. **HEAD**: answered from the GET capture, with no body.
4. **MISS**: a 404 page saying "Not in snapshot". Misses are summarized when you press Ctrl-C.

Each request is logged as `EXACT`, `FALLBACK`, `HEAD` or `MISS`.
Not supported: WebSockets (not in Burp's XML export) and native `.burp` files.
