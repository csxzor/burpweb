"""Run one replay proxy at a time on the shared event loop."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from mitmproxy import addons as mitm_addons
from mitmproxy import master as mitm_master
from mitmproxy.options import Options

from burpweb.addon import Replay
from burpweb.browser import FirefoxLauncher
from burpweb.matcher import Matcher


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


class ReplaySession:
    def __init__(self, confdir: Path):
        self.confdir = Path(confdir)
        self._master = None
        self._task = None
        self._port = None
        self._subs: list[Callable[[dict], None]] = []
        self._records = []

    @property
    def state(self):
        return {"running": self._master is not None, "port": self._port}

    def subscribe(self, cb):
        self._subs.append(cb)

    def unsubscribe(self, cb):
        if cb in self._subs:
            self._subs.remove(cb)

    def _emit(self, event: dict):
        for cb in list(self._subs):
            cb(event)

    async def start(self, records, port):
        if self._master is not None:
            await self.stop()
        self._records = list(records)
        matcher = Matcher(self._records)
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
            raise ReplayStartError("replay proxy did not start in time")
        failed = [i for i in instances if not i.is_running]
        if failed:
            exc = failed[0].last_exception
            await _close_listeners(master)
            master.shutdown()
            await task
            raise ReplayStartError(str(exc) if exc else f"could not bind port {port}")
        self._master, self._task, self._port = master, task, port
        self._emit({"type": "replay", "running": True, "port": port})

    async def stop(self):
        if self._master is None:
            return
        master, task = self._master, self._task
        self._master = self._task = self._port = None
        await _close_listeners(master)
        master.shutdown()
        await task
        self._emit({"type": "replay", "running": False, "port": None})

    def open_browser(self, start_url):
        launcher = FirefoxLauncher(port=self._port, confdir=self.confdir, start_url=start_url)
        launcher.running()
        return launcher
