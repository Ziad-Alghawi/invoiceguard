"""`GET /invoices/{id}/bookings`: the booking suggestion for each line with its evidence, the
account booked when the invoice was approved, and the accounts to choose from (ADR-020).

Suggestions are computed when asked, so they use every booking approved since. They are only
suggestions: the reviewer chooses the account per line when approving (review.py).
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from invoiceguard_api.auth import current_user
from invoiceguard_api.booking.accounts import ACCOUNTS, account_name
from invoiceguard_api.booking.suggest import Method, suggest_invoice
from invoiceguard_api.db import DbSession
from invoiceguard_api.invoices import ErrorOut, get_invoice_or_404
from invoiceguard_api.models import Booking

router = APIRouter(prefix="/invoices", tags=["bookings"], dependencies=[Depends(current_user)])


class AccountOut(BaseModel):
    number: str
    name: str


class SourceOut(BaseModel):
    """A booking the suggestion rests on; `invoice_id` is null for imported history."""

    invoice_id: uuid.UUID | None
    invoice_number: str | None
    issue_date: date | None
    supplier_name: str | None
    text: str
    account: str
    same_supplier: bool
    # Cosine similarity of the vectors, or trigram similarity of the texts (method `text`).
    similarity: float


class SuggestionOut(BaseModel):
    account: str
    name: str
    # Share of the neighbours' weight, 0..1; not a probability.
    share: float
    sources: list[SourceOut]


class BookedOut(BaseModel):
    account: str
    name: str
    suggested_account: str | None


class LineBookingOut(BaseModel):
    line_no: int
    text: str
    # `vector`: by embeddings; `text`: by text match (no vector for this line).
    method: Method
    suggestions: list[SuggestionOut]
    # The account chosen at approval; null until then.
    booked: BookedOut | None


class BookingsOut(BaseModel):
    accounts: list[AccountOut]
    # Preselected when a line has no suggestion (the DATEV export's expense account).
    default_account: str
    lines: list[LineBookingOut]


@router.get(
    "/{invoice_id}/bookings",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorOut, "description": "Unknown invoice"}},
)
def invoice_bookings(invoice_id: uuid.UUID, session: DbSession, request: Request) -> BookingsOut:
    """Booking suggestions per line, best first, with the bookings they rest on."""
    get_invoice_or_404(session, invoice_id)
    settings = request.app.state.settings
    booked = {
        booking.line_no: booking
        for booking in session.scalars(select(Booking).where(Booking.invoice_id == invoice_id))
    }
    lines: list[dict[str, Any]] = []
    for line in suggest_invoice(session, settings.embedding_model, invoice_id):
        booking = booked.get(line.line_no)
        lines.append(
            {
                "line_no": line.line_no,
                "text": line.text,
                "method": line.method,
                "suggestions": [
                    {
                        "account": suggestion.account,
                        "name": suggestion.name,
                        "share": round(suggestion.share, 3),
                        "sources": [
                            {**vars(source), "similarity": round(source.similarity, 3)}
                            for source in suggestion.sources
                        ],
                    }
                    for suggestion in line.suggestions
                ],
                "booked": None
                if booking is None
                else {
                    "account": booking.account,
                    "name": account_name(booking.account),
                    "suggested_account": booking.suggested_account,
                },
            }
        )
    return BookingsOut.model_validate(
        {
            "accounts": [{"number": n, "name": name} for n, name in ACCOUNTS.items()],
            "default_account": settings.datev_expense_account,
            "lines": lines,
        }
    )
