"""Run the real proxy and fetch through it with curl. Hosts use .invalid so any upstream attempt would fail."""

import gzip
import shutil
import signal
import socket
import subprocess
import sys
import time

import pytest

from burpfixtures import make_item, make_xml

pytestmark = pytest.mark.skipif(shutil.which("curl") is None, reason="curl not installed")

APP_JS = gzip.compress(b"console.log('shop');")
ITEMS = [
    make_item(
        host="shop.invalid",
        request=b"GET /index.html HTTP/1.1\r\nHost: shop.invalid\r\n\r\n",
        response=b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: keep-alive\r\nKeep-Alive: timeout=5\r\n\r\n<h1>shop</h1>",
    ),
    make_item(
        host="shop.invalid",
        request=b"GET /app.js HTTP/1.1\r\nHost: shop.invalid\r\n\r\n",
        response=b"HTTP/1.1 200 OK\r\nContent-Type: text/javascript\r\nContent-Encoding: gzip\r\n\r\n" + APP_JS,
    ),
    make_item(
        host="api.invalid",
        port=8080,
        protocol="http",
        request=b"GET /v1/items?id=1 HTTP/1.1\r\nHost: api.invalid:8080\r\n\r\n",
        response=b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{"id":1}',
    ),
]


@pytest.fixture(scope="module")
def proxy(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    export = tmp / "history.xml"
    export.write_text(make_xml(ITEMS), encoding="utf-8")
    confdir = tmp / "conf"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, "-m", "burpweb", "serve", str(export), "--port", str(port), "--confdir", str(confdir)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 30
    while True:
        if proc.poll() is not None:
            pytest.fail(f"proxy exited early:\n{proc.stdout.read()}")
        if (confdir / "mitmproxy-ca-cert.pem").exists():
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                pass
        if time.monotonic() > deadline:
            proc.kill()
            pytest.fail("proxy did not start within 30s")
        time.sleep(0.1)
    yield port, confdir / "mitmproxy-ca-cert.pem", proc
    if proc.poll() is None:
        proc.kill()
        proc.wait()


def curl(proxy, url, *extra):
    port, ca, _ = proxy
    result = subprocess.run(
        ["curl", "-sS", "--max-time", "10", "-x", f"http://127.0.0.1:{port}", "--cacert", str(ca), "-w", "\n%{http_code}", *extra, url],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    body, _, code = result.stdout.rpartition("\n")
    return int(code), body


def test_https_over_http1(proxy):
    assert curl(proxy, "https://shop.invalid/index.html", "--http1.1") == (200, "<h1>shop</h1>")


def test_https_over_http2(proxy):
    assert curl(proxy, "https://shop.invalid/index.html", "--http2") == (200, "<h1>shop</h1>")


def test_gzip_asset_decodes(proxy):
    assert curl(proxy, "https://shop.invalid/app.js", "--compressed") == (200, "console.log('shop');")


def test_plain_http_non_default_port(proxy):
    assert curl(proxy, "http://api.invalid:8080/v1/items?id=1") == (200, '{"id":1}')


def test_unknown_url_is_snapshot_404(proxy):
    code, body = curl(proxy, "https://shop.invalid/missing")
    assert code == 404 and "Not in snapshot" in body


def test_zz_shutdown_prints_log_and_miss_summary(proxy):
    # Runs last (pytest keeps definition order): stops the module's proxy.
    _, _, proc = proxy
    proc.send_signal(signal.SIGINT)
    out, _ = proc.communicate(timeout=20)
    assert proc.returncode == 0, out
    assert "EXACT    GET https://shop.invalid/index.html  -> 200" in out
    assert "MISS     GET https://shop.invalid/missing  -> 404" in out
    assert "--- 1 unique URL(s) not in snapshot ---" in out
