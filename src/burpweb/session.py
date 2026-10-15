"""Run one replay proxy at a time on the shared event loop."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

from mitmproxy import addons as mitm_addons
from mitmproxy import master as mitm_master
from mitmproxy.options import Options

from burpweb.addon import Replay
from burpweb.browser import FirefoxLauncher
from burpweb.matcher import Matcher

MISSES_INTERVAL = 0.5  # seconds: at most one "misses" event per interval


class ReplayStartError(Exception):
    pass


class _Ready:
    """mitmproxy addon: resolves a future once the proxy server has (not) bound."""

    def __init__(self, master, fut):
        self.master = master
        self.fut = fut

    def running(self):
        srv = self.master.addons.get("proxyserver")
        instances = list(srv.servers)
        if not self.fut.done():
            self.fut.set_result(instances)


async def _close_listeners(master) -> None:
    """Close the proxy's listening sockets.

    Master.shutdown() only ends the run loop; mitmproxy never closes its own listeners because
    mitmdump just exits the process. Here the process lives on, so without this the old proxy
    would keep answering on its port and a restart on that port would fail.
    """
    proxy = master.addons.get("proxyserver")
    for instance in list(proxy.servers):
        if instance.is_running:
            await instance.stop()


async def _close_connections(master) -> None:
    """End every open client connection (keep-alive sessions, CONNECT tunnels).

    Closing the listeners only stops new connections; a browser's keep-alive connection would
    otherwise keep being answered from the snapshot after Stop or Lock.
    """
    proxy = master.addons.get("proxyserver")
    tasks = []
    for handler in list(proxy.connections.values()):
        for io in list(handler.transports.values()):
            if io.handler is not None:
                io.handler.cancel("burpweb: replay stopped")
                tasks.append(io.handler)
    if tasks:
        await asyncio.wait(tasks, timeout=5)


class ReplaySession:
    def __init__(self, confdir: Path):
        self.confdir = Path(confdir)
        # Start and stop must never interleave: two starts would orphan a proxy, and a stop issued
        # while a start is in flight would otherwise be a silent no-op (Lock relies on stop()).
        self._lock = asyncio.Lock()
        self._master = None
        self._task = None
        self._port = None
        self._snapshot_id = None
        self._start_url = None
        self._subs: list[Callable[[dict], None]] = []
        self._records = []
        self._pending_misses: dict | None = None
        self._misses_handle = None
        self._misses_sent_at = 0.0

    @property
    def state(self):
        return {"running": self._master is not None, "port": self._port, "snapshot_id": self._snapshot_id}

    @property
    def start_url(self):
        return self._start_url

    def subscribe(self, cb):
        self._subs.append(cb)

    def unsubscribe(self, cb):
        if cb in self._subs:
            self._subs.remove(cb)

    def _broadcast(self, event: dict):
        for cb in list(self._subs):
            cb(event)

    def _emit(self, event: dict):
        event.setdefault("ts", int(time.time() * 1000))
        if event["type"] != "misses":
            self._broadcast(event)
            return
        # Every miss would otherwise resend the whole list: coalesce to the latest, once per interval.
        self._pending_misses = event
        if self._misses_handle is None:
            wait = max(0.0, MISSES_INTERVAL - (time.monotonic() - self._misses_sent_at))
            self._misses_handle = asyncio.get_running_loop().call_later(wait, self._flush_misses)

    def _flush_misses(self):
        if self._misses_handle is not None:
            self._misses_handle.cancel()
            self._misses_handle = None
        event, self._pending_misses = self._pending_misses, None
        if event is not None:
            self._misses_sent_at = time.monotonic()
            self._broadcast(event)

    async def start(self, records, port, snapshot_id=None):
        async with self._lock:
            await self._start(records, port, snapshot_id)

    async def stop(self):
        async with self._lock:
            await self._stop()

    async def _start(self, records, port, snapshot_id):
        if self._master is not None:
            await self._stop()
        records = list(records)
        matcher = Matcher(records)
        master = mitm_master.Master(
            Options(listen_host="127.0.0.1", listen_port=port, confdir=str(self.confdir)))
        master.addons.add(*mitm_addons.default_addons())
        master.addons.add(Replay(matcher, on_event=self._emit))
        loop = asyncio.get_running_loop()
        ready = loop.create_future()
        master.addons.add(_Ready(master, ready))
        # Plain Master, not DumpMaster: DumpMaster's error-check addon sys.exit()s on a startup
        # error (e.g. a busy port), which would take the whole UI process down with it.
        master.options.update(connection_strategy="lazy", upstream_cert=False,
                              http3=False, rawtcp=False)
        task = asyncio.create_task(master.run())
        try:
            instances = await asyncio.wait_for(ready, timeout=15)
        except asyncio.TimeoutError:
            master.shutdown()
            await task
            raise self._failed(snapshot_id, "replay proxy did not start in time")
        failed = [i for i in instances if not i.is_running]
        if failed:
            exc = failed[0].last_exception
            await _close_listeners(master)
            master.shutdown()
            await task
            raise self._failed(snapshot_id, str(exc) if exc else f"could not bind port {port}")
        self._master, self._task, self._port = master, task, port
        self._snapshot_id = snapshot_id
        self._start_url = records[0].url if records else None
        self._records = records
        self._emit({"type": "replay", "running": True, "port": port, "snapshot_id": snapshot_id})

    def _failed(self, snapshot_id, message) -> ReplayStartError:
        self._emit({"type": "toast", "level": "error", "message": f"{message} (choose another port)"})
        self._emit({"type": "replay", "running": False, "port": None, "snapshot_id": snapshot_id})
        return ReplayStartError(message)

    async def _stop(self):
        if self._master is None:
            return
        master, task, snapshot_id = self._master, self._task, self._snapshot_id
        self._master = self._task = self._port = None
        await _close_listeners(master)
        await _close_connections(master)
        master.shutdown()
        await task
        # Forget what was decrypted for this replay: Stop and Lock are the security boundary.
        self._records = []
        self._snapshot_id = self._start_url = None
        self._flush_misses()
        self._emit({"type": "replay", "running": False, "port": None, "snapshot_id": snapshot_id})

    def open_browser(self, start_url=None):
        launcher = FirefoxLauncher(port=self._port, confdir=self.confdir,
                                   start_url=start_url or self._start_url or "https://localhost/")
        launcher.running()
        return launcher
