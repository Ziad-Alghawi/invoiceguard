"""Keeping `rulebook_chunks` in step with docs/rulebook (part of `invoiceguard-index`).

`sync` makes the table hold exactly the current chunks: new and changed sections are written, a
changed section loses its vector, removed sections are deleted. Vectors come from the packaged
`vectors.json` (written by `invoiceguard-eval vectors` from recorded embeddings, so the demo and CI
need no key) and, with a key, from embedding what is still missing (task `document`). Without a
vector a chunk is found by full text only. The rulebook is reviewed text from the repository, but
what it returns to the agent is treated as data like every tool result.
"""

import json
import logging
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from invoiceguard_api.booking.embedding import BATCH_SIZE, decode_vector, embed_logged
from invoiceguard_api.llm import Embedder
from invoiceguard_api.models import EMBEDDING_DIMENSIONS, RulebookChunk
from invoiceguard_api.rulebook.chunks import Chunk, embedding_text

logger = logging.getLogger(__name__)

VECTORS = files("invoiceguard_api") / "rulebook" / "vectors.json"


@dataclass(frozen=True)
class SyncCounts:
    written: int
    deleted: int
    loaded_vectors: int
    embedded: int


def packaged_vectors() -> dict[str, Any]:
    vectors: dict[str, Any] = json.loads(VECTORS.read_text("utf-8"))
    return vectors


def _write(session: Session, chunks: list[Chunk]) -> tuple[int, int]:
    stored = {(row.source, row.anchor): row for row in session.scalars(select(RulebookChunk))}
    current = {(chunk.source, chunk.anchor) for chunk in chunks}
    written = 0
    for chunk in chunks:
        row = stored.get((chunk.source, chunk.anchor))
        if row is None:
            row = RulebookChunk(source=chunk.source, anchor=chunk.anchor)
            session.add(row)
        elif row.text_sha256 == chunk.text_sha256:
            row.file_sha256 = chunk.file_sha256
            continue
        row.title, row.heading, row.text = chunk.title, chunk.heading, chunk.text
        row.text_sha256, row.file_sha256 = chunk.text_sha256, chunk.file_sha256
        row.model, row.vector = None, None
        written += 1
    gone = [key for key in stored if key not in current]
    for source, anchor in gone:
        session.execute(
            delete(RulebookChunk).where(
                RulebookChunk.source == source, RulebookChunk.anchor == anchor
            )
        )
    session.flush()
    return written, len(gone)


def _missing(session: Session, model: str) -> list[RulebookChunk]:
    return list(
        session.scalars(
            select(RulebookChunk)
            .where((RulebookChunk.model.is_distinct_from(model)) | RulebookChunk.vector.is_(None))
            .order_by(RulebookChunk.id)
        )
    )


def _load_packaged(session: Session, model: str, packaged: dict[str, Any]) -> int:
    if packaged["model"] != model or packaged["dimensions"] != EMBEDDING_DIMENSIONS:
        logger.info("Packaged rulebook vectors are for %s, not %s", packaged["model"], model)
        return 0
    loaded = 0
    for row in _missing(session, model):
        encoded = packaged["vectors"].get(row.text_sha256)
        if encoded is not None:
            row.model, row.vector = model, decode_vector(encoded)
            loaded += 1
    session.flush()
    return loaded


def sync(
    session: Session,
    chunks: list[Chunk],
    model: str,
    embedder: Embedder | None,
    packaged: dict[str, Any] | None = None,
) -> SyncCounts:
    """Make the table match `chunks`, then fill in vectors; commits. Raises EmbeddingFailed
    when the embedding call fails (what was written before stays)."""
    written, deleted = _write(session, chunks)
    loaded = _load_packaged(session, model, packaged_vectors() if packaged is None else packaged)
    session.commit()
    embedded = 0
    missing = _missing(session, model)
    if embedder is not None:
        for start in range(0, len(missing), BATCH_SIZE):
            batch = missing[start : start + BATCH_SIZE]
            texts = [embedding_text(row.title, row.heading, row.text) for row in batch]
            vectors = embed_logged(session, embedder, model, texts, "document")
            for row, vector in zip(batch, vectors, strict=True):
                row.model, row.vector = model, list(vector)
            embedded += len(batch)
            session.commit()
    return SyncCounts(written, deleted, loaded, embedded)
