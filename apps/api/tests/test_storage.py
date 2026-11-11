import os
from pathlib import Path

import pytest

from invoiceguard_api.storage import FileStorage

SHA = "ab" + "0" * 62


def test_save_stores_content_under_its_hash(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path)

    relative = storage.save(SHA, "xml", b"<Invoice/>")

    assert relative == f"ab/{SHA}.xml"
    assert (tmp_path / relative).read_bytes() == b"<Invoice/>"


def test_saving_the_same_content_twice_is_harmless(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path)

    first = storage.save(SHA, "pdf", b"%PDF-1.7")
    second = storage.save(SHA, "pdf", b"%PDF-1.7")

    assert first == second
    assert [path.name for path in (tmp_path / "ab").iterdir()] == [f"{SHA}.pdf"]


def test_failed_write_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)

    with pytest.raises(OSError, match="disk full"):
        FileStorage(tmp_path).save(SHA, "xml", b"<Invoice/>")

    assert list((tmp_path / "ab").iterdir()) == []
