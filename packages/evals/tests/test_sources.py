"""Pinned sources: a file is used only when its hash matches the pin, downloads are HTTPS only,
and the model gets the PDF without its embedded XML."""

import hashlib
from pathlib import Path

import pytest
from facturx import generate_from_binary
from invoiceguard_api.parsing.model import NoEmbeddedXml
from invoiceguard_api.parsing.pdf import extract_xml

from invoiceguard_evals import sources
from invoiceguard_evals.datasets import GENERATED_DIR
from invoiceguard_evals.sources import (
    Manifest,
    Repository,
    SourceError,
    SourceFile,
    cache_path,
    fetch,
    load_manifest,
    read_source,
    without_attachments,
)

API_FIXTURES = Path(__file__).resolve().parents[3] / "apps" / "api" / "tests" / "fixtures"
CONTENT = b"<Invoice/>"


def manifest(content: bytes = CONTENT) -> Manifest:
    return Manifest(
        repositories={
            "repo": Repository(
                home="https://example.org",
                raw_url="https://example.org/raw",
                commit="abc123",
                licence="test",
            )
        },
        files=(
            SourceFile(
                id="one",
                set="kosit",
                repository="repo",
                path="dir/one.xml",
                sha256=hashlib.sha256(content).hexdigest(),
            ),
        ),
    )


def test_fetch_downloads_once_and_verifies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []

    def download(url: str) -> bytes:
        urls.append(url)
        return CONTENT

    monkeypatch.setattr(sources, "_download", download)

    assert fetch(manifest(), tmp_path) == 1
    assert fetch(manifest(), tmp_path) == 0
    assert urls == ["https://example.org/raw/abc123/dir/one.xml"]
    assert read_source(manifest().files[0], tmp_path) == CONTENT


def test_a_changed_file_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources, "_download", lambda url: b"<Invoice>changed</Invoice>")

    with pytest.raises(SourceError, match="does not match the pin"):
        fetch(manifest(), tmp_path)
    assert not cache_path(manifest().files[0], tmp_path).exists()


def test_a_changed_cached_file_is_refused(tmp_path: Path) -> None:
    path = cache_path(manifest().files[0], tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"tampered")

    with pytest.raises(SourceError, match="does not match the pin"):
        read_source(manifest().files[0], tmp_path)


def test_a_missing_file_says_how_to_get_it(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="invoiceguard-eval fetch"):
        read_source(manifest().files[0], tmp_path)


def test_only_https_downloads() -> None:
    with pytest.raises(SourceError, match="not HTTPS"):
        sources._download("file:///etc/passwd")


def test_the_committed_manifest_pins_every_file() -> None:
    pinned = load_manifest()

    assert {f.set for f in pinned.files} == {"kosit", "corpus"}
    assert all(len(f.sha256) == 64 for f in pinned.files)
    assert all(len(r.commit) == 40 for r in pinned.repositories.values())
    assert all(f.note for f in pinned.files if f.truth_overrides)


def test_the_embedded_xml_is_removed() -> None:
    pdf = (GENERATED_DIR / "g01_buerobedarf_classic.pdf").read_bytes()
    xml = (API_FIXTURES / "zugferd2_basic.xml").read_bytes()
    zugferd = bytes(generate_from_binary(pdf, xml, check_xsd=False))
    assert extract_xml(zugferd) == xml

    with pytest.raises(NoEmbeddedXml):
        extract_xml(without_attachments(zugferd))
