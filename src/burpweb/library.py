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
        self._verified: dict[tuple[str, int], tuple[int, int]] = {}  # (snapshot, file) -> (size, mtime_ns)

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
        self._verified.clear()

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
            snap = Snapshot(id=d.name, **meta, damaged=False)
        except (vault.BadData, OSError, ValueError, TypeError):
            return Snapshot(id=d.name, name="(damaged)", created="", files=[], stats={}, damaged=True)
        snap.damaged = not self._files_intact(key, d, snap.files)
        return snap

    def _files_intact(self, key: bytes, d: Path, files: list[dict]) -> bool:
        """Authenticate every data file once per unlock (re-checked only if size or mtime changes)."""
        for index in range(len(files)):
            path = d / "files" / f"{index}.enc"
            try:
                st = path.stat()
                signature = (st.st_size, st.st_mtime_ns)
                if self._verified.get((d.name, index)) == signature:
                    continue
                vault.verify_file(key, path, snapshot_id=d.name, label=str(index))
                self._verified[(d.name, index)] = signature
            except (OSError, vault.BadData):
                return False
        return True

    def create(self, name, sources, filenames):
        return self._write_snapshot(secrets.token_hex(16), name, list(sources), list(filenames), existing=None)

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
        rows: dict[str, dict] = {}
        for r in result.records:
            row = rows.setdefault(r.origin, {"items": 0, "paths": set()})
            row["items"] += 1
            row["paths"].add(r.path)
        by_origin = sorted(
            ({"origin": o, "items": v["items"], "paths": len(v["paths"])} for o, v in rows.items()),
            key=lambda row: -row["items"],  # sorted() is stable, so ties keep first-seen order
        )
        stats = {"items": len(result.records),
                 "origins": len(rows),
                 "skipped": result.skipped_no_response,
                 "malformed": result.malformed,
                 "by_origin": by_origin}
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
