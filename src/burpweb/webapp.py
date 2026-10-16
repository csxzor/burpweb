"""Local Tornado control server for the burpweb UI."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import secrets
import shutil
import webbrowser
from pathlib import Path

from urllib.parse import urlparse

import tornado.ioloop
import tornado.web
import tornado.websocket

from burpweb import vault
from burpweb.burp_xml import BurpXmlError
from burpweb.library import Library, LibraryLocked, SnapshotDamaged
from burpweb.session import ReplaySession, ReplayStartError

ALLOWED_HOSTS_SUFFIX = ("127.0.0.1", "localhost")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
SNAPSHOT_ID = re.compile(r"[0-9a-f]+")


def _token_ok(given, token) -> bool:
    """Constant-time comparison; encoding first keeps a non-ASCII value a mismatch instead of a TypeError."""
    return given is not None and hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8"))


class _Base(tornado.web.RequestHandler):
    def initialize(self, app_state):
        self.app_state = app_state

    def prepare(self):
        host = (self.request.host or "").split(":")[0]
        if host not in ALLOWED_HOSTS_SUFFIX:
            self.set_status(403)
            self.finish({"error": "forbidden host"})
            return
        if not _token_ok(self.get_cookie("bw_token"), self.app_state["token"]):
            self.set_status(403)
            self.finish({"error": "missing or bad token"})
            return
        # SameSite ignores ports, so a page on another 127.0.0.1 port still carries our cookie. Browsers always
        # send Origin on cross-origin writes; refuse any that is not this server. (curl and tests send none.)
        origin = self.request.headers.get("Origin")
        if (self.request.method not in SAFE_METHODS and origin is not None
                and urlparse(origin).netloc != self.request.host):
            self.set_status(403)
            self.finish({"error": "cross-origin request refused"})

    def write_error(self, status_code, **kwargs):
        self.finish({"error": self._reason})

    @property
    def library(self) -> Library:
        return self.app_state["library"]

    @property
    def session(self) -> ReplaySession:
        return self.app_state["session"]

    def json_body(self) -> dict:
        try:
            body = json.loads(self.request.body or b"{}")
        except ValueError:
            raise tornado.web.HTTPError(400, reason="invalid JSON") from None
        if not isinstance(body, dict):
            raise tornado.web.HTTPError(400, reason="expected a JSON object")
        return body

    @staticmethod
    def field(body: dict, key: str, kind: type):
        value = body.get(key)
        if not isinstance(value, kind):
            raise tornado.web.HTTPError(400, reason=f"'{key}' must be a {kind.__name__}")
        return value

    def upload_ids(self, body: dict) -> list:
        ids = self.field(body, "uploads", list)
        if not all(isinstance(i, str) for i in ids):
            raise tornado.web.HTTPError(400, reason="'uploads' must be a list of upload ids")
        return ids

    def require_snapshot(self, sid: str) -> None:
        if not SNAPSHOT_ID.fullmatch(sid) or not (self.library.root / sid).is_dir():
            raise tornado.web.HTTPError(404, reason="no such snapshot")

    def require_unlocked(self):
        if self.library.state != "unlocked":
            self.set_status(423)
            self.finish({"error": "library locked"})
            return False
        return True


class TokenHandler(tornado.web.RequestHandler):
    def initialize(self, app_state):
        self.app_state = app_state

    def get(self):
        host = (self.request.host or "").split(":")[0]
        if host not in ALLOWED_HOSTS_SUFFIX:
            self.set_status(403); return
        if _token_ok(self.get_argument("token", None), self.app_state["token"]):
            self.set_cookie("bw_token", self.app_state["token"],
                            httponly=True, samesite="Strict", path="/")
            self.redirect("/")
            return
        if _token_ok(self.get_cookie("bw_token"), self.app_state["token"]):
            self._serve_index()
            return
        self.set_status(403)
        self.finish("Missing token. Launch burpweb from the terminal to get the URL.")

    def _serve_index(self):
        static = self.app_state["static_dir"]
        index = static and (Path(static) / "index.html")
        if index and index.exists():
            self.set_header("Content-Type", "text/html")
            self.finish(index.read_bytes())
        else:
            self.finish("burpweb UI (frontend not built)")


class StateHandler(_Base):
    def get(self):
        state = self.session.state
        self.finish({"vault": self.library.state, "replay": state if state["running"] else None})


class VaultHandler(_Base):
    async def post(self, action):
        body = self.json_body()
        if action == "create":
            if self.library.state != "new":
                self.set_status(409); self.finish({"error": "vault already exists"}); return
            pw = body.get("passphrase", "")
            if len(pw) < 10:
                self.set_status(400); self.finish({"error": "passphrase too short"}); return
            self.library.create_vault(pw)
            self.finish({"ok": True})
        elif action == "unlock":
            if self.library.unlock(body.get("passphrase", "")):
                self.finish({"ok": True})
            else:
                self.set_status(401); self.finish({"error": "wrong passphrase"})
        elif action == "lock":
            await self.session.stop()
            _purge_uploads(self.app_state)
            self.library.cleanup_temp()  # also staged uploads still being written
            self.library.lock()
            self.finish({"ok": True})
        else:
            self.set_status(404); self.finish({"error": "unknown action"})


class SnapshotsHandler(_Base):
    def get(self):
        if not self.require_unlocked():
            return
        # Tornado refuses to serialize a bare list (a legacy XSSI guard), so write the JSON ourselves.
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps([vars(s) for s in self.library.list()]))

    def post(self):
        if not self.require_unlocked():
            return
        body = self.json_body()
        name, ids = self.field(body, "name", str), self.upload_ids(body)
        uploads = self.app_state["uploads"]
        try:
            sources, names = _claim(uploads, ids, self.library)
        except (KeyError, FileNotFoundError, vault.BadData):
            _drop(uploads, ids)
            self.set_status(400); self.finish({"error": "unknown or expired upload"}); return
        try:
            snap = self.library.create(name, sources, names)
        except (BurpXmlError, ValueError) as e:
            _drop(uploads, ids)
            self.set_status(422); self.finish({"error": str(e)}); return
        _drop(uploads, ids)
        self.finish(vars(snap))


class SnapshotHandler(_Base):
    def patch(self, sid):
        if not self.require_unlocked():
            return
        name = self.field(self.json_body(), "name", str)
        self.require_snapshot(sid)
        try:
            snap = self.library.rename(sid, name)
        except SnapshotDamaged:
            self.set_status(409); self.finish({"error": "snapshot damaged"}); return
        self.finish(vars(snap))

    async def delete(self, sid):
        if not self.require_unlocked():
            return
        if self.session.state["snapshot_id"] == sid:
            await self.session.stop()
        self.library.delete(sid)
        self.set_status(204); self.finish()


class SnapshotFilesHandler(_Base):
    def post(self, sid):  # add files
        if not self.require_unlocked():
            return
        ids = self.upload_ids(self.json_body())
        self.require_snapshot(sid)
        uploads = self.app_state["uploads"]
        try:
            sources, names = _claim(uploads, ids, self.library)
        except (KeyError, FileNotFoundError, vault.BadData):
            _drop(uploads, ids)
            self.set_status(400); self.finish({"error": "unknown or expired upload"}); return
        try:
            snap = self.library.add_files(sid, sources, names)
        except SnapshotDamaged:
            _drop(uploads, ids)
            self.set_status(409); self.finish({"error": "snapshot damaged"}); return
        except (BurpXmlError, ValueError) as e:
            _drop(uploads, ids)
            self.set_status(422); self.finish({"error": str(e)}); return
        _drop(uploads, ids)
        self.finish(vars(snap))


@tornado.web.stream_request_body
class UploadHandler(_Base):
    """Encrypts the request body to disk as it arrives; plaintext is never written out.

    Streaming is required, not optional: Tornado rejects buffered bodies over 100 MB, and
    real Burp exports are larger (the user's is 164 MB).
    """

    MAX_BYTES = 2 * 1024**3

    def prepare(self):
        super().prepare()
        self.enc = None
        self._registered = False
        if self._finished or not self.require_unlocked():
            return
        self.upload_id = self.path_args[0]
        taken = self.app_state["uploads"].keys() | self.app_state["inflight"]
        if self.upload_id in taken:  # a second PUT would clobber (and on abort delete) the first
            self.set_status(409); self.finish({"error": "upload id already used"}); return
        self.app_state["inflight"].add(self.upload_id)
        self._registered = True
        self.size = 0
        self.tmp = self.library.root / f".tmp-upload-{self.upload_id}"
        self.tmp.mkdir(parents=True, exist_ok=True)
        os.chmod(self.tmp, 0o700)
        self.out = open(self.tmp / "data.enc", "wb")
        os.chmod(self.tmp / "data.enc", 0o600)
        self.enc = vault.StreamEncryptor(
            self.library._require_key(), snapshot_id=f"upload-{self.upload_id}", label="0")
        self.request.connection.set_max_body_size(self.MAX_BYTES)

    def data_received(self, chunk):
        if self.enc is None:
            return
        self.size += len(chunk)
        self.out.write(self.enc.feed(chunk))

    def put(self, upload_id):
        self.out.write(self.enc.finish())
        self.out.close()
        if self.library.state != "unlocked":  # locked while the body was still arriving
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.set_status(423); self.finish({"error": "library locked"}); return
        name = self.get_argument("name", "upload.xml")
        self.app_state["uploads"][upload_id] = {"name": name, "path": self.tmp, "size": self.size}
        self.finish({"upload_id": upload_id, "size": self.size})

    def _release(self):
        if self._registered:
            self._registered = False
            self.app_state["inflight"].discard(self.upload_id)

    def on_finish(self):
        self._release()

    def on_connection_close(self):
        out = getattr(self, "out", None)
        if out is not None and not out.closed:  # client went away mid-upload
            out.close()
            shutil.rmtree(self.tmp, ignore_errors=True)
        self._release()


class ReplayHandler(_Base):
    async def post(self):
        if not self.require_unlocked():
            return
        body = self.json_body()
        sid = self.field(body, "snapshot_id", str)
        if not SNAPSHOT_ID.fullmatch(sid):
            raise tornado.web.HTTPError(400, reason="'snapshot_id' is not a snapshot id")
        try:
            port = int(body.get("port") or 8081)
        except (TypeError, ValueError):
            raise tornado.web.HTTPError(400, reason="'port' must be a number") from None
        if not 1 <= port <= 65535:
            raise tornado.web.HTTPError(400, reason="'port' must be between 1 and 65535")
        self.require_snapshot(sid)
        control_port = self.request.connection.stream.socket.getsockname()[1]
        if port == control_port:
            self.set_status(409)
            self.finish({"error": f"port {port} is the control page's own; choose another for the replay"})
            return
        try:
            records = self.library.load_records(sid)
        except SnapshotDamaged:
            self.set_status(409); self.finish({"error": "snapshot damaged"}); return
        try:
            await self.session.start(records, port, snapshot_id=sid)
        except ReplayStartError as e:
            self.set_status(409); self.finish({"error": str(e)}); return
        if self.library.state != "unlocked":  # Lock ran while this start was queued behind it
            await self.session.stop()
            self.set_status(423); self.finish({"error": "library locked"}); return
        self.finish({"snapshot_id": sid, "port": port, "running": True})

    async def delete(self):
        if not self.require_unlocked():
            return
        await self.session.stop()
        self.set_status(204); self.finish()


class BrowserHandler(_Base):
    def post(self):
        if not self.require_unlocked():
            return
        if not self.session.state["running"]:
            self.set_status(409); self.finish({"error": "no replay running"}); return
        launcher = self.session.open_browser()
        if launcher.process is None:
            self.set_status(409)
            self.finish({"error": "firefox/certutil not available; see terminal for manual setup"})
            return
        self.finish({"ok": True})


class EventsSocket(tornado.websocket.WebSocketHandler):
    def initialize(self, app_state):
        self.app_state = app_state

    def prepare(self):
        host = (self.request.host or "").split(":")[0]
        if host not in ALLOWED_HOSTS_SUFFIX or not _token_ok(self.get_cookie("bw_token"), self.app_state["token"]):
            self.set_status(403)
            self.finish()

    def check_origin(self, origin):
        # Same-origin only: the page that opens this socket was served by this very server.
        return urlparse(origin).netloc == self.request.host

    def open(self):
        self._cb = lambda e: self._send(e)
        self.app_state["session"].subscribe(self._cb)

    def _send(self, event):
        tornado.ioloop.IOLoop.current().add_callback(self._write, event)

    def _write(self, event):
        try:
            self.write_message(json.dumps(event))
        except tornado.websocket.WebSocketClosedError:
            pass

    def on_close(self):
        self.app_state["session"].unsubscribe(getattr(self, "_cb", None))


def _claim(uploads, ids, library):
    sources, names = [], []
    for uid in ids:
        info = uploads[uid]
        key = library._require_key()
        blob = (info["path"] / "data.enc").read_bytes()
        data = vault.decrypt_bytes(key, blob, snapshot_id=f"upload-{uid}", label="0")
        sources.append(data)
        names.append(info["name"])
    return sources, names


def _drop(uploads, ids):
    for uid in ids:
        info = uploads.pop(uid, None)
        if info:
            shutil.rmtree(info["path"], ignore_errors=True)


def _purge_uploads(state):
    _drop(state["uploads"], list(state["uploads"]))


def make_app(library, session, token, *, static_dir=None):
    state = {"library": library, "session": session, "token": token,
             "uploads": {}, "inflight": set(), "static_dir": static_dir}
    kw = {"app_state": state}
    routes = [
        (r"/", TokenHandler, kw),
        (r"/api/state", StateHandler, kw),
        (r"/api/vault/(create|unlock|lock)", VaultHandler, kw),
        (r"/api/snapshots", SnapshotsHandler, kw),
        (r"/api/snapshots/([0-9a-f]+)", SnapshotHandler, kw),
        (r"/api/snapshots/([0-9a-f]+)/files", SnapshotFilesHandler, kw),
        (r"/api/uploads/([A-Za-z0-9_-]+)", UploadHandler, kw),
        (r"/api/replay", ReplayHandler, kw),
        (r"/api/browser", BrowserHandler, kw),
        (r"/api/events", EventsSocket, kw),
    ]
    settings = {}
    if static_dir:
        settings["static_path"] = str(static_dir)
    app = tornado.web.Application(routes, **settings)
    app.settings["bw_state"] = state
    return app


def run(host="127.0.0.1", port=8765, open_browser=True, static_dir=None):
    from pathlib import Path as _P
    default_static = _P(__file__).parent / "static"
    static = static_dir or (str(default_static) if default_static.exists() else None)
    library = Library(_P.home() / ".local/share/burpweb/library")
    session = ReplaySession(confdir=_P.home() / ".mitmproxy")
    token = secrets.token_urlsafe(32)
    app = make_app(library, session, token, static_dir=static)

    async def serve_forever():
        bound = None
        for p in range(port, port + 21):
            try:
                app.listen(p, address=host)
                bound = p
                break
            except OSError:
                continue
        if bound is None:
            raise SystemExit(f"error: no free port in {port}..{port + 20}")
        url = f"http://{host}:{bound}/?token={token}"
        print(f"burpweb control page: {url}", flush=True)
        print("Keep this terminal open. Press Ctrl-C to stop.", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            await asyncio.Event().wait()  # Tornado and the replay proxy share this one loop
        finally:
            await session.stop()
            _purge_uploads(app.settings["bw_state"])
            library.cleanup_temp()
            library.lock()

    asyncio.run(serve_forever())
