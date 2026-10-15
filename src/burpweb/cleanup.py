"""Make a captured response safe to send again to a browser."""

from __future__ import annotations

import gzip
import zlib
from collections.abc import Iterable

# Connection-level headers: meaningless when replaying, and illegal over HTTP/2.
HOP_BY_HOP = {"connection", "keep-alive", "proxy-connection", "transfer-encoding", "upgrade", "te", "trailer"}
_DROP = HOP_BY_HOP | {"content-length", "alt-svc"}


def dechunk(body: bytes) -> bytes:
    """Decode a chunked transfer-encoded body; raise ValueError if it isn't validly chunked."""
    out = bytearray()
    pos = 0
    while True:
        eol = body.find(b"\r\n", pos)
        if eol < 0:
            raise ValueError("missing chunk size line")
        size_text = body[pos:eol].split(b";", 1)[0].strip()
        try:
            size = int(size_text, 16)
        except ValueError:
            raise ValueError(f"bad chunk size {size_text[:20]!r}") from None
        if size < 0:
            raise ValueError("negative chunk size")
        pos = eol + 2
        if size == 0:
            return bytes(out)
        if body[pos + size : pos + size + 2] != b"\r\n":
            raise ValueError("truncated chunk")
        out += body[pos : pos + size]
        pos += size + 2


def clean_response(headers: Iterable[tuple[str, str]], body: bytes) -> tuple[list[tuple[str, str]], bytes]:
    headers = list(headers)
    if any(k.lower() == "transfer-encoding" and "chunked" in v.lower() for k, v in headers):
        try:
            body = dechunk(body)
        except ValueError:
            pass
    out = [(k, v) for k, v in headers if k.lower() not in _DROP]
    encoding = ", ".join(v for k, v in out if k.lower() == "content-encoding").strip().lower()
    if encoding and _decodes(encoding, body) is False:
        out = [(k, v) for k, v in out if k.lower() != "content-encoding"]
    out.append(("Content-Length", str(len(body))))
    return out, body


def _decodes(encoding: str, body: bytes) -> bool | None:
    """Whether body is valid for encoding; None when we can't check that encoding."""
    try:
        if encoding in ("gzip", "x-gzip"):
            gzip.decompress(body)
        elif encoding == "deflate":
            try:
                zlib.decompress(body)
            except zlib.error:
                zlib.decompress(body, -zlib.MAX_WBITS)
        elif encoding == "br":
            try:
                import brotli
            except ImportError:
                return None
            brotli.decompress(body)
        else:
            return None
    except Exception:  # each decoder raises its own error types
        return False
    return True
