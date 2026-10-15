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


def test_verify_file_accepts_good_and_rejects_tampered_or_truncated(tmp_path):
    blob = enc(os.urandom(5000), chunk=1024)
    good = tmp_path / "good.enc"
    good.write_bytes(blob)
    vault.verify_file(KEY, good, snapshot_id="snap1", label="0")  # no exception

    flipped = bytearray(blob)
    flipped[-1] ^= 1
    (tmp_path / "flipped.enc").write_bytes(bytes(flipped))
    (tmp_path / "chopped.enc").write_bytes(blob[: len(blob) - 1100])
    frame = 4 + 1024 + 16  # length prefix + chunk + tag
    (tmp_path / "boundary.enc").write_bytes(blob[: 4 + 8 + 4 * frame])  # whole last chunk removed
    for name in ("flipped", "chopped", "boundary"):
        with pytest.raises(vault.BadData):
            vault.verify_file(KEY, tmp_path / f"{name}.enc", snapshot_id="snap1", label="0")
    with pytest.raises(vault.BadData):
        vault.verify_file(KEY, good, snapshot_id="snap1", label="other")
