import gzip

import pytest

from burpfixtures import make_item
from burpweb.burp_xml import BurpXmlError, load, load_many

GET_INDEX = b"GET /index.html?b=2&a=1 HTTP/1.1\r\nHost: example.com\r\n\r\n"
OK_HTML = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nSet-Cookie: a=1\r\nSet-Cookie: b=2\r\n\r\n<h1>hi</h1>"


def test_base64_item_parsed(write_xml):
    result = load(write_xml([make_item(request=GET_INDEX, response=OK_HTML)]))
    assert result.skipped_no_response == 0 and result.malformed == []
    (rec,) = result.records
    assert rec.index == 1
    assert (rec.scheme, rec.host, rec.port) == ("https", "example.com", 443)
    assert (rec.method, rec.path, rec.query) == ("GET", "/index.html", "b=2&a=1")
    assert rec.request_body == b""
    assert rec.status == 200
    assert rec.response_headers == (
        ("Content-Type", "text/html"),
        ("Set-Cookie", "a=1"),
        ("Set-Cookie", "b=2"),
    )
    assert rec.response_body == b"<h1>hi</h1>"
    assert rec.time == "Wed Oct 15 10:00:00 UTC 2026"
    assert rec.url == "https://example.com/index.html?b=2&a=1"


def test_raw_item_parsed(write_xml):
    req = b"POST /login HTTP/1.1\r\nHost: example.com\r\nContent-Type: application/x-www-form-urlencoded\r\n\r\nu=a&p=b"
    result = load(write_xml([make_item(request=req, response=OK_HTML, b64=False)]))
    (rec,) = result.records
    assert rec.method == "POST"
    assert rec.request_body == b"u=a&p=b"
    assert rec.request_content_type == "application/x-www-form-urlencoded"
    assert rec.response_body == b"<h1>hi</h1>"


def test_items_without_response_are_skipped(write_xml):
    path = write_xml(
        [
            make_item(request=GET_INDEX, response=None),
            make_item(request=GET_INDEX, response=b""),
            make_item(request=GET_INDEX, response=OK_HTML),
        ]
    )
    result = load(path)
    assert result.skipped_no_response == 2
    assert [r.index for r in result.records] == [3]


def test_malformed_item_reported_and_load_continues(write_xml):
    path = write_xml(
        [
            make_item(request=GET_INDEX, response=b"garbage\r\n\r\nbody"),
            make_item(request=GET_INDEX, response=OK_HTML),
        ]
    )
    result = load(path)
    assert [r.index for r in result.records] == [2]
    assert len(result.malformed) == 1
    index, reason = result.malformed[0]
    assert index == 1 and "status line" in reason


def test_bodies_kept_byte_exact(write_xml):
    zipped = gzip.compress(b"console.log(1)")
    gz = b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\n\r\n" + zipped
    chunked = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n4\r\nWiki\r\n0\r\n\r\n"
    result = load(write_xml([make_item(request=GET_INDEX, response=gz), make_item(request=GET_INDEX, response=chunked)]))
    assert result.records[0].response_body == zipped
    assert result.records[1].response_body == b"4\r\nWiki\r\n0\r\n\r\n"


def test_http_and_non_default_port(write_xml):
    req = b"GET /v1/items HTTP/1.1\r\nHost: API.invalid:8080\r\n\r\n"
    result = load(write_xml([make_item(request=req, response=OK_HTML, host="API.invalid", port=8080, protocol="http")]))
    (rec,) = result.records
    assert (rec.scheme, rec.host, rec.port) == ("http", "api.invalid", 8080)
    assert rec.origin == "http://api.invalid:8080"
    assert rec.url == "http://api.invalid:8080/v1/items"


def test_http2_format_item(write_xml):
    req = b'POST /api?x=1 HTTP/2\r\nhost: example.com\r\ncontent-type: application/json\r\n\r\n{"a":1}'
    resp = b"HTTP/2 201 Created\r\ncontent-type: application/json\r\n\r\n{}"
    (rec,) = load(write_xml([make_item(request=req, response=resp)])).records
    assert (rec.method, rec.path, rec.query, rec.status) == ("POST", "/api", "x=1", 201)
    assert rec.request_content_type == "application/json"
    assert rec.response_headers == (("content-type", "application/json"),)


def test_absolute_form_request_target(write_xml):
    req = b"GET http://example.com/a/b?c=d HTTP/1.1\r\nHost: example.com\r\n\r\n"
    (rec,) = load(write_xml([make_item(request=req, response=OK_HTML, port=80, protocol="http")])).records
    assert (rec.path, rec.query) == ("/a/b", "c=d")


def test_folded_header_lines_are_joined(write_xml):
    req = b"GET / HTTP/1.1\r\nHost: example.com\r\nAuthorization: Bearer abc\r\n def\r\nAccept: */*\r\n\r\n"
    resp = b"HTTP/1.1 200 OK\r\nX-Long: one\r\n\ttwo\r\nContent-Type: text/plain\r\n\r\nok"
    (rec,) = load(write_xml([make_item(request=req, response=resp)])).records
    assert rec.response_headers == (("X-Long", "one two"), ("Content-Type", "text/plain"))


def test_websocket_upgrade_skipped(write_xml):
    req = b"GET /ws HTTP/1.1\r\nHost: example.com\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
    resp = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
    result = load(write_xml([make_item(request=req, response=resp)]))
    assert result.records == []
    assert result.skipped_no_response == 1


@pytest.mark.parametrize("interim", [b"HTTP/1.1 100 Continue\r\n\r\n", b"HTTP/1.1 103 Early Hints\r\nLink: </a.css>\r\n\r\n"])
def test_interim_response_prefix_uses_final_response(write_xml, interim):
    resp = interim + b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nok"
    (rec,) = load(write_xml([make_item(request=GET_INDEX, response=resp)])).records
    assert rec.status == 200
    assert rec.response_headers == (("Content-Type", "text/plain"),)
    assert rec.response_body == b"ok"


def test_bare_interim_response_skipped(write_xml):
    result = load(write_xml([make_item(request=GET_INDEX, response=b"HTTP/1.1 100 Continue\r\n\r\n")]))
    assert result.records == [] and result.skipped_no_response == 1


def test_load_many_combines_files_in_order(write_xml):
    first = write_xml([make_item(request=GET_INDEX, response=OK_HTML), make_item(request=GET_INDEX, response=None)], "first.xml")
    second = write_xml(
        [make_item(request=GET_INDEX, response=b"junk"), make_item(request=GET_INDEX, response=OK_HTML)], "second.xml"
    )
    result = load_many([first, second])
    assert [(r.source, r.index) for r in result.records] == [("first.xml", 1), ("second.xml", 2)]
    assert result.skipped_no_response == 1
    assert result.malformed == [(1, "bad status line 'junk' (in second.xml)")]


def test_load_many_single_file_has_no_source(write_xml):
    result = load_many([write_xml([make_item(request=GET_INDEX, response=OK_HTML)])])
    assert [r.source for r in result.records] == [""]


def test_invalid_xml_suggests_base64(tmp_path):
    path = tmp_path / "bad.xml"
    path.write_bytes(b'<?xml version="1.0"?><items><item><response base64="false">\x01\x02</response></item></items>')
    with pytest.raises(BurpXmlError, match="Base64-encode"):
        load(path)


def test_wrong_root_element(tmp_path):
    path = tmp_path / "other.xml"
    path.write_text("<html><body/></html>")
    with pytest.raises(BurpXmlError, match="<items>"):
        load(path)


def test_missing_file(tmp_path):
    with pytest.raises(BurpXmlError):
        load(tmp_path / "nope.xml")
