import asyncio
import socket
import subprocess
import pytest
from burpfixtures import make_record
from burpweb.matcher import Matcher
from burpweb.session import ReplaySession, ReplayStartError

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_running(session, timeout=10):
    for _ in range(int(timeout * 20)):
        if session.state["running"]:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("did not start")


async def test_start_serves_and_stop(tmp_path):
    rec = make_record(1, host="shop.invalid", path="/x", response_body=b"hi there")
    session = ReplaySession(confdir=tmp_path / "conf")
    events = []
    session.subscribe(events.append)
    port = free_port()
    await session.start([rec], port)
    await _wait_running(session)
    # curl must run off the event loop: the proxy lives on this loop and could never answer it.
    out = await asyncio.to_thread(
        subprocess.run,
        ["curl", "-s", "-x", f"http://127.0.0.1:{port}", "--cacert",
         str(tmp_path / "conf" / "mitmproxy-ca-cert.pem"), "https://shop.invalid/x"],
        capture_output=True, timeout=15)
    assert out.stdout == b"hi there"
    await asyncio.sleep(0.2)
    assert any(e.get("tier") == "EXACT" for e in events)
    await session.stop()
    assert session.state["running"] is False


async def test_busy_port_reports_without_crashing(tmp_path):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        session = ReplaySession(confdir=tmp_path / "conf")
        with pytest.raises(ReplayStartError):
            await session.start([make_record(1)], port)
    assert session.state["running"] is False
    # session can still start afterwards on a good port
    await session.start([make_record(1, host="shop.invalid", path="/x")], free_port())
    await _wait_running(session)
    await session.stop()


async def test_switch_snapshots(tmp_path):
    session = ReplaySession(confdir=tmp_path / "conf")
    await session.start([make_record(1, host="a.invalid", path="/x")], free_port())
    await _wait_running(session)
    p2 = free_port()
    await session.stop()
    await session.start([make_record(1, host="b.invalid", path="/y")], p2)
    await _wait_running(session)
    assert session.state["port"] == p2
    await session.stop()


async def test_stop_actually_closes_the_port(tmp_path):
    session = ReplaySession(confdir=tmp_path / "conf")
    port = free_port()
    await session.start([make_record(1, host="shop.invalid", path="/x")], port)
    await session.stop()
    with pytest.raises(OSError):  # nothing may still be listening after stop()
        socket.create_connection(("127.0.0.1", port), timeout=2).close()


async def test_restart_on_the_same_port_after_stop(tmp_path):
    session = ReplaySession(confdir=tmp_path / "conf")
    port = free_port()
    await session.start([make_record(1, host="shop.invalid", path="/x")], port)
    await session.stop()
    await session.start([make_record(1, host="shop.invalid", path="/x")], port)  # must not hit "address in use"
    assert session.state == {"running": True, "port": port}
    await session.stop()
