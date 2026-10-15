import socket
import subprocess
import sys

from burpfixtures import make_item
from burpweb.cli import main

OK = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nok"


def req(path, host="example.com"):
    return f"GET {path} HTTP/1.1\r\nHost: {host}\r\n\r\n".encode()


def test_list_shows_origins_sorted_by_count(write_xml, capsys):
    path = write_xml(
        [
            make_item(request=req("/a"), response=OK),
            make_item(request=req("/b"), response=OK),
            make_item(request=req("/a"), response=OK),
            make_item(request=req("/x", "api.invalid"), response=OK, host="api.invalid", port=8080, protocol="http"),
            make_item(request=req("/a"), response=None),
        ]
    )
    assert main(["list", str(path)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Loaded 4 items across 2 origin(s); skipped 1 without a response, 0 malformed."
    assert out[1:] == [
        " ITEMS  PATHS  ORIGIN",
        "     3      2  https://example.com",
        "     1      1  http://api.invalid:8080",
    ]


def test_malformed_items_listed_in_summary(write_xml, capsys):
    path = write_xml([make_item(request=req("/a"), response=b"junk"), make_item(request=req("/a"), response=OK)])
    assert main(["list", str(path)]) == 0
    out = capsys.readouterr().out
    assert "1 malformed" in out
    assert "  malformed item #1: bad status line" in out


def test_missing_file_exit_2(tmp_path, capsys):
    assert main(["list", str(tmp_path / "nope.xml")]) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_empty_export_exit_1(write_xml, capsys):
    path = write_xml([make_item(request=req("/a"), response=None)])
    assert main(["serve", str(path)]) == 1
    assert "no usable items" in capsys.readouterr().err


def test_port_in_use_exits_with_hint(write_xml, tmp_path):
    path = write_xml([make_item(request=req("/a"), response=OK)])
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        proc = subprocess.run(
            [sys.executable, "-m", "burpweb", "serve", str(path), "--port", str(port), "--confdir", str(tmp_path / "conf")],
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert proc.returncode == 1
    assert "--port" in proc.stderr
