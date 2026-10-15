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
