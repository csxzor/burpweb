import pytest

from burpfixtures import make_xml


@pytest.fixture
def write_xml(tmp_path):
    def _write(items, name="history.xml"):
        path = tmp_path / name
        path.write_text(make_xml(items), encoding="utf-8")
        return path

    return _write
