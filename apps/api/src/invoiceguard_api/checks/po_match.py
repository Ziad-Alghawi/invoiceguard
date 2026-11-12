"""Purchase-order match: the invoice references an order (BT-13) of the same supplier, and does
not charge more than was ordered.

Invoice lines are paired with order lines by position (first with first, ...). That is fragile
when a supplier reorders or splits lines; matching by item ID (BT-155/BT-156) or by the order
line reference (BT-132) is the planned improvement (README, known limitations).

Severity: charging more than ordered (higher total, price, quantity, or lines not on the order)
or an order of another supplier → failed. Charging less (partial delivery, lower price) or a
missing or unknown order reference → warning.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from invoiceguard_api.checks.model import TOLERANCE, CheckContext, CheckResult, Order
from invoiceguard_api.models import CheckStatus
from invoiceguard_api.parsing import ParsedInvoice

CHECK_TYPE = "po_match"
CENT = Decimal("0.01")


def _order_net(order: Order) -> Decimal:
    return sum(
        ((line.quantity * line.unit_price).quantize(CENT, ROUND_HALF_UP) for line in order.lines),
        Decimal("0"),
    )


def _difference(
    severity: CheckStatus, what: str, line: int | None, ordered: object, invoiced: object
) -> dict[str, Any]:
    return {
        "severity": severity.value,
        "what": what,
        "line": line,
        "ordered": None if ordered is None else str(ordered),
        "invoiced": None if invoiced is None else str(invoiced),
    }


def _line_differences(invoice: ParsedInvoice, order: Order) -> list[dict[str, Any]]:
    differences = []
    for position in range(max(len(invoice.lines), len(order.lines))):
        line_no = position + 1
        if position >= len(order.lines):
            line = invoice.lines[position]
            differences.append(
                _difference(
                    CheckStatus.FAILED, "line not on the order", line_no, None, line.item_name
                )
            )
            continue
        ordered = order.lines[position]
        if position >= len(invoice.lines):
            differences.append(
                _difference(
                    CheckStatus.WARNING,
                    "ordered line not invoiced",
                    line_no,
                    ordered.description,
                    None,
                )
            )
            continue
        line = invoice.lines[position]
        if line.unit_code != ordered.unit_code:
            differences.append(
                _difference(CheckStatus.FAILED, "unit", line_no, ordered.unit_code, line.unit_code)
            )
        for what, ordered_value, invoiced_value, tolerance in (
            ("unit price", ordered.unit_price, line.net_price, TOLERANCE),
            ("quantity", ordered.quantity, line.quantity, Decimal("0")),
        ):
            if invoiced_value - ordered_value > tolerance:
                severity = CheckStatus.FAILED
            elif ordered_value - invoiced_value > tolerance:
                severity = CheckStatus.WARNING
            else:
                continue
            differences.append(_difference(severity, what, line_no, ordered_value, invoiced_value))
    return differences


def check(context: CheckContext) -> CheckResult:
    invoice = context.invoice
    reference = invoice.order_reference
    if reference is None:
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.WARNING,
            "The invoice has no order reference (BT-13); it cannot be matched to an order.",
            {},
        )
    order = context.order
    if order is None:
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.WARNING,
            f"Order {reference} is not in the order data.",
            {"order_reference": reference},
        )

    evidence: dict[str, Any] = {
        "order_reference": reference,
        "order_id": str(order.id),
        "tolerance": str(TOLERANCE),
        "line_pairing": "by position",
    }
    supplier = context.supplier
    if supplier is None or supplier.id != order.supplier_id:
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.FAILED,
            f"Order {reference} belongs to another supplier than the seller of this invoice.",
            evidence,
        )

    order_net = _order_net(order)
    differences: list[dict[str, Any]] = []
    if invoice.currency != order.currency:
        differences.append(
            _difference(CheckStatus.FAILED, "currency", None, order.currency, invoice.currency)
        )
    if invoice.net_total - order_net > TOLERANCE:
        differences.append(
            _difference(CheckStatus.FAILED, "net total", None, order_net, invoice.net_total)
        )
    elif order_net - invoice.net_total > TOLERANCE:
        differences.append(
            _difference(CheckStatus.WARNING, "net total", None, order_net, invoice.net_total)
        )
    if invoice.lines:
        differences.extend(_line_differences(invoice, order))
    evidence |= {
        "ordered_net": str(order_net),
        "invoiced_net": str(invoice.net_total),
        "differences": differences,
    }

    failed = [d["what"] for d in differences if d["severity"] == CheckStatus.FAILED.value]
    if failed:
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.FAILED,
            f"The invoice does not match order {reference}: {', '.join(dict.fromkeys(failed))}.",
            evidence,
        )
    if differences:
        what = ", ".join(dict.fromkeys(d["what"] for d in differences))
        return CheckResult(
            CHECK_TYPE,
            CheckStatus.WARNING,
            f"The invoice charges less than order {reference} (partial delivery?): {what}.",
            evidence,
        )
    return CheckResult(
        CHECK_TYPE, CheckStatus.PASSED, f"The invoice matches order {reference}.", evidence
    )
