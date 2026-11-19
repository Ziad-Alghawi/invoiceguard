"""Booking suggestions by retrieval and a vote, in code (ADR-020, ADR-002: no chat model).

For one line text: the K most similar searchable bookings, by cosine similarity of their vectors
when the line has a vector for the model ("vector"), otherwise by trigram similarity of the texts
("text", the text match). A booking from the same supplier gets SUPPLIER_BONUS on its score (the
supplier filter of PLAN section 9, as a preference: a new supplier still gets suggestions). Each
neighbour weighs exp((score - best score) / TEMPERATURE), and an account's weight is the sum over
its neighbours: the closest bookings decide, and many loosely similar ones cannot outvote an exact
match. The top accounts come with their share of the weight and the bookings behind them, so the
reviewer sees why.

Why not the plain sum of scores (the first design): embedding similarities are compressed (two
unrelated German item names still score about 0.8), so the sum let the account with the most
neighbours win; the first eval run missed every phone line for the internet account next to it,
even one whose exact text was booked before. The eval reports both (ADR-020, docs/results.md).

Bookings of the invoice itself never count, so an approved invoice is not its own evidence.
The search is an exact scan of the bookings; at a few thousand rows that takes milliseconds.
"""

import math
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from invoiceguard_api.booking.accounts import account_name
from invoiceguard_api.booking.lines import invoice_lines
from invoiceguard_api.booking.text import normalise, text_sha256
from invoiceguard_api.checks.supplier import normalise_vat_id
from invoiceguard_api.models import Embedding, InvoiceField
from invoiceguard_api.parsing.fields import DOCUMENT_TERMS

Method = Literal["vector", "text"]
K_NEIGHBOURS = 10
SUPPLIER_BONUS = 0.1
# A neighbour 0.05 below the best weighs 1/e of it.
TEMPERATURE = 0.05
MAX_SUGGESTIONS = 3
MAX_SOURCES = 3
SELLER_VAT_ID = DOCUMENT_TERMS["seller_vat_id"]

_COLUMNS = """
    b.invoice_id, b.invoice_number, b.issue_date, b.supplier_name, b.text, b.account,
    COALESCE(b.supplier_vat_id = :vat_id, false) AS same_supplier
"""
_FILTER = """b.searchable AND (
    CAST(:invoice_id AS uuid) IS NULL OR b.invoice_id IS DISTINCT FROM CAST(:invoice_id AS uuid)
)"""
_BONUS = "CASE WHEN b.supplier_vat_id = :vat_id THEN :bonus ELSE 0 END"
# Fixed SQL built from the constants above; every value is a bound parameter.
VECTOR_SQL = text(f"""
SELECT {_COLUMNS}, 1 - (e.vector <=> q.vector) AS similarity,
       1 - (e.vector <=> q.vector) + {_BONUS} AS score
FROM bookings b
JOIN embeddings e ON e.model = :model AND e.text_sha256 = b.text_sha256
CROSS JOIN (SELECT vector FROM embeddings WHERE model = :model AND text_sha256 = :sha) q
WHERE {_FILTER}
ORDER BY score DESC, b.id
LIMIT :k
""")
TEXT_SQL = text(f"""
SELECT {_COLUMNS}, similarity(b.text, :text) AS similarity,
       similarity(b.text, :text) + {_BONUS} AS score
FROM bookings b
WHERE {_FILTER}
ORDER BY score DESC, b.id
LIMIT :k
""")


@dataclass(frozen=True)
class Neighbour:
    """A booking found for a line, with how similar its text is."""

    invoice_id: uuid.UUID | None
    invoice_number: str | None
    issue_date: date | None
    supplier_name: str | None
    text: str
    account: str
    same_supplier: bool
    similarity: float
    score: float


@dataclass(frozen=True)
class AccountSuggestion:
    account: str
    name: str
    # The account's share of the neighbours' weight, 0..1.
    share: float
    # The most similar bookings to this account, best first.
    sources: tuple[Neighbour, ...]


@dataclass(frozen=True)
class LineSuggestion:
    line_no: int
    text: str
    method: Method
    # Best first; empty when there is nothing to suggest from.
    suggestions: tuple[AccountSuggestion, ...]


def neighbours(
    session: Session,
    model: str | None,
    line_text: str,
    vat_id: str | None,
    exclude_invoice_id: uuid.UUID | None = None,
    k: int = K_NEIGHBOURS,
) -> tuple[Method, list[Neighbour]]:
    """The K best bookings for a line text; `model` None uses the text match only."""
    normalised = normalise(line_text)
    sha = text_sha256(normalised)
    has_vector = model is not None and session.scalar(
        select(Embedding.id).where(Embedding.model == model, Embedding.text_sha256 == sha)
    )
    params = {
        "vat_id": None if vat_id is None else normalise_vat_id(vat_id),
        "invoice_id": None if exclude_invoice_id is None else str(exclude_invoice_id),
        "bonus": SUPPLIER_BONUS,
        "k": k,
    }
    if has_vector:
        rows = session.execute(VECTOR_SQL, {**params, "model": model, "sha": sha}).all()
        method: Method = "vector"
    else:
        rows = session.execute(TEXT_SQL, {**params, "text": normalised}).all()
        method = "text"
    return method, [Neighbour(**row._asdict()) for row in rows]


def vote(
    found: Sequence[Neighbour], temperature: float | None = TEMPERATURE
) -> tuple[AccountSuggestion, ...]:
    """Accounts by the weights of their neighbours (see the module docstring); `temperature`
    None sums the plain scores, the first design, which only the eval still runs. A neighbour
    with no score (no shared trigram, another supplier) is no evidence and does not count."""
    evidence = [neighbour for neighbour in found if neighbour.score > 0]
    best = max((neighbour.score for neighbour in evidence), default=0.0)
    weights: dict[str, float] = defaultdict(float)
    sources: dict[str, list[Neighbour]] = defaultdict(list)
    for neighbour in evidence:
        weights[neighbour.account] += (
            neighbour.score
            if temperature is None
            else math.exp((neighbour.score - best) / temperature)
        )
        sources[neighbour.account].append(neighbour)
    total = sum(weights.values())
    ranked = sorted(weights, key=lambda account: (-weights[account], account))
    return tuple(
        AccountSuggestion(
            account=account,
            name=account_name(account),
            share=weights[account] / total,
            sources=tuple(sources[account][:MAX_SOURCES]),
        )
        for account in ranked[:MAX_SUGGESTIONS]
    )


def seller_vat_id(session: Session, invoice_id: uuid.UUID) -> str | None:
    return session.scalar(
        select(InvoiceField.value).where(
            InvoiceField.invoice_id == invoice_id,
            InvoiceField.code == SELLER_VAT_ID,
            InvoiceField.line_no.is_(None),
        )
    )


def suggest_invoice(session: Session, model: str, invoice_id: uuid.UUID) -> list[LineSuggestion]:
    """A suggestion for every line of the invoice."""
    vat_id = seller_vat_id(session, invoice_id)
    suggestions = []
    for line in invoice_lines(session, invoice_id):
        method, found = neighbours(session, model, line.text, vat_id, invoice_id)
        suggestions.append(LineSuggestion(line.line_no, line.text, method, vote(found)))
    return suggestions
