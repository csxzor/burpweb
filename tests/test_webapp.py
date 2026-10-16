import asyncio
import json
import pytest
import tornado.testing
import tornado.web
from burpfixtures import make_item, make_xml
from burpweb.library import Library
from burpweb.session import ReplaySession
from burpweb.webapp import make_app

OK = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nhi"
REQ = b"GET /p HTTP/1.1\r\nHost: shop.invalid\r\n\r\n"
XML = make_xml([make_item(host="shop.invalid", request=REQ, response=OK)]).encode()
TOKEN = "test-token-123"


class Base(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        self.library = Library(self.get_temp_dir() / "lib")
        self.session = ReplaySession(confdir=self.get_temp_dir() / "conf")
        return make_app(self.library, self.session, TOKEN)

    def get_temp_dir(self):
        import pathlib, tempfile
        if not hasattr(self, "_td"):
            self._td = pathlib.Path(tempfile.mkdtemp())
        return self._td

    def cookie(self):
        return {"Cookie": f"bw_token={TOKEN}", "Host": "127.0.0.1"}

    def api(self, method, path, body=None, headers=None):
        h = {**self.cookie(), **(headers or {})}
        kw = {"method": method, "headers": h}
        if body is not None:
            kw["body"] = json.dumps(body)
        elif method in ("POST", "PUT", "PATCH"):
            kw["body"] = ""  # Tornado's client rejects these methods with no body at all
        return self.fetch(path, **kw)


class TestAuth(Base):
    def test_requires_token(self):
        r = self.fetch("/api/state", headers={"Host": "127.0.0.1"})
        assert r.code == 403

    def test_rejects_foreign_host(self):
        r = self.fetch("/api/state", headers={"Cookie": f"bw_token={TOKEN}", "Host": "evil.com"})
        assert r.code == 403

    @tornado.testing.gen_test
    async def test_websocket_requires_token(self):
        import tornado.httpclient
        import tornado.websocket
        with pytest.raises(tornado.httpclient.HTTPClientError) as e:
            await tornado.websocket.websocket_connect(self.get_url("/api/events").replace("http", "ws", 1))
        assert e.value.code == 403

    def test_token_handshake_sets_cookie(self):
        r = self.fetch(f"/?token={TOKEN}", headers={"Host": "127.0.0.1"}, follow_redirects=False)
        assert r.code in (302, 303)
        assert "bw_token=" in r.headers.get("Set-Cookie", "")


class TestFlow(Base):
    def test_state_new_then_unlocked(self):
        assert json.loads(self.api("GET", "/api/state").body)["vault"] == "new"
        r = self.api("POST", "/api/vault/create", {"passphrase": "passphrase-123"})
        assert r.code == 200
        assert json.loads(self.api("GET", "/api/state").body)["vault"] == "unlocked"

    def test_locked_returns_423(self):
        self.api("POST", "/api/vault/create", {"passphrase": "passphrase-123"})
        self.api("POST", "/api/vault/lock")
        assert self.api("GET", "/api/snapshots").code == 423

    def test_upload_create_and_list(self):
        self.api("POST", "/api/vault/create", {"passphrase": "passphrase-123"})
        up = self.fetch("/api/uploads/u1?name=history.xml", method="PUT", body=XML, headers=self.cookie())
        assert up.code == 200
        r = self.api("POST", "/api/snapshots", {"name": "Treasury", "uploads": ["u1"]})
        assert r.code == 200
        snaps = json.loads(self.api("GET", "/api/snapshots").body)
        assert snaps[0]["name"] == "Treasury" and snaps[0]["stats"]["items"] == 1
        assert len(snaps[0]["id"]) == 32  # 16 random bytes, as the spec says

    def _snapshot(self, upload_id="u1"):
        self.api("POST", "/api/vault/create", {"passphrase": "passphrase-123"})
        self.fetch(f"/api/uploads/{upload_id}?name=h.xml", method="PUT", body=XML, headers=self.cookie())
        return json.loads(self.api("POST", "/api/snapshots", {"name": "s", "uploads": [upload_id]}).body)["id"]

    def test_lock_discards_staged_uploads_and_claiming_one_is_a_400(self):
        self.api("POST", "/api/vault/create", {"passphrase": "passphrase-123"})
        self.fetch("/api/uploads/u1?name=h.xml", method="PUT", body=XML, headers=self.cookie())
        library_dir = self.get_temp_dir() / "lib"
        assert list(library_dir.glob(".tmp-upload-*"))
        self.api("POST", "/api/vault/lock")
        assert not list(library_dir.glob(".tmp-upload-*"))
        self.api("POST", "/api/vault/unlock", {"passphrase": "passphrase-123"})
        assert self.api("POST", "/api/snapshots", {"name": "x", "uploads": ["u1"]}).code == 400

    def test_reusing_an_upload_id_is_rejected_and_keeps_the_first(self):
        self.api("POST", "/api/vault/create", {"passphrase": "passphrase-123"})
        first = self.fetch("/api/uploads/u1?name=h.xml", method="PUT", body=XML, headers=self.cookie())
        again = self.fetch("/api/uploads/u1?name=other.xml", method="PUT", body=b"<x/>", headers=self.cookie())
        assert (first.code, again.code) == (200, 409)
        r = self.api("POST", "/api/snapshots", {"name": "s", "uploads": ["u1"]})
        assert r.code == 200 and json.loads(r.body)["stats"]["items"] == 1

    def test_unknown_upload_id_is_a_400_for_create_and_add_files(self):
        sid = self._snapshot()
        assert self.api("POST", "/api/snapshots", {"name": "n", "uploads": ["nope"]}).code == 400
        assert self.api("POST", f"/api/snapshots/{sid}/files", {"uploads": ["nope"]}).code == 400

    def test_wrong_verbs_are_not_routed(self):
        sid = self._snapshot()
        assert self.api("DELETE", f"/api/snapshots/{sid}/files").code == 405
        assert self.api("POST", f"/api/snapshots/{sid}", {"uploads": []}).code == 405
        assert len(json.loads(self.api("GET", "/api/snapshots").body)) == 1  # nothing was deleted

    def test_browser_and_replay_stop_return_423_while_locked(self):
        self.api("POST", "/api/vault/create", {"passphrase": "passphrase-123"})
        self.api("POST", "/api/vault/lock")
        assert self.api("POST", "/api/browser").code == 423
        assert self.api("DELETE", "/api/replay").code == 423

    def test_replay_refuses_the_control_pages_own_port(self):
        sid = self._snapshot()
        r = self.api("POST", "/api/replay", {"snapshot_id": sid, "port": self.get_http_port()})
        assert r.code == 409 and b"control page" in r.body

    def test_invalid_upload_rejected_and_cleaned(self):
        self.api("POST", "/api/vault/create", {"passphrase": "passphrase-123"})
        self.fetch("/api/uploads/u2?name=bad.xml", method="PUT",
                   body=b'<?xml version="1.0"?><items><item><response base64="false">\x01</response></item></items>',
                   headers=self.cookie())
        r = self.api("POST", "/api/snapshots", {"name": "bad", "uploads": ["u2"]})
        assert r.code == 422
        assert b"Base64" in r.body or b"base64" in r.body
        assert json.loads(self.api("GET", "/api/snapshots").body) == []
        # the staged ciphertext of the rejected upload is deleted too
        assert not list((self.get_temp_dir() / "lib").glob(".tmp-upload-*"))

    def test_upload_over_tornados_default_body_limit_is_streamed(self):
        # Tornado rejects buffered bodies over 100 MB; real Burp exports (164 MB here) are larger.
        self.api("POST", "/api/vault/create", {"passphrase": "passphrase-123"})
        size = 101 * 1024 * 1024
        r = self.fetch("/api/uploads/big?name=big.xml", method="PUT", body=bytes(size),
                       headers=self.cookie(), request_timeout=120)
        assert r.code == 200
        assert json.loads(r.body)["size"] == size
        staged = self.get_temp_dir() / "lib" / ".tmp-upload-big" / "data.enc"
        assert staged.stat().st_size > size  # encrypted, so slightly larger than the plaintext


class TestReplay(Base):
    @tornado.testing.gen_test(timeout=60)
    async def test_replay_serves_through_proxy_and_streams_events(self):
        # Everything here is async on purpose: the replay proxy shares this event loop, so a
        # blocking call (time.sleep, subprocess.run, the synchronous self.fetch) would freeze it.
        import socket, subprocess
        import tornado.httpclient
        import tornado.websocket

        async def call(method, path, body=None, raw=None):
            return await self.http_client.fetch(
                self.get_url(path), method=method, headers=self.cookie(), raise_error=False,
                body=raw if raw is not None else (json.dumps(body) if body is not None else None))

        await call("POST", "/api/vault/create", {"passphrase": "passphrase-123"})
        await call("PUT", "/api/uploads/u1?name=h.xml", raw=XML)
        sid = json.loads((await call("POST", "/api/snapshots", {"name": "s", "uploads": ["u1"]})).body)["id"]
        ws = await tornado.websocket.websocket_connect(tornado.httpclient.HTTPRequest(
            self.get_url("/api/events").replace("http", "ws", 1), headers=self.cookie()))
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
        assert (await call("POST", "/api/replay", {"snapshot_id": sid, "port": port})).code == 200
        ca = self.get_temp_dir() / "conf" / "mitmproxy-ca-cert.pem"
        out = await asyncio.to_thread(
            subprocess.run,
            ["curl", "-s", "-x", f"http://127.0.0.1:{port}", "--cacert", str(ca), "https://shop.invalid/p"],
            capture_output=True, timeout=30)
        assert out.stdout == b"hi"
        seen = []
        while not any(e.get("type") == "request" for e in seen):
            seen.append(json.loads(await ws.read_message()))
        assert [e for e in seen if e["type"] == "request"][0]["tier"] == "EXACT"
        await call("DELETE", "/api/replay")
        ws.close()

    @tornado.testing.gen_test(timeout=60)
    async def test_start_queued_behind_lock_does_not_outlive_the_lock(self):
        # The nasty interleaving: Lock is already waiting for the session when a Start (which
        # passed its "unlocked" check earlier) queues up behind it. Held open deterministically
        # by holding the session's own lock.
        import socket

        async def call(method, path, body=None, raw=None):
            return await self.http_client.fetch(
                self.get_url(path), method=method, headers=self.cookie(), raise_error=False,
                body=raw if raw is not None else (json.dumps(body) if body is not None else None))

        await call("POST", "/api/vault/create", {"passphrase": "passphrase-123"})
        await call("PUT", "/api/uploads/u1?name=h.xml", raw=XML)
        sid = json.loads((await call("POST", "/api/snapshots", {"name": "s", "uploads": ["u1"]})).body)["id"]
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
        await self.session._lock.acquire()  # a start/stop is "in progress"
        lock_request = asyncio.ensure_future(call("POST", "/api/vault/lock", raw=""))
        await asyncio.sleep(0.2)  # the lock request is now waiting for the session
        start_request = asyncio.ensure_future(call("POST", "/api/replay", {"snapshot_id": sid, "port": port}))
        await asyncio.sleep(0.2)  # the replay request passed its checks and queued behind it
        self.session._lock.release()
        _, start_response = await asyncio.gather(lock_request, start_request)
        assert start_response.code == 423
        assert self.library.state == "locked"
        assert self.session.state["running"] is False
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=2).close()


class TestStatic(Base):
    def get_app(self):
        self.library = Library(self.get_temp_dir() / "lib")
        self.session = ReplaySession(confdir=self.get_temp_dir() / "conf")
        static = self.get_temp_dir() / "static"
        (static / "assets").mkdir(parents=True)
        (static / "index.html").write_text("<!doctype html><title>burpweb</title>")
        (static / "assets" / "app.js").write_text("console.log(1)")
        return make_app(self.library, self.session, TOKEN, static_dir=str(static))

    def test_index_needs_the_token_but_assets_do_not_leak_data(self):
        assert self.fetch("/", headers={"Host": "127.0.0.1"}).code == 403
        page = self.fetch("/", headers=self.cookie())
        assert page.code == 200 and b"<title>burpweb</title>" in page.body
        asset = self.fetch("/static/assets/app.js", headers={"Host": "127.0.0.1"})
        assert asset.code == 200 and asset.body == b"console.log(1)"


class TestHardening(Base):
    PASS = "correct horse battery"

    def unlock(self):
        assert self.api("POST", "/api/vault/create", {"passphrase": self.PASS}).code == 200

    def test_cross_origin_writes_are_refused_before_they_act(self):
        for origin in ("http://127.0.0.1:9999", "http://evil.example", "null"):
            r = self.api("POST", "/api/vault/create", {"passphrase": self.PASS}, headers={"Origin": origin})
            assert r.code == 403, origin
        assert self.library.state == "new"  # none of them created the vault

    def test_same_origin_and_originless_writes_still_work(self):
        r = self.api("POST", "/api/vault/create", {"passphrase": self.PASS}, headers={"Origin": "http://127.0.0.1"})
        assert r.code == 200
        assert self.api("POST", "/api/vault/lock", headers={"Origin": "http://127.0.0.1"}).code == 200

    def test_cross_origin_upload_is_refused(self):
        self.unlock()
        r = self.api("PUT", "/api/uploads/abc", None, headers={"Origin": "http://127.0.0.1:9999"})
        assert r.code == 403

    def test_a_non_ascii_token_is_a_403_not_a_crash(self):
        r = self.fetch("/?token=%C3%A9", headers={"Host": "127.0.0.1"}, follow_redirects=False)
        assert r.code == 403
        r = self.fetch("/api/state", headers={"Cookie": "bw_token=é".encode("utf-8"), "Host": "127.0.0.1"})
        assert r.code == 403

    def test_malformed_json_is_a_400(self):
        for body in (b"{not json", b"[1, 2]", b'"text"', b"\xff\xfe"):
            r = self.fetch("/api/vault/unlock", method="POST", body=body, headers=self.cookie())
            assert r.code == 400, body

    def test_missing_or_mistyped_fields_are_a_400_not_a_500(self):
        self.unlock()
        assert self.api("POST", "/api/snapshots", {"uploads": []}).code == 400  # no name
        assert self.api("POST", "/api/snapshots", {"name": "x"}).code == 400  # no uploads
        assert self.api("POST", "/api/snapshots", {"name": "x", "uploads": "abc"}).code == 400
        assert self.api("PATCH", "/api/snapshots/abc123", {}).code == 400
        assert self.api("POST", "/api/replay", {}).code == 400
        assert self.api("POST", "/api/replay", {"snapshot_id": "../etc"}).code == 400
        assert self.api("POST", "/api/replay", {"snapshot_id": "abc123", "port": "http"}).code == 400
        assert self.api("POST", "/api/replay", {"snapshot_id": "abc123", "port": 70000}).code == 400

    def test_a_snapshot_that_does_not_exist_is_a_404(self):
        self.unlock()
        assert self.api("PATCH", "/api/snapshots/abc123", {"name": "x"}).code == 404
        assert self.api("POST", "/api/snapshots/abc123/files", {"uploads": []}).code == 404
        assert self.api("POST", "/api/replay", {"snapshot_id": "abc123"}).code == 404


class TestOffload(Base):
    """Slow library work (scrypt, snapshot create) must not freeze the loop the replay and feed share."""

    PASS = "correct horse battery"

    def setUp(self):
        super().setUp()
        self.library.create_vault(self.PASS)

    async def _state_answers_while(self, method, path, body=None):
        import asyncio
        from tornado.httpclient import AsyncHTTPClient
        client = AsyncHTTPClient()
        slow = asyncio.ensure_future(client.fetch(
            self.get_url(path), method=method, headers=self.cookie(),
            body=json.dumps(body) if body is not None else None, raise_error=False))
        await asyncio.sleep(0.15)
        r = await client.fetch(self.get_url("/api/state"), headers=self.cookie())
        assert r.code == 200
        still_running = not slow.done()
        return still_running, await slow

    @tornado.testing.gen_test
    async def test_a_slow_list_does_not_block_other_requests(self):
        import time
        self.library.list = lambda: time.sleep(0.8) or []
        still_running, res = await self._state_answers_while("GET", "/api/snapshots")
        assert still_running and res.code == 200

    @tornado.testing.gen_test
    async def test_a_slow_unlock_does_not_block_other_requests(self):
        import time
        self.library.lock()
        self.library.unlock = lambda pw: time.sleep(0.8) or True
        still_running, res = await self._state_answers_while("POST", "/api/vault/unlock", {"passphrase": self.PASS})
        assert still_running and res.code == 200

    @tornado.testing.gen_test
    async def test_locking_during_slow_work_is_a_423_not_a_500(self):
        import time
        from burpweb.library import LibraryLocked

        def slow_then_locked():
            time.sleep(0.2)
            raise LibraryLocked("library is locked")
        self.library.list = slow_then_locked
        _, res = await self._state_answers_while("GET", "/api/snapshots")
        assert res.code == 423
