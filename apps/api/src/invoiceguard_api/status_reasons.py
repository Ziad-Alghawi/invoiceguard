"""The status reasons processing writes, and their codes for the web (ADR-027).

`invoices.status_reason` and an audit row's `reason` hold text: a reason processing writes from
this module, a parser error, or what a user wrote with a decision. The web shows the first kind in
the user's language, so the API returns a code with it, found by `reason_code` from the text this
module wrote. Other text has no code and is shown as written.
"""

import re
from collections.abc import Sequence
from typing import Literal

ReasonCode = Literal[
    "failed_checks",
    "awaiting_extraction",
    "extraction_off",
    "daily_budget",
    "internal_error",
    "restarted",
]

AWAITING_EXTRACTION_REASON = "The PDF has no embedded e-invoice XML; it needs LLM extraction."
EXTRACTION_OFF_REASON = (
    "The PDF has no embedded e-invoice XML, and LLM extraction is skipped: no API key is "
    "configured (INVOICEGUARD_LLM_API_KEY)."
)
BUDGET_REASON = (
    "The daily LLM budget (INVOICEGUARD_LLM_DAILY_BUDGET_USD) is used up; the PDF is extracted "
    "after the next API restart on a later day."
)
INTERNAL_ERROR_REASON = "Processing failed with an internal error; see the API logs."
RESTART_REASON = "Reset after an API restart interrupted processing."

_FIXED: dict[str, ReasonCode] = {
    AWAITING_EXTRACTION_REASON: "awaiting_extraction",
    EXTRACTION_OFF_REASON: "extraction_off",
    BUDGET_REASON: "daily_budget",
    INTERNAL_ERROR_REASON: "internal_error",
    RESTART_REASON: "restarted",
}
_FAILED_CHECKS = re.compile(r"Failed checks: ([a-z_]+(?:, [a-z_]+)*)\.")


def failed_checks_reason(check_types: Sequence[str]) -> str:
    """Why an invoice is blocked or failed: "Failed checks: iban, po_match."."""
    return "Failed checks: " + ", ".join(check_types) + "."


def reason_code(reason: str | None) -> tuple[ReasonCode | None, list[str]]:
    """The code of a reason written here and, for failed checks, their types; else (None, [])."""
    if reason is None:
        return None, []
    if code := _FIXED.get(reason):
        return code, []
    if match := _FAILED_CHECKS.fullmatch(reason):
        return "failed_checks", match.group(1).split(", ")
    return None, []
