"""VAT math: the invoice's own totals must add up (EN 16931 BR-CO-10 to BR-CO-17, simplified).

Every rule compares two amounts with a tolerance of one cent and is only applied when the
invoice carries the terms it needs (a MINIMUM profile has no lines, for example).
"""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from invoiceguard_api.checks.model import TOLERANCE, CheckContext, CheckResult
from invoiceguard_api.models import CheckStatus
from invoiceguard_api.parsing import ParsedInvoice

CHECK_TYPE = "vat_math"
CENT = Decimal("0.01")
ZERO = Decimal("0")


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _rate_key(rate: Decimal | None) -> str:
    # 19, 19.0 and 19.00 are the same rate.
    return "none" if rate is None else str(rate.normalize())


class _Rules:
    def __init__(self) -> None:
        self.checked: list[str] = []
        self.differences: list[dict[str, Any]] = []

    def compare(self, rule: str, expected: Decimal, actual: Decimal) -> None:
        self.checked.append(rule)
        if abs(expected - actual) > TOLERANCE:
            self.differences.append(
                {
                    "rule": rule,
                    "expected": str(expected),
                    "actual": str(actual),
                    "difference": str(actual - expected),
                }
            )


def _per_rate_rules(rules: _Rules, invoice: ParsedInvoice) -> None:
    for group in invoice.vat_breakdown:
        if group.rate is not None:
            rules.compare(
                f"tax for rate {_rate_key(group.rate)}% = taxable amount x rate",
                _cents(group.taxable_amount * group.rate / 100),
                group.tax_amount,
            )
    rules.compare(
        "sum of tax per rate = tax total",
        sum((group.tax_amount for group in invoice.vat_breakdown), ZERO),
        invoice.tax_total or ZERO,
    )
    rules.compare(
        "sum of taxable amounts = net total",
        sum((group.taxable_amount for group in invoice.vat_breakdown), ZERO),
        invoice.net_total,
    )
    # Document-level allowances and charges move taxable amounts between rates; we do not read
    # their rates, so the line-to-rate rule is only applied without them.
    if not invoice.lines or invoice.allowance_total or invoice.charge_total:
        return
    lines_by_rate: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for line in invoice.lines:
        lines_by_rate[_rate_key(line.vat_rate)] += line.net_amount
    taxable_by_rate: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for group in invoice.vat_breakdown:
        taxable_by_rate[_rate_key(group.rate)] += group.taxable_amount
    for rate in sorted(lines_by_rate.keys() | taxable_by_rate.keys()):
        rules.compare(
            f"line amounts at rate {rate}% = taxable amount at that rate",
            lines_by_rate[rate],
            taxable_by_rate[rate],
        )


def check(context: CheckContext) -> CheckResult:
    invoice = context.invoice
    rules = _Rules()
    if invoice.lines and invoice.line_total is not None:
        rules.compare(
            "sum of line amounts = line total (BT-106)",
            sum((line.net_amount for line in invoice.lines), ZERO),
            invoice.line_total,
        )
    if invoice.line_total is not None:
        rules.compare(
            "line total - allowances + charges = net total (BT-109)",
            invoice.line_total - (invoice.allowance_total or ZERO) + (invoice.charge_total or ZERO),
            invoice.net_total,
        )
    rules.compare(
        "net total + tax total = gross total (BT-112)",
        invoice.net_total + (invoice.tax_total or ZERO),
        invoice.gross_total,
    )
    if invoice.vat_breakdown:
        _per_rate_rules(rules, invoice)

    evidence = {
        "tolerance": str(TOLERANCE),
        "checked": rules.checked,
        "differences": rules.differences,
    }
    if rules.differences:
        names = "; ".join(difference["rule"] for difference in rules.differences)
        return CheckResult(
            CHECK_TYPE, CheckStatus.FAILED, f"The amounts do not add up: {names}.", evidence
        )
    return CheckResult(
        CHECK_TYPE,
        CheckStatus.PASSED,
        f"All {len(rules.checked)} amount rules add up (tolerance {TOLERANCE}).",
        evidence,
    )
