# burpweb UI Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend for the burpweb control page: an encrypted snapshot library, a replay-session manager, and a local Tornado server with a JSON API and a WebSocket feed. No frontend in this plan.

**Architecture:** One asyncio loop shared by Tornado and mitmproxy. `vault.py` does chunked AES-256-GCM. `library.py` stores encrypted snapshots and loads them into records via the existing `load_many`. `session.py` runs one replay at a time and fans `Replay` events to subscribers. `webapp.py` is the Tornado app with token+Host auth, streamed uploads and the feed.

**Tech Stack:** Python ≥ 3.12, mitmproxy 12.2, tornado 6.5, cryptography 48, pytest. All already installed.

**Spec:** `docs/superpowers/specs/2026-10-15-burpweb-ui-design.md`

## Global Constraints

- The control server and replay proxy bind to `127.0.0.1` only.
- Replay options stay exactly as the engine uses them: `connection_strategy="lazy"`, `upstream_cert=False`, `http3=False`, `rawtcp=False`, plus `Replay.server_connect` blocking upstream. Verified: repeated start/stop/restart of a mitmproxy `Master` in one process works, and a busy port surfaces as `ServerInstance.last_exception` (OSError 98) rather than killing the process.
- The library lives in `~/.local/share/burpweb/library/`, directories `0700`, files `0600`.
- scrypt parameters: `n=2**17, r=8, p=1`, 32-byte key (~0.8s per derivation, measured).
- Plaintext from exports or uploads is never written to disk — only encrypted bytes are.
- `vault.py` and `library.py` must not import tornado or mitmproxy.
- Tests use `tmp_path` for the library root and `.invalid` hosts for any replay; they never touch `~/.local/share/burpweb` or `~/.mitmproxy`.

## Review Focus

1. **A snapshot file corrupted or tampered on disk** (flipped byte, swapped chunk, truncated final chunk) must be detected, reported as damaged, and must not crash the library or block other snapshots. Pinned by `test_detects_tampering` (Task 1) and `test_damaged_snapshot_isolated` (Task 2).
2. **A crash mid-upload or mid-create** must leave no half-written snapshot and no readable plaintext. Pinned by `test_incomplete_snapshot_not_listed` and `test_no_plaintext_on_disk` (Task 2).
3. **Replay start on a busy port** must become a toast + `running:false`, never hang or kill the server. Pinned by `test_busy_port_reports_without_crashing` (Task 3).
4. **A request without the token, or with a foreign Host header**, must get 403 before reaching any library code. Pinned by `test_requires_token` and `test_rejects_foreign_host` (Task 4).
5. **Uploading invalid XML** must return 422 with the base64 hint and delete the staged ciphertext. Pinned by `test_invalid_upload_rejected_and_cleaned` (Task 4).

## File Structure

```
src/burpweb/vault.py          # Vault: derive, encrypt_stream, decrypt_stream, verify
src/burpweb/library.py        # Library, Snapshot, LibraryLocked, SnapshotDamaged
src/burpweb/session.py        # ReplaySession
src/burpweb/webapp.py         # make_app(), handlers
src/burpweb/cli.py            # add `ui` subcommand (default)
tests/test_vault.py
tests/test_library.py
tests/test_session.py
tests/test_webapp.py
```

---

### Task 1: Vault (chunked authenticated encryption)

**Files:**
- Create: `src/burpweb/vault.py`
- Test: `tests/test_vault.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - `burpweb.vault.CHUNK = 4 * 1024 * 1024`
  - `burpweb.vault.derive_key(passphrase: str, salt: bytes, *, n=2**17, r=8, p=1) -> bytes` (32 bytes)
  - `burpweb.vault.StreamEncryptor(key, *, snapshot_id, label, chunk_size=CHUNK)` with `.feed(data: bytes) -> bytes` and `.finish() -> bytes` — incremental encryption for streamed uploads; concatenating every `feed` result plus `finish()` yields one valid blob
  - `burpweb.vault.encrypt_stream(key: bytes, plaintext: Iterable[bytes], *, snapshot_id: str, label: str, chunk_size: int = CHUNK) -> Iterator[bytes]` — yields the `BWV1` header then length-prefixed GCM chunks (built on `StreamEncryptor`)
  - `burpweb.vault.decrypt_stream(key: bytes, ciphertext: Iterable[bytes], *, snapshot_id: str, label: str) -> Iterator[bytes]` — raises `vault.BadData` on any authentication or structural failure
  - `burpweb.vault.encrypt_bytes(...) -> bytes` and `decrypt_bytes(...) -> bytes` (whole-value convenience over the stream functions)
  - `burpweb.vault.BadData(Exception)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_vault.py
import os
import pytest
from burpweb import vault

KEY = b"k" * 32


def enc(data, chunk=vault.CHUNK, sid="snap1", label="0"):
    return vault.encrypt_bytes(KEY, data, snapshot_id=sid, label=label, chunk_size=chunk)


def dec(blob, sid="snap1", label="0", key=KEY):
    return vault.decrypt_bytes(key, blob, snapshot_id=sid, label=label)


@pytest.mark.parametrize("size", [0, 10, vault.CHUNK, vault.CHUNK + 1, 3 * vault.CHUNK + 7])
def test_round_trip(size):
    data = os.urandom(size)
    assert dec(enc(data, chunk=4096 if size else vault.CHUNK)) == data


def test_small_chunk_multichunk_round_trip():
    data = os.urandom(10000)
    blob = enc(data, chunk=1024)
    assert blob.startswith(b"BWV1")
    assert dec(blob) == data


def test_derive_key_is_deterministic_and_salt_sensitive():
    salt = os.urandom(16)
    assert vault.derive_key("pw", salt, n=2**14) == vault.derive_key("pw", salt, n=2**14)
    assert vault.derive_key("pw", salt, n=2**14) != vault.derive_key("pw", os.urandom(16), n=2**14)


def test_wrong_key_rejected():
    with pytest.raises(vault.BadData):
        dec(enc(b"secret"), key=b"x" * 32)


def test_detects_flipped_bit():
    blob = bytearray(enc(b"secret payload", chunk=1024))
    blob[-1] ^= 1
    with pytest.raises(vault.BadData):
        dec(bytes(blob))


def test_detects_wrong_label_or_snapshot():
    blob = enc(b"secret", sid="snap1", label="0")
    with pytest.raises(vault.BadData):
        dec(blob, sid="snap1", label="1")
    with pytest.raises(vault.BadData):
        dec(blob, sid="OTHER", label="0")


def test_detects_truncated_final_chunk():
    # Drop the last chunk: decryption must not accept a short file as complete.
    data = os.urandom(5000)
    blob = enc(data, chunk=1024)
    # find the start of the last chunk by re-encrypting header-only length framing is complex;
    # instead truncate inside the last chunk's region.
    truncated = blob[: len(blob) - 1100]
    with pytest.raises(vault.BadData):
        dec(truncated)


def test_detects_swapped_chunks():
    # Two chunks of equal ciphertext length; swapping them must fail AAD (chunk index).
    data = b"A" * 1024 + b"B" * 1024 + b"C" * 10
    blob = enc(data, chunk=1024)
    body = blob[len(b"BWV1") + 8 :]
    # each full chunk framing = 4 (len) + 1024 + 16 (tag)
    frame = 4 + 1024 + 16
    c0, c1 = body[:frame], body[frame : 2 * frame]
    swapped = blob[: len(b"BWV1") + 8] + c1 + c0 + body[2 * frame :]
    with pytest.raises(vault.BadData):
        dec(swapped)


def test_stream_api_matches_bytes_api():
    data = os.urandom(9000)
    chunks = vault.encrypt_stream(KEY, [data[:3000], data[3000:]], snapshot_id="s", label="0", chunk_size=1024)
    blob = b"".join(chunks)
    assert b"".join(vault.decrypt_stream(KEY, [blob], snapshot_id="s", label="0")) == data


def test_stream_encryptor_incremental_round_trip():
    data = os.urandom(10_000)
    enc = vault.StreamEncryptor(KEY, snapshot_id="s", label="0", chunk_size=1024)
    blob = b"".join(enc.feed(data[i : i + 700]) for i in range(0, len(data), 700)) + enc.finish()
    assert vault.decrypt_bytes(KEY, blob, snapshot_id="s", label="0") == data


def test_stream_encryptor_empty_input():
    enc = vault.StreamEncryptor(KEY, snapshot_id="s", label="0")
    assert vault.decrypt_bytes(KEY, enc.finish(), snapshot_id="s", label="0") == b""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_vault.py -q`
Expected: `ModuleNotFoundError: No module named 'burpweb.vault'`

- [ ] **Step 3: Implement `src/burpweb/vault.py`**

```python
"""Chunked authenticated encryption for the snapshot library."""

from __future__ import annotations

import os
import struct
from collections.abc import Iterable, Iterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

CHUNK = 4 * 1024 * 1024
_MAGIC = b"BWV1"
_PREFIX_LEN = 8
_LEN = struct.Struct(">I")


class BadData(Exception):
    """Ciphertext failed authentication or was structurally invalid."""


def derive_key(passphrase: str, salt: bytes, *, n: int = 2**17, r: int = 8, p: int = 1) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


def _aad(snapshot_id: str, label: str, index: int, final: bool) -> bytes:
    return f"{snapshot_id}/{label}/{index}/{int(final)}".encode("utf-8")


class StreamEncryptor:
    """Incremental encryption: feed() plaintext as it arrives, then finish().

    The last chunk is sealed with final=1 in its AAD, so a chunk is only sealed as
    non-final once more data is known to follow it. Plaintext never leaves memory
    unencrypted, and memory use is bounded by one chunk.
    """

    def __init__(self, key: bytes, *, snapshot_id: str, label: str, chunk_size: int = CHUNK):
        self._aes = AESGCM(key)
        self._sid, self._label, self._size = snapshot_id, label, chunk_size
        self._prefix = os.urandom(_PREFIX_LEN)
        self._index = 0
        self._buf = bytearray()
        self._started = False

    def _header(self) -> bytes:
        if self._started:
            return b""
        self._started = True
        return _MAGIC + self._prefix

    def _seal(self, block: bytes, final: bool) -> bytes:
        nonce = self._prefix + _LEN.pack(self._index)
        ct = self._aes.encrypt(nonce, bytes(block), _aad(self._sid, self._label, self._index, final))
        self._index += 1
        return _LEN.pack(len(ct)) + ct

    def feed(self, data: bytes) -> bytes:
        self._buf += data
        out = bytearray(self._header())
        while len(self._buf) > self._size:  # strictly greater: the tail is held back for finish()
            out += self._seal(self._buf[: self._size], final=False)
            del self._buf[: self._size]
        return bytes(out)

    def finish(self) -> bytes:
        out = bytearray(self._header())
        out += self._seal(bytes(self._buf), final=True)
        self._buf.clear()
        return bytes(out)


def encrypt_stream(
    key: bytes,
    plaintext: Iterable[bytes],
    *,
    snapshot_id: str,
    label: str,
    chunk_size: int = CHUNK,
) -> Iterator[bytes]:
    enc = StreamEncryptor(key, snapshot_id=snapshot_id, label=label, chunk_size=chunk_size)
    for part in plaintext:
        out = enc.feed(part)
        if out:
            yield out
    yield enc.finish()


def decrypt_stream(
    key: bytes,
    ciphertext: Iterable[bytes],
    *,
    snapshot_id: str,
    label: str,
) -> Iterator[bytes]:
    aes = AESGCM(key)
    buf = bytearray()
    for part in ciphertext:
        buf += part
    if bytes(buf[:4]) != _MAGIC:
        raise BadData("bad magic")
    prefix = bytes(buf[4 : 4 + _PREFIX_LEN])
    pos = 4 + _PREFIX_LEN
    index = 0
    chunks: list[bytes] = []
    while pos < len(buf):
        if pos + 4 > len(buf):
            raise BadData("truncated length")
        (clen,) = _LEN.unpack(buf[pos : pos + 4])
        pos += 4
        ct = bytes(buf[pos : pos + clen])
        if len(ct) != clen:
            raise BadData("truncated chunk")
        pos += clen
        chunks.append(ct)
    if not chunks:
        raise BadData("no chunks")
    nonce_prefix = prefix
    out_final = len(chunks) - 1
    decoded = []
    for i, ct in enumerate(chunks):
        nonce = nonce_prefix + _LEN.pack(i)
        try:
            pt = aes.decrypt(nonce, ct, _aad(snapshot_id, label, i, i == out_final))
        except InvalidTag:
            raise BadData(f"authentication failed at chunk {i}") from None
        decoded.append(pt)
    yield from decoded


def encrypt_bytes(key: bytes, data: bytes, *, snapshot_id: str, label: str, chunk_size: int = CHUNK) -> bytes:
    return b"".join(encrypt_stream(key, [data], snapshot_id=snapshot_id, label=label, chunk_size=chunk_size))


def decrypt_bytes(key: bytes, blob: bytes, *, snapshot_id: str, label: str) -> bytes:
    return b"".join(decrypt_stream(key, [blob], snapshot_id=snapshot_id, label=label))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_vault.py -q`
Expected: all tests PASS.

Note: the `test_detects_truncated_final_chunk` case removes the last chunk's framing. Because the final chunk carries `final=1` in its AAD and the new last surviving chunk was encrypted with `final=0`, authentication fails — verify this holds; if truncation lands exactly on a chunk boundary, the "truncated chunk"/"truncated length" guards catch it instead. Either way it raises `BadData`.

- [ ] **Step 5: Commit**

```bash
git add src/burpweb/vault.py tests/test_vault.py
git commit -m "feat: chunked authenticated encryption vault"
```

---

### Task 2: Library (encrypted snapshot store)

**Files:**
- Create: `src/burpweb/library.py`
- Test: `tests/test_library.py`

**Interfaces:**
- Consumes: `vault`; `burpweb.burp_xml.load_many` (reused for validation/loading); `tests/burpfixtures.make_item`, `make_xml`
- Produces:
  - `burpweb.library.LibraryLocked(Exception)`, `burpweb.library.SnapshotDamaged(Exception)`
  - `burpweb.library.Snapshot`: dataclass `{id, name, created, files: list[dict], stats: dict, damaged: bool}` (`stats` = `{items, origins, skipped, malformed}`)
  - `burpweb.library.Library(root: Path)`:
    - `.state -> "new"|"locked"|"unlocked"`
    - `.create_vault(passphrase)`, `.unlock(passphrase) -> bool`, `.lock()`
    - `.list() -> list[Snapshot]`
    - `.create(name: str, sources: list[bytes | Iterable[bytes]], filenames: list[str]) -> Snapshot` (validates with `load_many`; raises `BurpXmlError`/`ValueError` on bad input)
    - `.add_files(id, sources, filenames) -> Snapshot`
    - `.rename(id, name) -> Snapshot`
    - `.delete(id)`
    - `.load_records(id) -> list[Record]` (raises `SnapshotDamaged`)
    - `.cleanup_temp()`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_library.py
import os
import stat
import pytest
from burpfixtures import make_item, make_xml
from burpweb.library import Library, LibraryLocked, SnapshotDamaged

OK = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nMARKER-BODY-9z"
REQ = b"GET /p HTTP/1.1\r\nHost: shop.invalid\r\n\r\n"
XML = make_xml([make_item(host="shop.invalid", request=REQ, response=OK)]).encode()


@pytest.fixture
def lib(tmp_path):
    lib = Library(tmp_path / "library")
    lib.create_vault("passphrase-123")
    return lib


def test_state_transitions(tmp_path):
    lib = Library(tmp_path / "lib")
    assert lib.state == "new"
    lib.create_vault("passphrase-123")
    assert lib.state == "unlocked"
    lib.lock()
    assert lib.state == "locked"
    assert lib.unlock("passphrase-123") is True
    assert lib.state == "unlocked"


def test_wrong_passphrase(tmp_path):
    lib = Library(tmp_path / "lib")
    lib.create_vault("passphrase-123")
    lib.lock()
    assert lib.unlock("nope") is False
    assert lib.state == "locked"


def test_locked_operations_raise(tmp_path):
    lib = Library(tmp_path / "lib")
    lib.create_vault("passphrase-123")
    lib.lock()
    with pytest.raises(LibraryLocked):
        lib.list()


def test_create_list_rename_delete(lib):
    snap = lib.create("Treasury", [XML], ["history.xml"])
    assert snap.name == "Treasury"
    assert snap.stats["items"] == 1
    assert [s.id for s in lib.list()] == [snap.id]
    lib.rename(snap.id, "Renamed")
    assert lib.list()[0].name == "Renamed"
    lib.delete(snap.id)
    assert lib.list() == []


def test_add_files_later_file_wins(lib):
    first = make_xml([make_item(host="shop.invalid", request=REQ,
                                response=b"HTTP/1.1 200 OK\r\n\r\nOLD")]).encode()
    second = make_xml([make_item(host="shop.invalid", request=REQ,
                                 response=b"HTTP/1.1 200 OK\r\n\r\nNEW")]).encode()
    snap = lib.create("s", [first], ["a.xml"])
    lib.add_files(snap.id, [second], ["b.xml"])
    recs = lib.load_records(snap.id)
    # last file wins on identical request
    assert recs[-1].response_body == b"NEW"
    assert [f["name"] for f in lib.list()[0].files] == ["a.xml", "b.xml"]


def test_invalid_xml_rejected(lib):
    with pytest.raises(Exception) as e:
        lib.create("bad", [b"<notburp/>"], ["x.xml"])
    assert "items" in str(e.value).lower() or "base64" in str(e.value).lower()
    assert lib.list() == []  # nothing persisted


def test_no_plaintext_on_disk(lib, tmp_path):
    lib.create("Treasury", [XML], ["secret-history.xml"])
    for dirpath, _dirs, files in os.walk(tmp_path):
        for name in files:
            blob = (tmp_path / dirpath / name).read_bytes()
            assert b"MARKER-BODY-9z" not in blob
            assert b"secret-history" not in blob
            assert b"shop.invalid" not in blob
        for d in _dirs:
            assert "secret-history" not in d


def test_incomplete_snapshot_not_listed(lib, tmp_path):
    # A leftover temp dir (simulating a crash mid-create) is ignored and cleaned.
    (tmp_path / "library" / ".tmp-deadbeef").mkdir()
    (tmp_path / "library" / ".tmp-deadbeef" / "files").mkdir()
    lib.cleanup_temp()
    assert not (tmp_path / "library" / ".tmp-deadbeef").exists()
    assert lib.list() == []


def test_damaged_snapshot_isolated(lib, tmp_path):
    good = lib.create("good", [XML], ["a.xml"])
    bad = lib.create("bad", [XML], ["b.xml"])
    # corrupt the bad snapshot's file 0
    f = tmp_path / "library" / bad.id / "files" / "0.enc"
    data = bytearray(f.read_bytes())
    data[-1] ^= 1
    f.write_bytes(bytes(data))
    listing = {s.id: s for s in lib.list()}
    assert listing[bad.id].damaged is True
    assert listing[good.id].damaged is False
    with pytest.raises(SnapshotDamaged):
        lib.load_records(bad.id)
    assert lib.load_records(good.id)  # good one still loads


def test_failed_add_keeps_existing_snapshot(lib):
    snap = lib.create("s", [XML], ["a.xml"])
    with pytest.raises(Exception):
        lib.add_files(snap.id, [b"<notburp/>"], ["b.xml"])
    assert lib.list()[0].stats["items"] == 1
    assert len(lib.load_records(snap.id)) == 1


def test_crash_between_swap_steps_restores_previous_version(lib, tmp_path):
    snap = lib.create("keep", [XML], ["a.xml"])
    root = tmp_path / "library"
    os.replace(root / snap.id, root / f".old-{snap.id}")  # simulate a crash mid-swap
    lib.cleanup_temp()
    assert [s.name for s in lib.list()] == ["keep"]


def test_permissions(lib, tmp_path):
    snap = lib.create("s", [XML], ["a.xml"])
    root = tmp_path / "library"
    assert stat.S_IMODE((root).stat().st_mode) == 0o700
    f = root / snap.id / "files" / "0.enc"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_library.py -q`
Expected: `ModuleNotFoundError: No module named 'burpweb.library'`

- [ ] **Step 3: Implement `src/burpweb/library.py`**

```python
"""Encrypted, on-disk snapshot library."""

from __future__ import annotations

import io
import json
import os
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from burpweb import vault
from burpweb.burp_xml import Record, load_many_streams

VAULT_FILE = "vault.json"
_CHECK = b"burpweb-vault-ok"


class LibraryLocked(Exception):
    pass


class SnapshotDamaged(Exception):
    pass


@dataclass
class Snapshot:
    id: str
    name: str
    created: str
    files: list[dict]
    stats: dict
    damaged: bool = False


class Library:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._key: bytes | None = None

    # ---- vault lifecycle ----
    @property
    def state(self) -> str:
        if not (self.root / VAULT_FILE).exists():
            return "new"
        return "unlocked" if self._key is not None else "locked"

    def create_vault(self, passphrase: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        salt = os.urandom(16)
        key = vault.derive_key(passphrase, salt)
        check = vault.encrypt_bytes(key, _CHECK, snapshot_id="vault", label="check")
        self._write(self.root / VAULT_FILE, json.dumps({
            "version": 1, "kdf": "scrypt", "n": 2**17, "r": 8, "p": 1,
            "salt": salt.hex(), "check": check.hex(),
        }).encode())
        self._key = key
        self.cleanup_temp()

    def unlock(self, passphrase: str) -> bool:
        meta = json.loads((self.root / VAULT_FILE).read_text())
        key = vault.derive_key(passphrase, bytes.fromhex(meta["salt"]),
                               n=meta["n"], r=meta["r"], p=meta["p"])
        try:
            if vault.decrypt_bytes(key, bytes.fromhex(meta["check"]),
                                   snapshot_id="vault", label="check") != _CHECK:
                return False
        except vault.BadData:
            return False
        self._key = key
        self.cleanup_temp()
        return True

    def lock(self) -> None:
        self._key = None

    # ---- snapshots ----
    def _require_key(self) -> bytes:
        if self._key is None:
            raise LibraryLocked("library is locked")
        return self._key

    def list(self) -> list[Snapshot]:
        key = self._require_key()
        out = []
        for d in sorted(self.root.glob("*")):
            if not d.is_dir() or d.name.startswith("."):
                continue
            out.append(self._read_snapshot(key, d))
        out.sort(key=lambda s: s.created)
        return out

    def _read_snapshot(self, key: bytes, d: Path) -> Snapshot:
        try:
            meta = json.loads(vault.decrypt_bytes(
                key, (d / "meta.enc").read_bytes(), snapshot_id=d.name, label="meta"))
            return Snapshot(id=d.name, **meta, damaged=False)
        except (vault.BadData, OSError, ValueError, TypeError):
            return Snapshot(id=d.name, name="(damaged)", created="", files=[], stats={}, damaged=True)

    def create(self, name, sources, filenames):
        return self._write_snapshot(secrets.token_hex(8), name, list(sources), list(filenames), existing=None)

    def add_files(self, sid, sources, filenames):
        key = self._require_key()
        snap = self._read_snapshot(key, self.root / sid)
        if snap.damaged:
            raise SnapshotDamaged(sid)
        return self._write_snapshot(sid, snap.name, list(sources), list(filenames), existing=snap)

    def _write_snapshot(self, sid, name, sources, filenames, existing):
        key = self._require_key()
        base_index = len(existing.files) if existing else 0
        materialized = [s if isinstance(s, (bytes, bytearray)) else b"".join(s) for s in sources]
        # Validate everything (old + new) before persisting.
        try:
            old_streams = ([self._decrypt_file(key, sid, i, f["name"]) for i, f in enumerate(existing.files)]
                           if existing else [])
        except vault.BadData:
            raise SnapshotDamaged(sid) from None
        result = load_many_streams(old_streams + [(fn, io.BytesIO(m)) for fn, m in zip(filenames, materialized)])
        if not result.records:
            from burpweb.burp_xml import BurpXmlError
            raise BurpXmlError("no usable items in the uploaded export(s)")

        tmp = self.root / f".tmp-{sid}"
        shutil.rmtree(tmp, ignore_errors=True)
        (tmp / "files").mkdir(parents=True)
        os.chmod(tmp, 0o700)
        if existing:  # copy existing encrypted files unchanged
            for i in range(len(existing.files)):
                shutil.copy2(self.root / sid / "files" / f"{i}.enc", tmp / "files" / f"{i}.enc")
        for offset, m in enumerate(materialized):
            self._write(tmp / "files" / f"{base_index + offset}.enc",
                        vault.encrypt_bytes(key, m, snapshot_id=sid, label=str(base_index + offset)))
        files = (existing.files if existing else []) + [
            {"name": fn, "size": len(m)} for fn, m in zip(filenames, materialized)]
        created = existing.created if existing else datetime.now(timezone.utc).isoformat()
        stats = {"items": len(result.records),
                 "origins": len({r.origin for r in result.records}),
                 "skipped": result.skipped_no_response,
                 "malformed": result.malformed}
        meta = {"name": name, "created": created, "files": files, "stats": stats}
        self._write(tmp / "meta.enc",
                    vault.encrypt_bytes(key, json.dumps(meta).encode(), snapshot_id=sid, label="meta"))
        dest = self.root / sid
        old = self.root / f".old-{sid}"
        shutil.rmtree(old, ignore_errors=True)
        if dest.exists():
            os.replace(dest, old)  # keep the previous version until the new one is in place
        os.replace(tmp, dest)
        shutil.rmtree(old, ignore_errors=True)
        return Snapshot(id=sid, name=name, created=created, files=files, stats=stats)

    def rename(self, sid, name):
        key = self._require_key()
        snap = self._read_snapshot(key, self.root / sid)
        if snap.damaged:
            raise SnapshotDamaged(sid)
        meta = {"name": name, "created": snap.created, "files": snap.files, "stats": snap.stats}
        self._write_atomic(self.root / sid / "meta.enc",
                           vault.encrypt_bytes(key, json.dumps(meta).encode(), snapshot_id=sid, label="meta"))
        snap.name = name
        return snap

    def delete(self, sid):
        shutil.rmtree(self.root / sid, ignore_errors=True)

    def _decrypt_file(self, key, sid, index, name):
        blob = (self.root / sid / "files" / f"{index}.enc").read_bytes()
        return (name, io.BytesIO(vault.decrypt_bytes(key, blob, snapshot_id=sid, label=str(index))))

    def load_records(self, sid) -> list[Record]:
        key = self._require_key()
        snap = self._read_snapshot(key, self.root / sid)
        if snap.damaged:
            raise SnapshotDamaged(sid)
        try:
            streams = [self._decrypt_file(key, sid, i, f["name"]) for i, f in enumerate(snap.files)]
        except vault.BadData:
            raise SnapshotDamaged(sid) from None
        return load_many_streams(streams).records

    def cleanup_temp(self):
        for d in self.root.glob(".tmp-*"):
            shutil.rmtree(d, ignore_errors=True)
        for d in self.root.glob(".old-*"):
            sid = d.name[len(".old-"):]
            if (self.root / sid).exists():
                shutil.rmtree(d, ignore_errors=True)
            else:  # crashed between the two renames: restore the previous version
                os.replace(d, self.root / sid)

    # ---- disk helpers ----
    @staticmethod
    def _write(path: Path, data: bytes):
        path.write_bytes(data)
        os.chmod(path, 0o600)

    def _write_atomic(self, path: Path, data: bytes):
        tmp = path.with_suffix(path.suffix + ".tmp")
        self._write(tmp, data)
        os.replace(tmp, path)
```

- [ ] **Step 4: Add `load_many_streams` to `burp_xml.py`**

`load_many` currently takes file paths. Refactor so both paths and in-memory streams share one implementation. In `src/burpweb/burp_xml.py`:

```python
def load_stream(source, name: str = "") -> LoadResult:
    """Like load(), but `source` may be a path or a binary file object."""
    # move the body of load() here, operating on `source` (ET.iterparse accepts both),
    # keeping the same BurpXmlError messages (use `name or source` in text).

def load(path): 
    return load_stream(path, name=str(path))

def load_many(paths):
    return load_many_streams([(Path(p).name, p) for p in paths])

def load_many_streams(items: list[tuple[str, object]]) -> LoadResult:
    """items: (display_name, path-or-stream). Combines in order; later items win."""
    combined = LoadResult()
    tag = len(items) > 1
    for name, source in items:
        result = load_stream(source, name=name)
        combined.records += [replace(r, source=name) for r in result.records] if tag else result.records
        combined.skipped_no_response += result.skipped_no_response
        combined.malformed += [(i, f"{r} (in {name})" if tag else r) for i, r in result.malformed]
    return combined
```

Keep `test_burp_xml.py` green — the existing `load`/`load_many` behavior and messages must not change. Run `uv run pytest tests/test_burp_xml.py -q` after this step.

- [ ] **Step 5: Run the library tests to verify they pass**

Run: `uv run pytest tests/test_library.py tests/test_burp_xml.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/burpweb/library.py src/burpweb/burp_xml.py tests/test_library.py
git commit -m "feat: encrypted snapshot library"
```

---

### Task 3: Replay session + addon event callback

**Files:**
- Modify: `src/burpweb/addon.py` (add an `on_event` callback), `tests/test_addon.py` (one new test)
- Create: `src/burpweb/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `Replay`, `Matcher`, `burp_xml.Record`, `browser.FirefoxLauncher`
- Produces:
  - `Replay(matcher, out=None, on_event: Callable[[dict], None] | None = None)` — in addition to printing, calls `on_event` with `{type:"request", tier, method, url, status, item}` per request, `{type:"misses", misses:[{key, count}]}` right after each MISS, and `{type:"blocked", address}` on an upstream block. Printed output is unchanged.
  - `burpweb.session.ReplaySession(confdir: Path)`:
    - `async start(records, port) -> None` (raises `ReplayStartError` with the message on bind failure)
    - `async stop() -> None`
    - `open_browser(start_url) -> None` (delegates to `FirefoxLauncher.running`)
    - `.state -> {"running": bool, "port": int|None}`
    - `.subscribe(cb)` / `.unsubscribe(cb)` for event dicts; also forwards `{type:"misses",...}`
  - `burpweb.session.ReplayStartError(Exception)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_session.py
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
```

The tests are plain `async def` functions; they run under `pytest-asyncio` in auto mode (installed in Step 2), so they need no markers or backend fixtures.

- [ ] **Step 2: Install the async test plugin**

Run: `uv add --dev pytest-asyncio`, then merge this into the existing `[tool.pytest.ini_options]` table in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

Run: `uv run pytest tests/test_session.py -q`
Expected: fails to import `burpweb.session`.

- [ ] **Step 3: Add `on_event` to `Replay` (`src/burpweb/addon.py`)**

In `__init__` add `on_event=None` and store it. In `request()`, after computing the matched result, call the callback. Factor the emit into the existing `_log` path so both stay in sync:

```python
    def __init__(self, matcher, out=None, on_event=None):
        ...
        self.on_event = on_event

    # in request(), replace the two self._log(...) calls' surroundings so that
    # after determining (tier, method, url, status, item) we also do:
    #     if self.on_event:
    #         self.on_event({"type": "request", "tier": tier.value, "method": method, "url": url,
    #                        "status": status, "item": item})
    #     and, only for a MISS, right after that event:
    #         self.on_event({"type": "misses",
    #                        "misses": [{"key": k, "count": c} for k, c in self.misses.most_common()]})
    # For the server_connect block:
    def server_connect(self, data):
        host, port = data.server.address or ("?", 0)
        data.server.error = "burpweb never connects upstream"
        print(f"{'BLOCKED':<8} upstream connection to {host}:{port}", file=self.out, flush=True)
        if self.on_event:
            self.on_event({"type": "blocked", "address": f"{host}:{port}"})
```

First add this test to `tests/test_addon.py` and watch it fail:

```python
def test_on_event_reports_requests_and_misses():
    events = []
    addon = Replay(Matcher([make_record(1, path="/a")]), out=io.StringIO(), on_event=events.append)
    addon.request(flow("GET", "https://example.com/a"))
    addon.request(flow("GET", "https://example.com/zzz"))
    assert [e["type"] for e in events] == ["request", "request", "misses"]
    assert events[0]["tier"] == "EXACT" and events[1]["tier"] == "MISS"
    assert events[2]["misses"] == [{"key": "GET https://example.com/zzz", "count": 1}]
```

Then implement it, keeping every existing assertion green (printed lines are unchanged). Run `uv run pytest tests/test_addon.py -q`.

- [ ] **Step 4: Implement `src/burpweb/session.py`**

```python
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
        master.options.update(connection_strategy="lazy", upstream_cert=False,
                              http3=False, rawtcp=False, termlog_verbosity="warn")
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
        master.shutdown()
        await task
        self._emit({"type": "replay", "running": False, "port": None})

    def open_browser(self, start_url):
        launcher = FirefoxLauncher(port=self._port, confdir=self.confdir, start_url=start_url)
        launcher.running()
        return launcher
```

- [ ] **Step 5: Run the session tests to verify they pass**

Run: `uv run pytest tests/test_session.py tests/test_addon.py -q`
Expected: all PASS. (The `.invalid` hosts guarantee nothing reaches a real server.)

- [ ] **Step 6: Commit**

```bash
git add src/burpweb/session.py src/burpweb/addon.py tests/test_session.py tests/test_addon.py pyproject.toml uv.lock
git commit -m "feat: replay session manager with event subscriptions"
```

---

### Task 4: Tornado control server + `ui` CLI command

**Files:**
- Create: `src/burpweb/webapp.py`
- Modify: `src/burpweb/cli.py` (add `ui`, make it the default command)
- Test: `tests/test_webapp.py`

**Interfaces:**
- Consumes: `Library`, `ReplaySession`, `burp_xml.BurpXmlError`
- Produces:
  - `burpweb.webapp.make_app(library, session, token, *, static_dir=None) -> tornado.web.Application`
  - `burpweb.webapp.run(host="127.0.0.1", port=8080, open_browser=True)` — binds `[port, port+20]`, prints the URL, runs the IOLoop
  - CLI: `burpweb` (no args) and `burpweb ui` start the server.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_webapp.py
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
        if method in ("GET", "DELETE") and body is None:
            kw.pop("body", None)
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

    def test_invalid_upload_rejected_and_cleaned(self):
        self.api("POST", "/api/vault/create", {"passphrase": "passphrase-123"})
        self.fetch("/api/uploads/u2?name=bad.xml", method="PUT",
                   body=b'<?xml version="1.0"?><items><item><response base64="false">\x01</response></item></items>',
                   headers=self.cookie())
        r = self.api("POST", "/api/snapshots", {"name": "bad", "uploads": ["u2"]})
        assert r.code == 422
        assert b"Base64" in r.body or b"base64" in r.body
        assert json.loads(self.api("GET", "/api/snapshots").body) == []


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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_webapp.py -q`
Expected: fails to import `burpweb.webapp`.

- [ ] **Step 3: Implement `src/burpweb/webapp.py`**

```python
"""Local Tornado control server for the burpweb UI."""

from __future__ import annotations

import asyncio
import json
import os
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


class _Base(tornado.web.RequestHandler):
    def initialize(self, app_state):
        self.app_state = app_state

    def prepare(self):
        host = (self.request.host or "").split(":")[0]
        if host not in ALLOWED_HOSTS_SUFFIX:
            self.set_status(403)
            self.finish({"error": "forbidden host"})
            return
        if self.get_cookie("bw_token") != self.app_state["token"]:
            self.set_status(403)
            self.finish({"error": "missing or bad token"})
            return

    def write_error(self, status_code, **kwargs):
        self.finish({"error": self._reason})

    @property
    def library(self) -> Library:
        return self.app_state["library"]

    @property
    def session(self) -> ReplaySession:
        return self.app_state["session"]

    def json_body(self):
        return json.loads(self.request.body or b"{}")

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
        if self.get_argument("token", None) == self.app_state["token"]:
            self.set_cookie("bw_token", self.app_state["token"],
                            httponly=True, samesite="Strict", path="/")
            self.redirect("/")
            return
        if self.get_cookie("bw_token") == self.app_state["token"]:
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
        self.finish({"vault": self.library.state, "replay": self.session.state})


class VaultHandler(_Base):
    def post(self, action):
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
            asyncio.ensure_future(self.session.stop())
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
        uploads = self.app_state["uploads"]
        try:
            sources, names = _claim(uploads, body["uploads"], self.library)
        except KeyError:
            self.set_status(400); self.finish({"error": "unknown upload id"}); return
        try:
            snap = self.library.create(body["name"], sources, names)
        except (BurpXmlError, ValueError) as e:
            _drop(uploads, body["uploads"])
            self.set_status(422); self.finish({"error": str(e)}); return
        _drop(uploads, body["uploads"])
        self.finish(vars(snap))


class SnapshotHandler(_Base):
    def patch(self, sid):
        if not self.require_unlocked():
            return
        try:
            snap = self.library.rename(sid, self.json_body()["name"])
        except SnapshotDamaged:
            self.set_status(409); self.finish({"error": "snapshot damaged"}); return
        self.finish(vars(snap))

    def delete(self, sid):
        if not self.require_unlocked():
            return
        if self.session.state["running"] and self.app_state.get("replay_sid") == sid:
            asyncio.ensure_future(self.session.stop())
        self.library.delete(sid)
        self.set_status(204); self.finish()

    def post(self, sid):  # add files
        if not self.require_unlocked():
            return
        body = self.json_body()
        uploads = self.app_state["uploads"]
        sources, names = _claim(uploads, body["uploads"], self.library)
        try:
            snap = self.library.add_files(sid, sources, names)
        except SnapshotDamaged:
            _drop(uploads, body["uploads"])
            self.set_status(409); self.finish({"error": "snapshot damaged"}); return
        except (BurpXmlError, ValueError) as e:
            _drop(uploads, body["uploads"])
            self.set_status(422); self.finish({"error": str(e)}); return
        _drop(uploads, body["uploads"])
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
        if self._finished or not self.require_unlocked():
            return
        self.upload_id = self.path_args[0]
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
        name = self.get_argument("name", "upload.xml")
        self.app_state["uploads"][upload_id] = {"name": name, "path": self.tmp, "size": self.size}
        self.finish({"upload_id": upload_id, "size": self.size})

    def on_connection_close(self):
        out = getattr(self, "out", None)
        if out is not None and not out.closed:  # client went away mid-upload
            out.close()
            shutil.rmtree(self.tmp, ignore_errors=True)


class ReplayHandler(_Base):
    async def post(self):
        if not self.require_unlocked():
            return
        body = self.json_body()
        sid = body["snapshot_id"]
        port = int(body.get("port") or 8081)
        try:
            records = self.library.load_records(sid)
        except SnapshotDamaged:
            self.set_status(409); self.finish({"error": "snapshot damaged"}); return
        try:
            await self.session.start(records, port)
        except ReplayStartError as e:
            self.set_status(409); self.finish({"error": str(e)}); return
        self.app_state["replay_sid"] = sid
        self.app_state["replay_url"] = records[0].url if records else "https://localhost/"
        self.finish({"snapshot_id": sid, "port": port, "running": True})

    async def delete(self):
        await self.session.stop()
        self.set_status(204); self.finish()


class BrowserHandler(_Base):
    def post(self):
        if not self.session.state["running"]:
            self.set_status(409); self.finish({"error": "no replay running"}); return
        launcher = self.session.open_browser(self.app_state["replay_url"])
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
        if host not in ALLOWED_HOSTS_SUFFIX or self.get_cookie("bw_token") != self.app_state["token"]:
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


def make_app(library, session, token, *, static_dir=None):
    state = {"library": library, "session": session, "token": token,
             "uploads": {}, "static_dir": static_dir, "replay_sid": None, "replay_url": None}
    kw = {"app_state": state}
    routes = [
        (r"/", TokenHandler, kw),
        (r"/api/state", StateHandler, kw),
        (r"/api/vault/(create|unlock|lock)", VaultHandler, kw),
        (r"/api/snapshots", SnapshotsHandler, kw),
        (r"/api/snapshots/([0-9a-f]+)", SnapshotHandler, kw),
        (r"/api/snapshots/([0-9a-f]+)/files", SnapshotHandler, kw),
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


def run(host="127.0.0.1", port=8080, open_browser=True, static_dir=None):
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
            library.lock()

    asyncio.run(serve_forever())
```

- [ ] **Step 4: Wire the `ui` command in `cli.py`**

Make `ui` the default subcommand. First add this test to `tests/test_cli.py` and watch it fail:

```python
def test_bare_command_defaults_to_ui():
    from burpweb.cli import build_parser
    args = build_parser().parse_args([])
    assert (args.command, args.port, args.no_open) == ("ui", 8080, False)
```

Then make the subparsers optional (`sub = parser.add_subparsers(dest="command")`, dropping `required=True`) and call `parser.set_defaults(command="ui", port=8080, no_open=False)` so a bare `burpweb` parses as `ui` with defaults. Add the subcommand:
```python
    ui = sub.add_parser("ui", help="open the control page in a browser (default)")
    ui.add_argument("--port", type=int, default=8080)
    ui.add_argument("--no-open", action="store_true")
```
In `main`, handle `ui` as the first statement after `parse_args`, before any export is loaded (the `ui` command has no `exports` argument):
```python
    if args.command == "ui":
        from burpweb.webapp import run
        try:
            run(port=args.port, open_browser=not args.no_open)
        except KeyboardInterrupt:
            pass
        return 0
```
Keep `serve` and `list` behavior and their tests unchanged.

- [ ] **Step 5: Run the webapp tests to verify they pass**

Run: `uv run pytest tests/test_webapp.py -q`
Expected: all PASS. If `AsyncHTTPTestCase` needs `tornado.testing`, it is already installed with tornado.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: every test PASSES, including the existing engine tests.

- [ ] **Step 7: Commit**

```bash
git add src/burpweb/webapp.py src/burpweb/cli.py tests/test_webapp.py tests/test_cli.py
git commit -m "feat: Tornado control server and ui command"
```

- [ ] **Step 8: Manual smoke test**

Run: `uv run burpweb ui --no-open` in one terminal; from another, use the printed URL's token to `curl` `/api/state` with the cookie. Confirm it reports `vault: new`. Stop with Ctrl-C.

---

## Self-review notes

- **Memory:** uploads are streamed to disk already encrypted, so an upload never holds the file in memory. Creating, extending or replaying a snapshot does decrypt it into memory (`BytesIO`), because the XML parser needs a seekable stream; expect about twice the export's size in RAM while it loads. That is fine at the 100s-of-MB scale and is not optimised further here.
- **Review-driven fixes already applied to this plan:** streamed (not buffered) uploads, because Tornado's default 100 MB body limit would reject a real export; async tests that never block the shared event loop; same-origin WebSocket check; atomic snapshot replacement with crash recovery.
- **`replay_sid`** is single-valued because only one replay runs at a time (spec: out of scope to run several).
- **Frontend** is a separate plan; `static_dir` is optional and the server runs headless without it.
