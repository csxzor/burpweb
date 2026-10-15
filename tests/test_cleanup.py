import gzip
import zlib

import brotli
import pytest

from burpweb.cleanup import clean_response, dechunk

CHUNKED = b"4\r\nWiki\r\n5;ext=1\r\npedia\r\n0\r\n\r\n"


def names(headers):
    return [k.lower() for k, _ in headers]


def value(headers, name):
    return next(v for k, v in headers if k.lower() == name)


def test_dechunk_valid():
    assert dechunk(CHUNKED) == b"Wikipedia"


@pytest.mark.parametrize("bad", [b"zz\r\nabc\r\n0\r\n\r\n", b"10\r\nshort\r\n", b"no crlf at all", b"-1\r\n\r\n"])
def test_dechunk_invalid(bad):
    with pytest.raises(ValueError):
        dechunk(bad)


def test_chunked_body_is_decoded():
    headers, body = clean_response([("Transfer-Encoding", "chunked"), ("Content-Type", "text/plain")], CHUNKED)
    assert body == b"Wikipedia"
    assert "transfer-encoding" not in names(headers)
    assert value(headers, "content-length") == "9"


def test_invalid_chunked_body_kept_but_header_removed():
    headers, body = clean_response([("Transfer-Encoding", "chunked")], b"not chunked")
    assert body == b"not chunked"
    assert "transfer-encoding" not in names(headers)


@pytest.mark.parametrize(
    "encoding, compress",
    [("gzip", gzip.compress), ("deflate", zlib.compress), ("deflate", lambda b: zlib.compress(b)[2:-4]), ("br", brotli.compress)],
)
def test_valid_content_encoding_kept(encoding, compress):
    data = compress(b"hello world")
    headers, body = clean_response([("Content-Encoding", encoding)], data)
    assert body == data
    assert value(headers, "content-encoding") == encoding
    assert value(headers, "content-length") == str(len(data))


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br"])
def test_content_encoding_dropped_when_body_already_decoded(encoding):
    headers, body = clean_response([("Content-Encoding", encoding), ("Content-Type", "text/plain")], b"plain text")
    assert body == b"plain text"
    assert "content-encoding" not in names(headers)


def test_unknown_content_encoding_kept():
    headers, _ = clean_response([("Content-Encoding", "compress")], b"whatever")
    assert value(headers, "content-encoding") == "compress"


def test_strips_hop_by_hop_and_alt_svc():
    headers, _ = clean_response(
        [
            ("Connection", "keep-alive"),
            ("Keep-Alive", "timeout=5"),
            ("Proxy-Connection", "keep-alive"),
            ("Upgrade", "h2c"),
            ("Alt-Svc", 'h3=":443"'),
            ("Set-Cookie", "a=1"),
            ("Content-Security-Policy", "default-src 'self'"),
            ("Set-Cookie", "b=2"),
        ],
        b"x",
    )
    assert headers == [
        ("Set-Cookie", "a=1"),
        ("Content-Security-Policy", "default-src 'self'"),
        ("Set-Cookie", "b=2"),
        ("Content-Length", "1"),
    ]


def test_stale_content_length_replaced():
    headers, _ = clean_response([("Content-Length", "999")], b"abc")
    assert [v for k, v in headers if k.lower() == "content-length"] == ["3"]
