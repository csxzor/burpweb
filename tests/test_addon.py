import gzip
import io

from mitmproxy import http
from mitmproxy.test import tflow

from burpfixtures import make_record
from burpweb.addon import Replay
from burpweb.matcher import Matcher


def flow(method, url, body=b"", headers=None):
    return tflow.tflow(req=http.Request.make(method, url, body, headers or {}))


def replay(*records):
    out = io.StringIO()
    return Replay(Matcher(records), out=out), out


def test_exact_hit_sets_response_in_request_hook():
    rec = make_record(1, path="/a", headers=(("Content-Type", "text/html"), ("Connection", "keep-alive")), response_body=b"<p>a</p>")
    addon, out = replay(rec)
    f = flow("GET", "https://example.com/a")
    addon.request(f)
    # A response set during the request hook means mitmproxy never opens an upstream connection.
    assert f.response is not None
    assert f.response.status_code == 200
    assert f.response.raw_content == b"<p>a</p>"
    assert f.response.headers["Content-Type"] == "text/html"
    assert f.response.headers["Content-Length"] == "8"
    assert "Connection" not in f.response.headers
    assert out.getvalue() == "EXACT    GET https://example.com/a  -> 200\n"


def test_gzip_body_passed_through_raw():
    data = gzip.compress(b"var x = 1;")
    rec = make_record(1, path="/app.js", headers=(("Content-Encoding", "gzip"),), response_body=data)
    addon, _ = replay(rec)
    f = flow("GET", "https://example.com/app.js")
    addon.request(f)
    assert f.response.raw_content == data
    assert f.response.content == b"var x = 1;"


def test_fallback_logs_burp_index():
    addon, out = replay(make_record(7, path="/s", query="q=1"))
    addon.request(flow("GET", "https://example.com/s?q=2"))
    assert out.getvalue() == "FALLBACK GET https://example.com/s?q=2  -> 200  [burp #7]\n"


def test_head_gets_empty_body():
    addon, out = replay(make_record(3, path="/h", response_body=b"full body"))
    f = flow("HEAD", "https://example.com/h")
    addon.request(f)
    assert f.response.raw_content == b""
    assert f.response.headers["Content-Length"] == "9"
    assert out.getvalue().startswith("HEAD     HEAD https://example.com/h  -> 200  [burp #3]")


def test_post_body_used_for_exact_match():
    a = make_record(1, method="POST", path="/api", body=b'{"id":1}', content_type="application/json", response_body=b"one")
    b = make_record(2, method="POST", path="/api", body=b'{"id":2}', content_type="application/json", response_body=b"two")
    addon, _ = replay(a, b)
    f = flow("POST", "https://example.com/api", b'{"id": 1}', {"Content-Type": "application/json"})
    addon.request(f)
    assert f.response.raw_content == b"one"


def test_miss_returns_snapshot_404_and_is_counted():
    addon, out = replay(make_record(1, path="/a"))
    for _ in range(2):
        f = flow("GET", "http://example.com:8080/<x>")
        addon.request(f)
    assert f.response.status_code == 404
    assert b"Not in snapshot" in f.response.content
    assert b"http://example.com:8080/&lt;x&gt;" in f.response.content
    assert addon.misses == {"GET http://example.com:8080/<x>": 2}
    assert "MISS     GET http://example.com:8080/<x>  -> 404" in out.getvalue()


def test_summary_lists_misses_by_count():
    addon, out = replay(make_record(1, path="/a"))
    addon.request(flow("GET", "https://example.com/b"))
    addon.request(flow("GET", "https://example.com/c"))
    addon.request(flow("GET", "https://example.com/c"))
    addon.done()
    tail = out.getvalue().splitlines()[-3:]
    assert tail == [
        "--- 2 unique URL(s) not in snapshot ---",
        "    2  GET https://example.com/c",
        "    1  GET https://example.com/b",
    ]


def test_summary_without_misses():
    addon, _ = replay(make_record(1))
    assert addon.summary() == "No misses: every request was answered from the snapshot."
