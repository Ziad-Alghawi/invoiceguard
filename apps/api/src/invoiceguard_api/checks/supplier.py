"""Supplier known: the seller's VAT ID (BT-31) is in the supplier master data."""

import re

from invoiceguard_api.checks.model import CheckContext, CheckResult
from invoiceguard_api.models import CheckStatus

CHECK_TYPE = "supplier_known"


def normalise_vat_id(vat_id: str) -> str:
    """'de 999 000 017' and 'DE999000017' are the same VAT ID."""
    return re.sub(r"[^0-9A-Z]", "", vat_id.upper())


def check(context: CheckContext) -> CheckResult:
    invoice = context.invoice
    evidence = {"seller_name": invoice.seller_name, "seller_vat_id": invoice.seller_vat_id}
    if invoice.seller_vat_id is None:
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.WARNING,
            "Unknown supplier: the invoice has no seller VAT ID (BT-31) to match.",
            evidence,
        )
    supplier = context.supplier
    if supplier is None:
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.WARNING,
            f"Unknown supplier: VAT ID {invoice.seller_vat_id} is not in the supplier master data.",
            evidence,
        )
    return CheckResult(
        CHECK_TYPE,
        CheckStatus.PASSED,
        f"Known supplier {supplier.name} ({supplier.vat_id}).",
        {**evidence, "supplier_id": str(supplier.id), "supplier_name": supplier.name},
    )
