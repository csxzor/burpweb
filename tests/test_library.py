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


def test_stats_include_origin_table(lib):
    other = b"GET /q HTTP/1.1\r\nHost: shop.invalid\r\n\r\n"
    api = b"GET /a HTTP/1.1\r\nHost: api.invalid:8080\r\n\r\n"
    xml = make_xml([
        make_item(host="shop.invalid", request=REQ, response=OK),
        make_item(host="shop.invalid", request=other, response=OK),
        make_item(host="api.invalid", port=8080, protocol="http", request=api, response=OK),
    ]).encode()
    snap = lib.create("s", [xml], ["a.xml"])
    expected = [
        {"origin": "https://shop.invalid", "items": 2, "paths": 2},
        {"origin": "http://api.invalid:8080", "items": 1, "paths": 1},
    ]
    assert snap.stats["by_origin"] == expected
    assert lib.list()[0].stats["by_origin"] == expected
    assert snap.stats["origins"] == 2  # the existing count is untouched


def _record_fsyncs(monkeypatch):
    seen = {"files": 0, "dirs": 0}
    real = os.fsync

    def spy(fd):
        seen["dirs" if stat.S_ISDIR(os.fstat(fd).st_mode) else "files"] += 1
        real(fd)
    monkeypatch.setattr(os, "fsync", spy)
    return seen


def test_a_crash_while_writing_vault_json_leaves_no_half_written_vault(tmp_path, monkeypatch):
    lib = Library(tmp_path / "lib")
    real = Library._write

    def torn(path, data):  # the process dies after half the bytes reached the disk
        real(path, data[: len(data) // 2])
        raise OSError("crash")
    monkeypatch.setattr(Library, "_write", staticmethod(torn))
    with pytest.raises(OSError):
        lib.create_vault("passphrase-123")
    assert lib.state == "new"  # a torn vault.json would be "locked" forever and unopenable
    monkeypatch.undo()
    lib.create_vault("passphrase-123")  # and a retry works
    assert lib.state == "unlocked"


def test_vault_creation_syncs_the_file_and_its_directory(tmp_path, monkeypatch):
    seen = _record_fsyncs(monkeypatch)
    Library(tmp_path / "lib").create_vault("passphrase-123")
    assert seen["files"] >= 1 and seen["dirs"] >= 1


def test_snapshot_creation_syncs_files_and_directories(lib, monkeypatch):
    seen = _record_fsyncs(monkeypatch)
    lib.create("s", [XML], ["a.xml"])
    assert seen["files"] >= 2 and seen["dirs"] >= 2  # data + meta; the new snapshot dir and the library dir


def test_new_files_are_never_world_readable_even_briefly(lib, monkeypatch):
    modes = []
    real_open = os.open

    def spy(path, flags, mode=0o777, **kw):
        if flags & os.O_CREAT:
            modes.append(mode)
        return real_open(path, flags, mode, **kw)
    monkeypatch.setattr(os, "open", spy)
    lib.create("s", [XML], ["a.xml"])
    assert modes and all(m == 0o600 for m in modes)
