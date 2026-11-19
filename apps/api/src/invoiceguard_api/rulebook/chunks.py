"""Splitting the rulebook's Markdown files into chunks, one per `##` section.

A file has one `#` title and short `##` sections; each section is a chunk that carries the file
title and its heading, so a chunk found alone still says what it is about. Text before the first
section is not a chunk (the files have none). A section longer than MAX_CHUNK_CHARS is an error:
the rulebook is kept short on purpose, and a cut section would lose its end silently.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

MAX_CHUNK_CHARS = 1500
_TITLE = re.compile(r"^# (.+)$")
_SECTION = re.compile(r"^## (.+)$")


class RulebookError(Exception):
    """A rulebook file does not have the expected shape."""


@dataclass(frozen=True)
class Chunk:
    # The file name in docs/rulebook and the section's anchor (its heading as a slug).
    source: str
    anchor: str
    title: str
    heading: str
    text: str
    file_sha256: str

    @property
    def key(self) -> str:
        """The chunk's id in evals and tool results: `iban.md#how-to-resolve-a-changed-iban`."""
        return f"{self.source}#{self.anchor}"

    @property
    def text_sha256(self) -> str:
        """Of the embedded text: a changed title or heading needs a new vector too."""
        text = embedding_text(self.title, self.heading, self.text)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embedding_text(title: str, heading: str, text: str) -> str:
    """What is embedded for a chunk: the title and heading give a short section its context."""
    return f"{title}\n{heading}\n{text}"


def slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.casefold()).strip("-")


def parse(source: str, content: str) -> list[Chunk]:
    lines = content.replace("\r\n", "\n").split("\n")
    title_match = _TITLE.match(lines[0]) if lines else None
    if title_match is None:
        raise RulebookError(f"{source}: the first line must be a '# ' title")
    title = title_match.group(1).strip()
    file_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    sections: list[tuple[str, list[str]]] = []
    for line in lines[1:]:
        if (match := _SECTION.match(line)) is not None:
            sections.append((match.group(1).strip(), []))
        elif sections:
            sections[-1][1].append(line)
    chunks = []
    for heading, body in sections:
        text = "\n".join(body).strip()
        if len(text) > MAX_CHUNK_CHARS:
            raise RulebookError(f"{source}#{slug(heading)}: longer than {MAX_CHUNK_CHARS} chars")
        chunks.append(Chunk(source, slug(heading), title, heading, text, file_sha256))
    if not chunks or len({chunk.anchor for chunk in chunks}) != len(chunks):
        raise RulebookError(f"{source}: needs '## ' sections with distinct headings")
    return chunks


def load(directory: Path) -> list[Chunk]:
    """Every chunk of every `*.md` file in the directory but its README, in file and section
    order."""
    files = sorted(path for path in directory.glob("*.md") if path.name != "README.md")
    if not files:
        raise RulebookError(f"No rulebook files in {directory}")
    return [chunk for path in files for chunk in parse(path.name, path.read_text("utf-8"))]
