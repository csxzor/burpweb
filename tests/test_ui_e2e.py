"""Drive the real control page in headless Firefox (WebDriver BiDi).

Create the library, drop an export onto the page, create a snapshot, start a replay, make a
request through the proxy, see it in the live feed, then lock and confirm the proxy is closed.

Skipped when Firefox or curl is missing or the frontend has not been built.
Set BURPWEB_E2E_SHOTS=<dir> to save a screenshot after each step (used for the visual review).
"""

import asyncio
import base64
import json
import os
import select
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import tornado.websocket

from burpfixtures import make_item, make_xml

INDEX = Path(__file__).resolve().parents[1] / "src" / "burpweb" / "static" / "index.html"
pytestmark = pytest.mark.skipif(
    shutil.which("firefox") is None or shutil.which("curl") is None or not INDEX.exists(),
    reason="needs firefox, curl and a built frontend (cd frontend && npm run build)",
)

PREFS = """
user_pref("app.update.auto", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("network.captive-portal-service.enabled", false);
user_pref("browser.safebrowsing.malware.enabled", false);
"""
REQUEST = b"GET /p HTTP/1.1\r\nHost: shop.invalid\r\n\r\n"
RESPONSE = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nhi"
PASSPHRASE = "e2e-test-passphrase"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def printed_url(proc: subprocess.Popen, timeout: float = 30) -> str:
    ready, _, _ = select.select([proc.stdout], [], [], timeout)
    if not ready:
        raise RuntimeError("burpweb ui did not print its URL")
    line = proc.stdout.readline()
    assert "control page:" in line, line
    return line.split("control page:")[1].strip()


class Bidi:
    def __init__(self, ws):
        self.ws = ws
        self.counter = 0

    @classmethod
    async def connect(cls, port: int) -> "Bidi":
        for _ in range(150):
            try:
                return cls(await tornado.websocket.websocket_connect(f"ws://127.0.0.1:{port}/session"))
            except Exception:
                await asyncio.sleep(0.2)
        raise RuntimeError("firefox did not start")

    async def call(self, method: str, **params):
        self.counter += 1
        mid = self.counter
        await self.ws.write_message(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            message = json.loads(await self.ws.read_message())
            if message.get("id") == mid:
                if message.get("type") == "error":
                    raise RuntimeError(message)
                return message["result"]

    async def js(self, ctx: str, expression: str):
        result = await self.call(
            "script.evaluate", expression=expression, target={"context": ctx}, awaitPromise=True
        )
        if result["type"] == "exception":
            raise RuntimeError(result["exceptionDetails"]["text"])
        return result["result"].get("value")

    async def wait_for(self, ctx: str, expression: str, timeout: float = 20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await self.js(ctx, f"Boolean({expression})"):
                return
            await asyncio.sleep(0.15)
        raise AssertionError(f"timed out waiting for: {expression}")


def click_button(label: str) -> str:
    """True (after clicking) once an enabled button with this exact text exists."""
    return (
        "(() => { const b = [...document.querySelectorAll('button')]"
        f".find(b => b.textContent.trim() === {json.dumps(label)});"
        " if (!b || b.disabled) return false; b.click(); return true; })()"
    )


def fill(selector: str, value: str) -> str:
    return (
        f"(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return false;"
        " Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set"
        f".call(el, {json.dumps(value)});"
        " el.dispatchEvent(new Event('input', {bubbles: true})); return true; })()"
    )


def drop_file(zone_selector: str, name: str, text: str) -> str:
    return (
        "(() => {"
        f" const zone = document.querySelector({json.dumps(zone_selector)}); if (!zone) return false;"
        f" const dt = new DataTransfer(); dt.items.add(new File([{json.dumps(text)}], {json.dumps(name)}));"
        " zone.dispatchEvent(new DragEvent('dragenter', {bubbles: true, cancelable: true, dataTransfer: dt}));"
        " zone.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: dt}));"
        " return true; })()"
    )


async def test_full_flow_through_the_real_page(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home)}
    profile = tmp_path / "firefox"
    profile.mkdir()
    (profile / "user.js").write_text(PREFS)
    shots = os.environ.get("BURPWEB_E2E_SHOTS")
    export = make_xml([make_item(host="shop.invalid", request=REQUEST, response=RESPONSE)])

    server = subprocess.Popen(
        [sys.executable, "-m", "burpweb", "ui", "--no-open", "--port", str(free_port())],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    bidi_port = free_port()
    firefox = subprocess.Popen(
        ["firefox", "--headless", "--remote-debugging-port", str(bidi_port), "-profile", str(profile),
         "-no-remote", "--window-size=1440,900"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        url = printed_url(server)
        bidi = await Bidi.connect(bidi_port)
        await bidi.call("session.new", capabilities={})
        ctx = (await bidi.call("browsingContext.create", type="tab"))["context"]

        async def shot(name: str):
            if shots:
                await asyncio.sleep(0.8)  # let the entry animations settle
                Path(shots).mkdir(parents=True, exist_ok=True)
                png = (await bidi.call("browsingContext.captureScreenshot", context=ctx))["data"]
                (Path(shots) / f"{name}.png").write_bytes(base64.b64decode(png))

        async def until(expression: str):
            await bidi.wait_for(ctx, expression)

        await bidi.call("browsingContext.navigate", context=ctx, url=url, wait="complete")

        # 1. a new library: create the passphrase
        await until("document.querySelector('input[type=password]')")
        await shot("1-create-library")
        await until(fill("label:nth-of-type(1) input", PASSPHRASE))
        await until(fill("label:nth-of-type(2) input", PASSPHRASE))
        await until(click_button("Create library"))
        await until("document.querySelector('[aria-label=\"Live feed\"]')")
        await shot("2-new-snapshot")

        # 2. drop an export on the page
        await until(drop_file("[role=button][aria-label^='Drop Burp XML']", "history.xml", export))
        await until("document.querySelector('.chip[data-status=\"done\"]')")
        await shot("3-uploaded")
        await until(click_button("Create snapshot"))
        await until("[...document.querySelectorAll('.card-name')].some(e => e.textContent.includes('history'))")
        await until("document.querySelector('.replay-panel')")
        await shot("4-snapshot")

        # 3. replay it and request the page through the proxy
        replay_port = free_port()
        await until(fill("input[aria-label='Replay port']", str(replay_port)))
        await until(click_button("Start replay"))
        await until("document.body.textContent.includes('Replaying on 127.0.0.1:')")
        ca = home / ".mitmproxy" / "mitmproxy-ca-cert.pem"
        out = await asyncio.to_thread(
            subprocess.run,
            ["curl", "-s", "-x", f"http://127.0.0.1:{replay_port}", "--cacert", str(ca), "https://shop.invalid/p"],
            capture_output=True, timeout=30,
        )
        assert out.stdout == b"hi"
        await until("[...document.querySelectorAll('.feed-row')].some(r => r.textContent.includes('https://shop.invalid/p'))")
        await shot("5-replaying")

        # 4. design and privacy invariants, checked in the real browser
        assert not await bidi.js(
            ctx,
            "[...document.querySelectorAll('*')].some(e => getComputedStyle(e).backgroundImage.includes('gradient'))",
        ), "no element may use a gradient"
        assert await bidi.js(
            ctx,
            "document.fonts.ready.then(() => document.fonts.check('13px \"Schibsted Grotesk\"')"
            " && document.fonts.check('13px \"JetBrains Mono\"'))",
        ), "the bundled fonts must be loaded"
        assert await bidi.js(
            ctx,
            "performance.getEntriesByType('resource').every(r => new URL(r.name).origin === location.origin)",
        ), "the page must only load resources from its own origin"

        # 5. lock: back to the unlock screen, and the replay proxy is gone
        await until(click_button("Lock"))
        await until("document.querySelector('input[type=password]')")
        await shot("6-locked")
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", replay_port), timeout=2).close()
    finally:
        firefox.terminate()
        server.terminate()
        for proc in (firefox, server):
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
