"""Compare extracted invoices with the truth, and summarise results (ADR-019).

Pure functions over plain data, so every number in `docs/results.md` can be unit-tested.
"""

import math
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from invoiceguard_api.extraction import FieldConfidence
from invoiceguard_api.parsing import ParsedInvoice
from invoiceguard_api.parsing.fields import DOCUMENT_TERMS, LINE_TERMS

# "Document accuracy": every one of these terms right (PLAN section 6, mandatory fields).
KEY_TERMS = (
    "invoice_number",
    "issue_date",
    "seller_name",
    "seller_vat_id",
    "payee_iban",
    "net_total",
    "tax_total",
    "gross_total",
    "amount_due",
)
COMPACT_TERMS = {"payee_iban", "seller_vat_id", "buyer_vat_id"}
CODE_TERMS = {"type_code", "currency", "unit_code"}
# Rec. 20 has two codes for a piece; a printed "Stk" cannot tell them apart, and the extraction
# prompt asks for C62, while many XML writers use H87.
SAME_UNIT = {"H87": "C62"}
# Upper bounds of the confidence buckets; the last one holds exactly 1.0.
BUCKETS = (Decimal("0.5"), Decimal("0.8"), Decimal("0.9"), Decimal("0.95"), Decimal(1))


def normalise(term: str, value: Any) -> Any:
    """Decimals compare by value (100.00 == 100); text after NFKC with whitespace collapsed;
    IBAN and VAT IDs without spaces; codes in upper case."""
    if value is None or isinstance(value, Decimal | date):
        return value
    text = " ".join(unicodedata.normalize("NFKC", str(value)).split())
    if term in COMPACT_TERMS:
        return text.replace(" ", "").upper()
    if term in CODE_TERMS:
        code = text.upper()
        return SAME_UNIT.get(code, code) if term == "unit_code" else code
    return text


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else str(value)


@dataclass(frozen=True)
class FieldScore:
    """One term of one invoice: document terms by name, line terms as "line.<term>"."""

    term: str
    line_no: int | None
    expected: str | None
    actual: str | None
    correct: bool
    confidence: Decimal | None


@dataclass(frozen=True)
class LineScore:
    """A whole line: right when every line term is right. The model gives one confidence per
    line, so the confidence analysis counts a line once, not once per term."""

    line_no: int
    correct: bool
    confidence: Decimal | None


def score(
    expected: ParsedInvoice,
    actual: ParsedInvoice | None,
    confidences: Sequence[FieldConfidence] = (),
) -> tuple[list[FieldScore], list[LineScore]]:
    """Every document term and every expected line term, by position. A failed extraction
    (`actual` None) scores every term wrong; missing lines score their terms wrong."""
    by_name = {c.name: c.confidence for c in confidences}
    fields = []
    for term in DOCUMENT_TERMS:
        want = getattr(expected, term)
        got = None if actual is None else getattr(actual, term)
        fields.append(
            FieldScore(
                term,
                None,
                _text(want),
                _text(got),
                actual is not None and normalise(term, want) == normalise(term, got),
                by_name.get(term),
            )
        )
    lines = []
    actual_lines = () if actual is None else actual.lines
    for n, want_line in enumerate(expected.lines, start=1):
        got_line = actual_lines[n - 1] if n <= len(actual_lines) else None
        confidence = by_name.get(f"line {n}")
        line_fields = []
        for term in LINE_TERMS:
            want = getattr(want_line, term)
            got = None if got_line is None else getattr(got_line, term)
            line_fields.append(
                FieldScore(
                    f"line.{term}",
                    n,
                    _text(want),
                    _text(got),
                    got_line is not None and normalise(term, want) == normalise(term, got),
                    confidence,
                )
            )
        fields += line_fields
        lines.append(LineScore(n, all(f.correct for f in line_fields), confidence))
    return fields, lines


def ratio(part: int, whole: int) -> float | None:
    return None if whole == 0 else part / whole


def percentile(values: Sequence[float], share: float) -> float | None:
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def auroc(pairs: Sequence[tuple[Decimal, bool]]) -> float | None:
    """The chance that a right field has a higher confidence than a wrong one (ties count
    half). 0.5 is no better than a coin; None when there are no errors or no right fields."""
    right = [c for c, ok in pairs if ok]
    wrong = [c for c, ok in pairs if not ok]
    if not right or not wrong:
        return None
    wins = sum(1.0 if r > w else 0.5 if r == w else 0.0 for r in right for w in wrong)
    return wins / (len(right) * len(wrong))


def confidence_summary(pairs: Sequence[tuple[Decimal, bool]], threshold: Decimal) -> dict[str, Any]:
    """Accuracy per bucket, errors at or above the `low_confidence` threshold, and AUROC."""
    buckets = []
    lower = Decimal(0)
    for upper in BUCKETS:
        if upper == 1:
            inside = [ok for c, ok in pairs if lower <= c < 1]
            buckets.append(_bucket(f"{lower}-<1", inside))
            buckets.append(_bucket("1.0", [ok for c, ok in pairs if c == 1]))
        else:
            buckets.append(
                _bucket(f"{lower}-<{upper}", [ok for c, ok in pairs if lower <= c < upper])
            )
        lower = upper
    errors = [c for c, ok in pairs if not ok]
    return {
        "fields": len(pairs),
        "errors": len(errors),
        "confident_errors": sum(1 for c in errors if c >= threshold),
        "threshold": str(threshold),
        "auroc": auroc(pairs),
        "buckets": buckets,
    }


def _bucket(label: str, outcomes: list[bool]) -> dict[str, Any]:
    return {
        "range": label,
        "fields": len(outcomes),
        "accuracy": ratio(sum(outcomes), len(outcomes)),
    }


@dataclass(frozen=True)
class Decision:
    """What processing decided for one fraud-set case."""

    case_id: str
    variant: str
    status: str
    flags: frozenset[str]
    expected_status: str
    expected_flags: frozenset[str]
    fraud_type: str | None
    primary_check: str | None


def decision_summary(decisions: Sequence[Decision]) -> dict[str, Any]:
    """Per fraud type: flagged and blocked. Per check: precision and recall over the whole set,
    clean invoices included. Any flag not in the expected set is a false positive."""
    by_type: dict[str, list[Decision]] = defaultdict(list)
    for decision in decisions:
        by_type[decision.fraud_type or "clean"].append(decision)
    fraud_types = {
        name: {
            "cases": len(cases),
            "flagged": sum(1 for d in cases if d.primary_check in d.flags),
            "blocked": sum(1 for d in cases if d.status == "blocked"),
            "as_expected": sum(1 for d in cases if as_expected(d)),
        }
        for name, cases in sorted(by_type.items())
        if name != "clean"
    }
    clean = by_type.get("clean", [])
    checks = sorted({c for d in decisions for c in d.flags | d.expected_flags})
    per_check = {}
    for check in checks:
        tp = sum(1 for d in decisions if check in d.flags and check in d.expected_flags)
        fp = sum(1 for d in decisions if check in d.flags and check not in d.expected_flags)
        fn = sum(1 for d in decisions if check not in d.flags and check in d.expected_flags)
        per_check[check] = {
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": ratio(tp, tp + fp),
            "recall": ratio(tp, tp + fn),
        }
    return {
        "cases": len(decisions),
        "as_expected": sum(1 for d in decisions if as_expected(d)),
        "clean_cases": len(clean),
        "clean_blocked": sum(1 for d in clean if d.status == "blocked"),
        "clean_flagged": sum(1 for d in clean if d.flags),
        "fraud_types": fraud_types,
        "checks": per_check,
    }


def as_expected(decision: Decision) -> bool:
    return decision.status == decision.expected_status and decision.flags == decision.expected_flags
