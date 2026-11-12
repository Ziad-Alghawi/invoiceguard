"""Deterministic invoice checks (PLAN section 5): pure functions of a `CheckContext`.

`run_checks` runs all of them; `replace_results` stores the results so that a re-run replaces
the previous ones. Any failed check blocks the invoice (`final_status`).
"""

import uuid
from collections import Counter
from collections.abc import Callable
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from invoiceguard_api.checks import (
    duplicate,
    iban,
    kosit,
    low_confidence,
    po_match,
    supplier,
    vat,
)
from invoiceguard_api.checks.context import load_context
from invoiceguard_api.checks.kosit import KositValidator
from invoiceguard_api.checks.model import CheckContext, CheckResult
from invoiceguard_api.models import Check, CheckStatus, InvoiceStatus

__all__ = [
    "CheckResult",
    "KositValidator",
    "final_status",
    "load_context",
    "replace_results",
    "run_checks",
    "summarise",
]

_CHECKS: tuple[Callable[[CheckContext], CheckResult | list[CheckResult]], ...] = (
    kosit.check,
    vat.check,
    duplicate.check,
    supplier.check,
    iban.check,
    po_match.check,
    low_confidence.check,
)


def run_checks(context: CheckContext) -> list[CheckResult]:
    results: list[CheckResult] = []
    for run in _CHECKS:
        outcome = run(context)
        results.extend(outcome if isinstance(outcome, list) else [outcome])
    return results


def final_status(results: list[CheckResult]) -> InvoiceStatus:
    """Any failed check blocks the invoice; warnings and skipped checks leave it `ready`."""
    if any(result.status is CheckStatus.FAILED for result in results):
        return InvoiceStatus.BLOCKED
    return InvoiceStatus.READY


def summarise(results: list[CheckResult]) -> dict[str, Any]:
    """Counts per status and the failed check types, for the audit event and status reason."""
    counts = Counter(result.status.value for result in results)
    return {
        **{status.value: counts[status.value] for status in CheckStatus},
        "failed_checks": [r.type for r in results if r.status is CheckStatus.FAILED],
    }


def replace_results(session: Session, invoice_id: uuid.UUID, results: list[CheckResult]) -> None:
    """Delete the invoice's previous check rows and add these; the caller commits."""
    session.execute(delete(Check).where(Check.invoice_id == invoice_id))
    session.add_all(
        Check(
            invoice_id=invoice_id,
            type=result.type,
            status=result.status,
            message=result.message,
            evidence=result.evidence,
        )
        for result in results
    )
