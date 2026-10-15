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
    assert session.state["running"] is True and session.state["port"] == port
    await session.stop()


def _refused(port):
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=2).close()


async def test_concurrent_starts_do_not_orphan_a_proxy(tmp_path):
    session = ReplaySession(confdir=tmp_path / "conf")
    rec = make_record(1, host="shop.invalid", path="/x")
    p1, p2 = free_port(), free_port()
    await asyncio.gather(session.start([rec], p1), session.start([rec], p2))
    assert session.state["running"] is True
    await session.stop()
    _refused(p1)
    _refused(p2)


async def test_stop_issued_during_start_wins(tmp_path):
    session = ReplaySession(confdir=tmp_path / "conf")
    port = free_port()
    starting = asyncio.create_task(session.start([make_record(1, host="shop.invalid", path="/x")], port))
    await asyncio.sleep(0)  # let start() begin
    await session.stop()
    await starting
    assert session.state["running"] is False
    _refused(port)


async def test_stop_ends_open_connections_and_forgets_the_records(tmp_path):
    rec = make_record(1, scheme="http", port=80, host="shop.invalid", path="/x", response_body=b"hi")
    session = ReplaySession(confdir=tmp_path / "conf")
    port = free_port()
    await session.start([rec], port, snapshot_id="abc")
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    request = b"GET http://shop.invalid/x HTTP/1.1\r\nHost: shop.invalid\r\n\r\n"
    writer.write(request)
    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
    assert head.startswith(b"HTTP/1.1 200")
    await reader.readexactly(2)  # the body, "hi"
    await session.stop()
    try:  # an already-open keep-alive connection must not keep serving after stop()
        writer.write(request)
        data = await asyncio.wait_for(reader.read(1000), 5)
    except OSError:
        data = b""
    assert data == b""
    assert session._records == [] and session.start_url is None
    writer.close()


async def test_state_and_events_carry_snapshot_id_and_timestamp(tmp_path):
    session = ReplaySession(confdir=tmp_path / "conf")
    events = []
    session.subscribe(events.append)
    port = free_port()
    assert session.state == {"running": False, "port": None, "snapshot_id": None}
    await session.start([make_record(1, host="shop.invalid", path="/x")], port, snapshot_id="abc")
    assert session.state == {"running": True, "port": port, "snapshot_id": "abc"}
    await session.stop()
    replay = [e for e in events if e["type"] == "replay"]
    assert [(e["running"], e["snapshot_id"]) for e in replay] == [(True, "abc"), (False, "abc")]
    assert all(isinstance(e["ts"], int) for e in events)


async def test_busy_port_emits_toast_and_stopped_event(tmp_path):
    session = ReplaySession(confdir=tmp_path / "conf")
    events = []
    session.subscribe(events.append)
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        with pytest.raises(ReplayStartError):
            await session.start([make_record(1)], busy.getsockname()[1], snapshot_id="abc")
    toast = [e for e in events if e["type"] == "toast"]
    assert toast and toast[0]["level"] == "error" and "another port" in toast[0]["message"]
    assert [e for e in events if e["type"] == "replay"][-1]["running"] is False


async def test_misses_events_are_throttled_and_the_latest_is_delivered(tmp_path):
    session = ReplaySession(confdir=tmp_path / "conf")
    got = []
    session.subscribe(got.append)
    for i in range(50):
        session._emit({"type": "misses", "misses": [{"key": f"k{i}", "count": 1}]})
    await asyncio.sleep(0.8)
    misses = [e for e in got if e["type"] == "misses"]
    assert 1 <= len(misses) <= 2
    assert misses[-1]["misses"][0]["key"] == "k49"
