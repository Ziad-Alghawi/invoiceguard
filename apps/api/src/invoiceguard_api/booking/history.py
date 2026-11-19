"""The booking index (ADR-020): imported history, packaged vectors, and `invoiceguard-index`.

- `history.json`: generated booking history (approved supplier invoices with an SKR03 account
  per line; `invoiceguard-eval generate`), imported as bookings with source `import`, as a
  company would bring its old bookings. All names and numbers are made up.
- `vectors.json`: the embedding vectors of those texts and of the demo samples' lines, written
  from the eval's recorded embeddings (`invoiceguard-eval vectors`). They let the demo, which has
  no model key, suggest by vector for its samples; other uploads there get the text match.

`invoiceguard-index` (`make index`) rebuilds the index and is safe to run again: it replaces the
imported history, loads the packaged vectors, and with a model key embeds every booking and
invoice line text that has no vector for the configured model yet (after a model change, every
text). Approved invoices are indexed when they are approved (record.py); nothing else changes.
"""

import base64
import json
import logging
import struct
import sys
from datetime import date
from importlib.resources import files
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from invoiceguard_api.booking.embedding import EmbeddingFailed, embed_missing
from invoiceguard_api.booking.text import normalise, text_sha256
from invoiceguard_api.checks.supplier import normalise_vat_id
from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.llm import Embedder
from invoiceguard_api.logging import configure_logging
from invoiceguard_api.main import make_embedder
from invoiceguard_api.models import (
    EMBEDDING_DIMENSIONS,
    Booking,
    BookingSource,
    Embedding,
    InvoiceField,
)
from invoiceguard_api.parsing.fields import LINE_TERMS
from invoiceguard_api.settings import get_settings

logger = logging.getLogger(__name__)

PACKAGE = files("invoiceguard_api") / "booking"
HISTORY = PACKAGE / "history.json"
VECTORS = PACKAGE / "vectors.json"
# Little-endian float32: 3 KB per 768-dimension vector in base64.
_FORMAT = f"<{EMBEDDING_DIMENSIONS}f"


def encode_vector(vector: tuple[float, ...] | list[float]) -> str:
    return base64.b64encode(struct.pack(_FORMAT, *vector)).decode("ascii")


def decode_vector(encoded: str) -> list[float]:
    return list(struct.unpack(_FORMAT, base64.b64decode(encoded)))


def packaged_history() -> list[dict[str, Any]]:
    invoices: list[dict[str, Any]] = json.loads(HISTORY.read_text("utf-8"))["invoices"]
    return invoices


def import_history(session: Session, invoices: list[dict[str, Any]]) -> int:
    """Replace the imported bookings with these invoices' lines; returns the number of lines.
    Bookings of approved invoices are left alone. The caller commits."""
    session.execute(delete(Booking).where(Booking.source == BookingSource.IMPORT))
    count = 0
    for invoice in invoices:
        for line_no, line in enumerate(invoice["lines"], start=1):
            text = normalise(line["text"])
            session.add(
                Booking(
                    source=BookingSource.IMPORT,
                    line_no=line_no,
                    supplier_vat_id=normalise_vat_id(invoice["supplier_vat_id"]),
                    supplier_name=invoice["supplier_name"],
                    invoice_number=invoice["invoice_number"],
                    issue_date=date.fromisoformat(invoice["issue_date"]),
                    text=text,
                    text_sha256=text_sha256(text),
                    account=line["account"],
                    suggested_account=None,
                    searchable=True,
                )
            )
            count += 1
    session.flush()
    return count


def load_vectors(session: Session, model: str, packaged: dict[str, Any]) -> int:
    """Store packaged vectors made with `model` for texts without one; returns how many are new.
    Vectors of another model are ignored: they do not compare with this model's. The caller
    commits."""
    if packaged["model"] != model or packaged["dimensions"] != EMBEDDING_DIMENSIONS:
        logger.info("Packaged vectors are for %s, not %s; not loaded", packaged["model"], model)
        return 0
    rows = [
        {
            "model": model,
            "text_sha256": text_sha256(normalise(text)),
            "text": normalise(text),
            "vector": decode_vector(encoded),
        }
        for text, encoded in packaged["vectors"].items()
    ]
    if not rows:
        return 0
    inserted = session.execute(
        insert(Embedding)
        .values(rows)
        .on_conflict_do_nothing(index_elements=[Embedding.model, Embedding.text_sha256])
        .returning(Embedding.id)
    )
    return len(inserted.all())


def packaged_vectors() -> dict[str, Any]:
    vectors: dict[str, Any] = json.loads(VECTORS.read_text("utf-8"))
    return vectors


def import_packaged(session: Session, model: str) -> tuple[int, int]:
    """The packaged history and vectors (demo reset, `invoiceguard-index`); the caller commits.
    Returns (bookings imported, vectors loaded)."""
    return import_history(session, packaged_history()), load_vectors(
        session, model, packaged_vectors()
    )


def all_texts(session: Session) -> list[str]:
    """Every booking text and every invoice line text, the texts suggestions compare."""
    bookings = session.scalars(select(Booking.text).distinct())
    lines = session.scalars(
        select(InvoiceField.value).where(InvoiceField.code == LINE_TERMS["item_name"]).distinct()
    )
    return [*bookings, *lines]


def rebuild(session: Session, model: str, embedder: Embedder | None) -> dict[str, int]:
    """`invoiceguard-index`: import the packaged index, then embed what is missing."""
    imported, loaded = import_packaged(session, model)
    session.commit()
    embedded = (
        0 if embedder is None else embed_missing(session, embedder, model, all_texts(session))
    )
    return {"imported_bookings": imported, "loaded_vectors": loaded, "embedded_texts": embedded}


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    embedder = make_embedder(settings, None)
    if embedder is None:
        logger.info("No model key: texts without a packaged vector keep the text match")
    engine = make_engine(str(settings.database_url))
    try:
        with make_session_factory(engine)() as session:
            counts = rebuild(session, settings.embedding_model, embedder)
    except EmbeddingFailed as error:
        sys.exit(f"Embedding failed: {error}. The texts embedded before it are stored.")
    finally:
        engine.dispose()
    logger.info("Booking index: %s", counts)
