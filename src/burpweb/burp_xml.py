"""Stream-parse Burp Suite "Save items" XML exports into Records."""

from __future__ import annotations

import base64
import binascii
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}
_LINE_BREAK = re.compile(rb"\r?\n")


class BurpXmlError(Exception):
    """The file can't be read as a Burp XML export."""


@dataclass(frozen=True)
class Record:
    index: int
    time: str
    scheme: str
    host: str
    port: int
    method: str
    path: str
    query: str
    request_body: bytes
    request_content_type: str
    status: int
    response_headers: tuple[tuple[str, str], ...]
    response_body: bytes
    source: str = ""  # export file name, set when several exports are combined

    @property
    def origin(self) -> str:
        if self.port == _DEFAULT_PORTS.get(self.scheme):
            return f"{self.scheme}://{self.host}"
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def url(self) -> str:
        return self.origin + self.path + (f"?{self.query}" if self.query else "")


@dataclass
class LoadResult:
    records: list[Record] = field(default_factory=list)
    skipped_no_response: int = 0
    malformed: list[tuple[int, str]] = field(default_factory=list)


def split_message(raw: bytes) -> tuple[str, list[tuple[str, str]], bytes]:
    """Split a raw HTTP message into (start line, headers, body)."""
    for separator in (b"\r\n\r\n", b"\n\n"):
        head, found, body = raw.partition(separator)
        if found:
            break
    else:
        head, body = raw, b""
    lines = _LINE_BREAK.split(head)
    start = lines[0].decode("latin-1").strip()
    headers = []
    for line in lines[1:]:
        if not line.strip():
            continue
        if line[:1] in (b" ", b"\t") and headers:  # obsolete line folding: continues the previous value
            name, value = headers[-1]
            headers[-1] = (name, f"{value} {line.decode('latin-1').strip()}")
            continue
        name, colon, value = line.decode("latin-1").partition(":")
        if not colon:
            raise ValueError(f"bad header line {line[:60]!r}")
        headers.append((name.strip(), value.strip()))
    return start, headers, body


def load(path: str | Path) -> LoadResult:
    """Parse a Burp export. Bad items are counted, never fatal; a bad file raises BurpXmlError."""
    result = LoadResult()
    index = 0
    root = None
    try:
        for event, elem in ET.iterparse(path, events=("start", "end")):
            if root is None:
                if elem.tag != "items":
                    raise BurpXmlError(
                        f"{path}: root element is <{elem.tag}>, expected <items> "
                        "(export with Proxy > HTTP history > Save items)"
                    )
                root = elem
                continue
            if event != "end" or elem.tag != "item":
                continue
            index += 1
            try:
                record = _parse_item(index, elem)
            except ValueError as e:
                result.malformed.append((index, str(e)))
            else:
                if record is None:
                    result.skipped_no_response += 1
                else:
                    result.records.append(record)
            root.clear()  # keep memory flat on large exports
    except ET.ParseError as e:
        raise BurpXmlError(
            f"{path}: not valid XML ({e}). If you exported without base64, re-export with "
            "'Base64-encode requests and responses' enabled."
        ) from None
    except OSError as e:
        raise BurpXmlError(f"{path}: {e.strerror or e}") from None
    return result


def load_many(paths: list[str | Path]) -> LoadResult:
    """Load several exports as one history, in the given order (later files are more recent)."""
    combined = LoadResult()
    tag = len(paths) > 1
    for path in paths:
        result = load(path)
        name = Path(path).name
        combined.records += [replace(r, source=name) for r in result.records] if tag else result.records
        combined.skipped_no_response += result.skipped_no_response
        combined.malformed += [(i, f"{reason} (in {name})" if tag else reason) for i, reason in result.malformed]
    return combined


def _parse_item(index: int, item: ET.Element) -> Record | None:
    """Return a Record, or None when the item has no response. Raise ValueError if malformed."""
    response_el = item.find("response")
    if response_el is None or not (response_el.text or "").strip():
        return None
    request_el = item.find("request")
    if request_el is None:
        raise ValueError("missing <request>")
    try:
        raw_request = _decode(request_el)
        raw_response = _decode(response_el)
    except binascii.Error as e:
        raise ValueError(f"bad base64: {e}") from None

    request_line, request_headers, request_body = split_message(raw_request)
    parts = request_line.split()
    if len(parts) < 2:
        raise ValueError(f"bad request line {request_line[:60]!r}")
    method, target = parts[0].upper(), parts[1]
    if "://" in target:
        url = urlsplit(target)
        target = (url.path or "/") + (f"?{url.query}" if url.query else "")
    path, _, query = target.partition("?")

    status_line, response_headers, response_body = split_message(raw_response)
    status = _status(status_line)
    # Interim responses (100 Continue, 103 Early Hints) are stored ahead of the final one.
    while 100 <= status < 200 and status != 101 and response_body:
        status_line, response_headers, response_body = split_message(response_body)
        status = _status(status_line)
    if 100 <= status < 200:
        return None  # a 101 upgrade (WebSocket) or a lone interim response can't be replayed

    scheme = (item.findtext("protocol") or "").strip().lower()
    host = (item.findtext("host") or "").strip().lower()
    port = (item.findtext("port") or "").strip()
    if scheme not in _DEFAULT_PORTS or not host or not port.isdigit():
        raise ValueError("missing or invalid protocol/host/port")

    return Record(
        index=index,
        time=(item.findtext("time") or "").strip(),
        scheme=scheme,
        host=host,
        port=int(port),
        method=method,
        path=path or "/",
        query=query,
        request_body=request_body,
        request_content_type=_header(request_headers, "content-type"),
        status=status,
        response_headers=tuple(response_headers),
        response_body=response_body,
    )


def _status(status_line: str) -> int:
    parts = status_line.split()
    if len(parts) < 2 or not parts[0].upper().startswith("HTTP/") or not parts[1].isdigit():
        raise ValueError(f"bad status line {status_line[:60]!r}")
    return int(parts[1])


def _decode(elem: ET.Element) -> bytes:
    text = elem.text or ""
    if elem.get("base64") == "true":
        return base64.b64decode("".join(text.split()), validate=True)
    return text.encode("utf-8")


def _header(headers: list[tuple[str, str]], name: str) -> str:
    return next((value for key, value in headers if key.lower() == name), "")
