"""The rulebook (R3-4b): docs/rulebook split into chunks by heading, and `sync`, which keeps
`rulebook_chunks` in step with the files and fills in vectors (packaged, then embedded)."""

from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from fakes import KeywordEmbedder
from invoiceguard_api.booking import history
from invoiceguard_api.booking.embedding import EmbeddingFailed, encode_vector
from invoiceguard_api.models import ModelCall, ModelCallStatus, RulebookChunk
from invoiceguard_api.rulebook import index
from invoiceguard_api.rulebook.chunks import MAX_CHUNK_CHARS, RulebookError, load, parse

RULEBOOK = Path(__file__).resolve().parents[3] / "docs" / "rulebook"
MODEL = "gemini/gemini-embedding-001"
FILE = """# IBAN check

## What the check does

Compares the payee IBAN.

## How to resolve

Call the supplier.
"""
NO_VECTORS = {"model": MODEL, "dimensions": 768, "vectors": {}}


def rows(session: Session) -> list[RulebookChunk]:
    return list(session.scalars(select(RulebookChunk).order_by(RulebookChunk.id)))


def test_a_file_becomes_one_chunk_per_section() -> None:
    chunks = parse("iban.md", FILE)

    assert [chunk.key for chunk in chunks] == [
        "iban.md#what-the-check-does",
        "iban.md#how-to-resolve",
    ]
    assert chunks[0].title == "IBAN check" and chunks[0].text == "Compares the payee IBAN."
    assert chunks[0].file_sha256 == chunks[1].file_sha256
    assert chunks[0].text_sha256 != chunks[1].text_sha256


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ("No title\n\n## A\n\nx", "title"),
        ("# Title\n\nno sections", "sections"),
        ("# Title\n\n## Same\n\nx\n\n## Same\n\ny", "distinct"),
        (f"# Title\n\n## Long\n\n{'x' * (MAX_CHUNK_CHARS + 1)}", "longer"),
    ],
)
def test_a_badly_shaped_file_is_refused(content: str, problem: str) -> None:
    with pytest.raises(RulebookError, match=problem):
        parse("bad.md", content)


def test_the_repository_rulebook_parses(tmp_path: Path) -> None:
    chunks = load(RULEBOOK)

    assert len({chunk.source for chunk in chunks}) >= 10
    assert all(0 < len(chunk.text) <= MAX_CHUNK_CHARS for chunk in chunks)
    assert len({chunk.key for chunk in chunks}) == len(chunks)
    with pytest.raises(RulebookError, match="No rulebook files"):
        load(tmp_path)


def test_sync_writes_keeps_changes_and_deletes(db_session: Session) -> None:
    first = index.sync(db_session, parse("iban.md", FILE), MODEL, None, NO_VECTORS)
    assert (first.written, first.deleted) == (2, 0)
    # Unchanged: nothing written. A vector stays.
    stored = rows(db_session)
    stored[0].model, stored[0].vector = MODEL, [0.0] * 767 + [1.0]
    db_session.commit()
    again = index.sync(db_session, parse("iban.md", FILE), MODEL, None, NO_VECTORS)
    assert (again.written, again.deleted) == (0, 0)
    assert rows(db_session)[0].vector is not None

    changed = FILE.replace("Compares the payee IBAN.", "Compares the IBAN with the registry.")
    changed = changed.split("## How to resolve")[0]
    result = index.sync(db_session, parse("iban.md", changed), MODEL, None, NO_VECTORS)

    assert (result.written, result.deleted) == (1, 1)
    (row,) = rows(db_session)
    assert row.text == "Compares the IBAN with the registry." and row.vector is None


def test_packaged_vectors_are_loaded_by_text_hash(db_session: Session) -> None:
    chunks = parse("iban.md", FILE)
    packaged = {
        "model": MODEL,
        "dimensions": 768,
        "vectors": {chunks[0].text_sha256: encode_vector([0.5] * 768)},
    }

    result = index.sync(db_session, chunks, MODEL, None, packaged)
    other_model = index.sync(db_session, chunks, "other/model", None, packaged)

    assert result.loaded_vectors == 1 and other_model.loaded_vectors == 0
    assert [row.model for row in rows(db_session)] == [MODEL, None]


def test_missing_vectors_are_embedded_as_documents_and_logged(db_session: Session) -> None:
    embedder = KeywordEmbedder({"iban": 0, "supplier": 1})

    result = index.sync(db_session, parse("iban.md", FILE), MODEL, embedder, NO_VECTORS)

    assert result.embedded == 2 and embedder.tasks == ["document"]
    # The title and heading are embedded with the text.
    assert embedder.calls[0][0] == "IBAN check\nWhat the check does\nCompares the payee IBAN."
    assert all(row.model == MODEL and row.vector is not None for row in rows(db_session))
    (call,) = db_session.scalars(select(ModelCall)).all()
    assert (call.purpose, call.status) == ("embedding", ModelCallStatus.OK)


def test_a_failed_embedding_keeps_the_written_chunks(db_session: Session) -> None:
    with pytest.raises(EmbeddingFailed):
        index.sync(
            db_session, parse("iban.md", FILE), MODEL, KeywordEmbedder({}, fail=True), NO_VECTORS
        )
    assert len(rows(db_session)) == 2


def test_the_index_command_syncs_the_rulebook(engine: Engine, db_session: Session) -> None:
    counts = history.rebuild(db_session, MODEL, None, RULEBOOK)

    assert counts["rulebook_written"] == len(load(RULEBOOK))
    assert counts["rulebook_embedded"] == 0
    assert len(rows(db_session)) == counts["rulebook_written"]


def test_the_packaged_vectors_cover_the_rulebook() -> None:
    """`invoiceguard-eval vectors` writes them from the recorded embeddings; a changed section
    needs a new live embedding (docs/results.md)."""
    packaged = index.packaged_vectors()

    assert (packaged["model"], packaged["dimensions"]) == (MODEL, 768)
    assert {chunk.text_sha256 for chunk in load(RULEBOOK)} == set(packaged["vectors"])
