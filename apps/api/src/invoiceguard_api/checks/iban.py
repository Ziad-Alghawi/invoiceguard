"""Payee IBAN (BT-84) against the supplier registry: the main defence against bank-detail fraud.

A changed IBAN on an otherwise normal invoice is the classic "CEO fraud" / invoice redirection
pattern, so a mismatch with every verified account is a hard failure (status `blocked`, PLAN
section 5). A missing payee IBAN (direct debit, card payment) is its own warning, not a
mismatch (ADR-005).
"""

import re

from invoiceguard_api.checks.model import CheckContext, CheckResult
from invoiceguard_api.models import CheckStatus

CHECK_TYPE = "iban"
NO_PAYEE_IBAN = "no_payee_iban"
MULTIPLE_PAYEE_IBANS = "multiple_payee_ibans"
_IBAN_SHAPE = re.compile(r"[A-Z]{2}[0-9]{2}[0-9A-Z]{11,30}")


def normalise_iban(iban: str) -> str:
    return iban.replace(" ", "").upper()


def iban_checksum_ok(iban: str) -> bool:
    """ISO 13616 check digits: move the first four characters to the end, letters to numbers
    (A=10 ... Z=35), and the result mod 97 must be 1."""
    iban = normalise_iban(iban)
    if not _IBAN_SHAPE.fullmatch(iban):
        return False
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(char, 36)) for char in rearranged)
    return int(digits) % 97 == 1


def _registry_check(context: CheckContext, iban: str) -> CheckResult:
    evidence: dict[str, object] = {"invoice_iban": iban}
    if not iban_checksum_ok(iban):
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.FAILED,
            f"Payee IBAN {iban} is not a valid IBAN (wrong format or check digits).",
            evidence,
        )
    supplier = context.supplier
    if supplier is None:
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.WARNING,
            "Payee IBAN cannot be compared: the supplier is not in the registry.",
            evidence,
        )
    verified = [
        {
            "iban": account.iban,
            "since": account.since.isoformat(),
            "verified_by": account.verified_by,
        }
        for account in supplier.verified_ibans
    ]
    evidence |= {
        "supplier_id": str(supplier.id),
        "supplier_name": supplier.name,
        "verified_ibans": verified,
    }
    if not verified:
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.WARNING,
            f"{supplier.name} has no verified bank account in the registry.",
            evidence,
        )
    if any(normalise_iban(account.iban) == iban for account in supplier.verified_ibans):
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.PASSED,
            f"Payee IBAN matches a verified account of {supplier.name}.",
            evidence,
        )
    return CheckResult(
        CHECK_TYPE,
        CheckStatus.FAILED,
        f"Payee IBAN {iban} is not a verified account of {supplier.name}: possible bank-detail "
        "fraud. Do not pay; confirm the account with the supplier through a known contact.",
        evidence,
    )


def check(context: CheckContext) -> list[CheckResult]:
    invoice = context.invoice
    if invoice.payee_iban is None:
        return [
            CheckResult(
                NO_PAYEE_IBAN,
                CheckStatus.WARNING,
                "The invoice names no payee IBAN (BT-84), for example because it is paid by "
                "direct debit; check how it will be paid.",
                {},
            )
        ]
    results = [_registry_check(context, normalise_iban(invoice.payee_iban))]
    multiple = [warning for warning in invoice.warnings if warning.startswith(MULTIPLE_PAYEE_IBANS)]
    if multiple:
        results.append(
            CheckResult(
                MULTIPLE_PAYEE_IBANS,
                CheckStatus.WARNING,
                "The invoice names more than one payee IBAN; only the first was checked.",
                {"parser_warnings": multiple},
            )
        )
    return results
