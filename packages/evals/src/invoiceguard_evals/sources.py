"""Public sample files, pinned in `sources.json` by repository commit and SHA-256 (ADR-019).

They are downloaded into an ignored cache, never committed: the ZUGFeRD corpus collects files from
FeRD and many vendors, so its repository licence does not clearly cover every file. A file whose
hash differs from the pin is refused, so a changed upstream file cannot change the results.
"""

import hashlib
import io
import urllib.request
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pypdf import PdfReader, PdfWriter

PACKAGE_DIR = Path(__file__).resolve().parents[2]
MANIFEST = PACKAGE_DIR / "sources.json"
CACHE_DIR = PACKAGE_DIR / ".cache"
DOWNLOAD_TIMEOUT_SECONDS = 60


class Repository(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    home: str
    # Raw file URL prefix; the commit and the path are appended.
    raw_url: str
    commit: str
    licence: str


class SourceFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    set: Literal["kosit", "corpus"]
    repository: str
    path: str
    sha256: str
    tags: frozenset[str] = frozenset()
    # Terms whose printed value differs from the XML (or that the XML leaves out), with `note`
    # saying why; never taken from a model's answer.
    truth_overrides: dict[str, Any] = {}
    note: str | None = None


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repositories: dict[str, Repository]
    files: tuple[SourceFile, ...]

    def url(self, source: SourceFile) -> str:
        repository = self.repositories[source.repository]
        return f"{repository.raw_url}/{repository.commit}/{source.path}"


class SourceError(Exception):
    """A source file is missing from the cache or does not match its pinned hash."""


def load_manifest(path: Path = MANIFEST) -> Manifest:
    return Manifest.model_validate_json(path.read_text("utf-8"))


def cache_path(source: SourceFile, cache: Path = CACHE_DIR) -> Path:
    return cache / source.repository / source.path


def _verified(source: SourceFile, content: bytes) -> bytes:
    actual = hashlib.sha256(content).hexdigest()
    if actual != source.sha256:
        raise SourceError(
            f"{source.id}: SHA-256 {actual} does not match the pin {source.sha256}; refused."
        )
    return content


def read_source(source: SourceFile, cache: Path = CACHE_DIR) -> bytes:
    path = cache_path(source, cache)
    if not path.exists():
        raise SourceError(f"{source.id} is not downloaded: run `invoiceguard-eval fetch`.")
    return _verified(source, path.read_bytes())


def _download(url: str) -> bytes:
    if not url.startswith("https://"):
        raise SourceError(f"Refusing a download that is not HTTPS: {url}")
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        return bytes(response.read())


def fetch(manifest: Manifest, cache: Path = CACHE_DIR) -> int:
    """Download every file that is not cached yet; returns how many were downloaded."""
    downloaded = 0
    for source in manifest.files:
        path = cache_path(source, cache)
        if path.exists():
            read_source(source, cache)
            continue
        content = _verified(source, _download(manifest.url(source)))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        downloaded += 1
    return downloaded


def without_attachments(pdf: bytes) -> bytes:
    """The PDF's pages only: no embedded files (the e-invoice XML), no document metadata, so the
    model sees what a person sees and nothing else."""
    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(pdf)).pages:
        writer.add_page(page)
    writer.remove_annotations(subtypes="/FileAttachment")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
