"""Duplicate invoices: the same file is already refused at upload (SHA-256); this check finds the
same invoice sent again as a different file.

- Same seller and same invoice number (ignoring case, spaces and separators) → failed.
- Same seller, a different number, but the same gross total within one cent and an issue date
  at most a week apart → warning: possibly the same invoice renumbered.

`context.py` loads the other invoices of the same seller (by VAT ID, or by name without one).
"""

import re
from datetime import timedelta
from typing import Any

from invoiceguard_api.checks.model import TOLERANCE, CheckContext, CheckResult, OtherInvoice
from invoiceguard_api.models import CheckStatus

CHECK_TYPE = "duplicate"
SIMILAR_DATE_WINDOW = timedelta(days=7)


def normalise_number(number: str) -> str:
    """'RE-2026/0815 ' and 're 2026 0815' are the same invoice number."""
    return re.sub(r"[^0-9A-Z]", "", number.upper())


def _describe(other: OtherInvoice) -> dict[str, Any]:
    return {
        "invoice_id": str(other.id),
        "invoice_number": other.invoice_number,
        "issue_date": other.issue_date.isoformat(),
        "gross_total": str(other.gross_total),
        "status": other.status,
    }


def check(context: CheckContext) -> CheckResult:
    invoice = context.invoice
    number = normalise_number(invoice.invoice_number)
    same_number = [
        other
        for other in context.other_invoices
        if normalise_number(other.invoice_number) == number
    ]
    if same_number:
        ids = ", ".join(str(other.id) for other in same_number)
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.FAILED,
            f"Invoice number {invoice.invoice_number} from this seller already exists "
            f"(invoice {ids}).",
            {"match": "same_number", "invoices": [_describe(other) for other in same_number]},
        )

    similar = [
        other
        for other in context.other_invoices
        if abs(other.gross_total - invoice.gross_total) <= TOLERANCE
        and abs(other.issue_date - invoice.issue_date) <= SIMILAR_DATE_WINDOW
    ]
    if similar:
        ids = ", ".join(str(other.id) for other in similar)
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.WARNING,
            f"Same seller, same gross total and a close issue date as invoice {ids}: "
            "possibly a duplicate with a new number.",
            {
                "match": "similar_amount_and_date",
                "date_window_days": SIMILAR_DATE_WINDOW.days,
                "invoices": [_describe(other) for other in similar],
            },
        )
    return CheckResult(
        CHECK_TYPE,
        CheckStatus.PASSED,
        "No other invoice from this seller with the same number or amount and date.",
        {"compared_with": len(context.other_invoices)},
    )
