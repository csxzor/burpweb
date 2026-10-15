"""Pick the captured response for an incoming request."""

from __future__ import annotations

import enum
import json
from collections.abc import Iterable
from dataclasses import dataclass, replace
from urllib.parse import parse_qsl

from burpweb.burp_xml import Record


class Tier(enum.Enum):
    EXACT = "EXACT"
    FALLBACK = "FALLBACK"
    HEAD = "HEAD"
    MISS = "MISS"


@dataclass(frozen=True)
class Incoming:
    scheme: str
    host: str
    port: int
    method: str
    path: str
    query: str
    body: bytes
    content_type: str = ""


def normalize_query(query: str) -> tuple:
    return tuple(sorted(parse_qsl(query, keep_blank_values=True)))


def normalize_body(body: bytes, content_type: str) -> tuple:
    if not body:
        return ("raw", b"")
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime == "application/x-www-form-urlencoded":
        return ("form", tuple(sorted(parse_qsl(body.decode("latin-1"), keep_blank_values=True))))
    if mime == "application/json" or mime.endswith("+json"):
        try:
            return ("json", json.dumps(json.loads(body), sort_keys=True, separators=(",", ":")))
        except ValueError:
            pass
    return ("raw", body)


# Answers to conditional or Range requests: useless to a browser that asks unconditionally.
PARTIAL_STATUSES = {206, 304}


class Matcher:
    def __init__(self, records: Iterable[Record]):
        self._exact_full: dict[tuple, Record] = {}
        self._exact_any: dict[tuple, Record] = {}
        self._success_full: dict[tuple, Record] = {}
        self._any: dict[tuple, Record] = {}
        for rec in records:
            base = (rec.scheme, rec.host.lower(), rec.port, rec.method.upper(), rec.path)
            exact = base + (
                normalize_query(rec.query),
                normalize_body(rec.request_body, rec.request_content_type),
            )
            full = rec.status not in PARTIAL_STATUSES
            _keep_latest(self._exact_any, exact, rec)
            _keep_latest(self._any, base, rec)
            if full:
                _keep_latest(self._exact_full, exact, rec)
                if rec.status < 400:
                    _keep_latest(self._success_full, base, rec)

    def match(self, req: Incoming) -> tuple[Record | None, Tier]:
        found = self._lookup(req)
        if found:
            return found
        if req.method.upper() == "HEAD":
            found = self._lookup(replace(req, method="GET"))
            if found:
                return found[0], Tier.HEAD
        return None, Tier.MISS

    def _lookup(self, req: Incoming) -> tuple[Record, Tier] | None:
        base = (req.scheme.lower(), req.host.lower(), req.port, req.method.upper(), req.path)
        exact = base + (normalize_query(req.query), normalize_body(req.body, req.content_type))
        # Full responses first; a captured 304/206 is only a last resort.
        if exact in self._exact_full:
            return self._exact_full[exact], Tier.EXACT
        if base in self._success_full:
            return self._success_full[base], Tier.FALLBACK
        if exact in self._exact_any:
            return self._exact_any[exact], Tier.EXACT
        if base in self._any:
            return self._any[base], Tier.FALLBACK
        return None


def _keep_latest(index: dict[tuple, Record], key: tuple, rec: Record) -> None:
    # Records arrive in history order (item numbers restart per export), so the last one wins.
    index[key] = rec
