"""Embedding invoice line texts (ADR-020): each normalised text is embedded once per model and
stored in `embeddings`; every call is logged in `model_calls` with its cost.

After processing, `embed_invoice_lines` embeds the new invoice's lines in the background. It
never changes the invoice: when it cannot run (no key, the daily budget, a failed call), the
suggestions for that invoice use the text match instead.
"""

import base64
import logging
import struct
import uuid
from collections.abc import Iterable, Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from invoiceguard_api.booking.lines import invoice_lines
from invoiceguard_api.booking.text import normalise, text_sha256
from invoiceguard_api.llm import Embedder, EmbeddingTask, LLMError
from invoiceguard_api.models import EMBEDDING_DIMENSIONS, Embedding, ModelCall, ModelCallStatus
from invoiceguard_api.processing import spent_today_usd

logger = logging.getLogger(__name__)

EMBEDDING_PURPOSE = "embedding"
# Texts per call; Gemini's batch endpoint takes up to 100.
BATCH_SIZE = 100


# Little-endian float32: 3 KB per 768-dimension vector in base64.
_FORMAT = f"<{EMBEDDING_DIMENSIONS}f"


def encode_vector(vector: tuple[float, ...] | list[float]) -> str:
    return base64.b64encode(struct.pack(_FORMAT, *vector)).decode("ascii")


def decode_vector(encoded: str) -> list[float]:
    return list(struct.unpack(_FORMAT, base64.b64decode(encoded)))


class EmbeddingFailed(Exception):
    """The call failed or returned something unusable; it is logged in `model_calls`."""


def missing_texts(session: Session, model: str, texts: Iterable[str]) -> list[str]:
    """The normalised texts that have no vector for `model` yet, each once, in first order."""
    unique = list(dict.fromkeys(normalise(text) for text in texts if text.strip()))
    stored = set(
        session.scalars(
            select(Embedding.text_sha256).where(
                Embedding.model == model,
                Embedding.text_sha256.in_([text_sha256(text) for text in unique]),
            )
        )
    )
    return [text for text in unique if text_sha256(text) not in stored]


def _log(
    session: Session,
    invoice_id: uuid.UUID | None,
    model: str,
    status: ModelCallStatus,
    latency_ms: int,
    *,
    input_tokens: int | None = None,
    cost_usd: Decimal | None = None,
    error: str | None = None,
) -> None:
    session.add(
        ModelCall(
            invoice_id=invoice_id,
            purpose=EMBEDDING_PURPOSE,
            model=model,
            status=status,
            input_tokens=input_tokens,
            output_tokens=None if input_tokens is None else 0,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            error=error,
        )
    )
    # Committed on its own: the cost stays logged even if storing the vectors fails.
    session.commit()


def embed_logged(
    session: Session,
    embedder: Embedder,
    model: str,
    texts: Sequence[str],
    task: EmbeddingTask,
    invoice_id: uuid.UUID | None = None,
) -> tuple[tuple[float, ...], ...]:
    """One embedding call, logged in `model_calls` (committed); the vectors in the order of the
    texts. Raises EmbeddingFailed for a failed call, an unknown price or unusable vectors."""
    try:
        reply = embedder.embed(model=model, texts=texts, dimensions=EMBEDDING_DIMENSIONS, task=task)
    except LLMError as error:
        _log(session, invoice_id, model, ModelCallStatus.ERROR, error.latency_ms, error=str(error))
        raise EmbeddingFailed(str(error)) from error
    status, problem = ModelCallStatus.OK, None
    sizes = {len(vector) for vector in reply.vectors}
    if reply.cost_usd is None:
        # An unknown price is an error, never zero cost (ADR-004).
        status = ModelCallStatus.PRICE_UNKNOWN
        problem = f"No price for {model} in the price table."
    elif len(reply.vectors) != len(texts) or sizes != {EMBEDDING_DIMENSIONS}:
        status = ModelCallStatus.INVALID_OUTPUT
        problem = f"Expected {len(texts)} vectors of {EMBEDDING_DIMENSIONS} numbers."
    _log(
        session,
        invoice_id,
        model,
        status,
        reply.latency_ms,
        input_tokens=reply.input_tokens,
        cost_usd=reply.cost_usd,
        error=problem,
    )
    if problem is not None:
        raise EmbeddingFailed(problem)
    return reply.vectors


def _embed_batch(
    session: Session,
    embedder: Embedder,
    model: str,
    batch: Sequence[str],
    invoice_id: uuid.UUID | None,
) -> None:
    vectors = embed_logged(session, embedder, model, batch, "similarity", invoice_id)
    # A parallel run may have stored the same text meanwhile; its vector is just as good.
    session.execute(
        insert(Embedding)
        .values(
            [
                {
                    "model": model,
                    "text_sha256": text_sha256(text),
                    "text": text,
                    "vector": list(vector),
                }
                for text, vector in zip(batch, vectors, strict=True)
            ]
        )
        .on_conflict_do_nothing(index_elements=[Embedding.model, Embedding.text_sha256])
    )
    session.commit()


def embed_missing(
    session: Session,
    embedder: Embedder,
    model: str,
    texts: Iterable[str],
    invoice_id: uuid.UUID | None = None,
) -> int:
    """Embed and store the texts without a vector for `model`; returns how many were embedded.

    Raises EmbeddingFailed at the first failed call; the batches before it stay stored.
    """
    pending = missing_texts(session, model, texts)
    for start in range(0, len(pending), BATCH_SIZE):
        _embed_batch(session, embedder, model, pending[start : start + BATCH_SIZE], invoice_id)
    return len(pending)


def embed_invoice_lines(
    session_factory: sessionmaker[Session],
    embedder: Embedder | None,
    model: str,
    daily_budget_usd: Decimal | None,
    invoice_id: uuid.UUID,
) -> None:
    """After processing: embed the invoice's line texts that have no vector yet."""
    if embedder is None:
        return
    with session_factory() as session:
        texts = [line.text for line in invoice_lines(session, invoice_id)]
        if not missing_texts(session, model, texts):
            return
        if daily_budget_usd is not None and spent_today_usd(session) >= daily_budget_usd:
            logger.info("Lines of invoice %s not embedded: daily LLM budget used up", invoice_id)
            return
        try:
            count = embed_missing(session, embedder, model, texts, invoice_id)
        except EmbeddingFailed as error:
            logger.warning("Lines of invoice %s not embedded: %s", invoice_id, error)
            return
    logger.info("Embedded %d line text(s) of invoice %s", count, invoice_id)
