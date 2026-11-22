"""The codes of the status reasons processing writes (ADR-027)."""

import pytest

from invoiceguard_api import status_reasons
from invoiceguard_api.status_reasons import failed_checks_reason, reason_code


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        (status_reasons.AWAITING_EXTRACTION_REASON, "awaiting_extraction"),
        (status_reasons.EXTRACTION_OFF_REASON, "extraction_off"),
        (status_reasons.BUDGET_REASON, "daily_budget"),
        (status_reasons.INTERNAL_ERROR_REASON, "internal_error"),
        (status_reasons.RESTART_REASON, "restarted"),
    ],
)
def test_fixed_reasons_have_a_code(reason: str, code: str) -> None:
    assert reason_code(reason) == (code, [])


def test_failed_checks_round_trip() -> None:
    assert failed_checks_reason(["iban"]) == "Failed checks: iban."
    for checks in (["iban"], ["po_match", "prompt_injection"]):
        assert reason_code(failed_checks_reason(checks)) == ("failed_checks", checks)


@pytest.mark.parametrize(
    "reason",
    [
        None,
        "Second try.",
        "Unknown invoice format: not UBL or CII.",
        "Failed checks: iban",
        "Failed checks: IBAN.",
        "Note: Failed checks: iban.",
    ],
)
def test_other_text_has_no_code(reason: str | None) -> None:
    assert reason_code(reason) == (None, [])
