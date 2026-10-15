"""mitmproxy addon that answers every request from the Burp capture."""

from __future__ import annotations

import collections
import html
import sys
import time
from http.client import responses as REASONS
from typing import TextIO

from mitmproxy import http

from burpweb.cleanup import clean_response
from burpweb.matcher import Incoming, Matcher, Tier

MISS_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Not in snapshot</title>
<body style="font-family: sans-serif; margin: 2em">
<h1>Not in snapshot</h1>
<p>burpweb has no captured response for:</p>
<pre>{method} {url}</pre>
</body>
"""


class Replay:
    def __init__(self, matcher: Matcher, out: TextIO | None = None):
        self.matcher = matcher
        self.out = out or sys.stdout
        self.misses: collections.Counter[str] = collections.Counter()

    def request(self, flow: http.HTTPFlow) -> None:
        req = flow.request
        path, _, query = req.path.partition("?")
        record, tier = self.matcher.match(
            Incoming(
                scheme=req.scheme,
                host=req.host,
                port=req.port,
                method=req.method,
                path=path or "/",
                query=query,
                body=req.raw_content or b"",
                content_type=req.headers.get("content-type", ""),
            )
        )
        url = req.pretty_url
        if record is None:
            self.misses[f"{req.method} {url}"] += 1
            page = MISS_PAGE.format(method=html.escape(req.method), url=html.escape(url))
            flow.response = http.Response.make(404, page, {"Content-Type": "text/html; charset=utf-8"})
            self._log(tier, req.method, url, 404)
            return

        headers, body = clean_response(record.response_headers, record.response_body)
        if req.method.upper() == "HEAD":
            body = b""
        now = time.time()
        flow.response = http.Response(
            http_version=b"HTTP/1.1",
            status_code=record.status,
            reason=REASONS.get(record.status, "").encode(),
            headers=http.Headers([(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers]),
            content=body,  # raw bytes: keeps any Content-Encoding intact
            trailers=None,
            timestamp_start=now,
            timestamp_end=now,
        )
        index = record.index if tier in (Tier.FALLBACK, Tier.HEAD) else None
        self._log(tier, req.method, url, record.status, index)

    def done(self) -> None:
        print(self.summary(), file=self.out, flush=True)

    def summary(self) -> str:
        if not self.misses:
            return "No misses: every request was answered from the snapshot."
        lines = [f"--- {len(self.misses)} unique URL(s) not in snapshot ---"]
        lines += [f"{count:>5}  {key}" for key, count in self.misses.most_common()]
        return "\n".join(lines)

    def _log(self, tier: Tier, method: str, url: str, status: int, burp_index: int | None = None) -> None:
        extra = f"  [burp #{burp_index}]" if burp_index is not None else ""
        print(f"{tier.value:<8} {method} {url}  -> {status}{extra}", file=self.out, flush=True)
