"""The numbers behind docs/results.md: normalisation, scoring, confidence and decision metrics."""

from datetime import date
from decimal import Decimal

import pytest
from invoiceguard_api.extraction import FieldConfidence

from invoiceguard_evals.metrics import (
    Decision,
    as_expected,
    auroc,
    confidence_summary,
    decision_summary,
    normalise,
    percentile,
    score,
)
from invoiceguard_evals.specs import ALL, truth

TRUTH = truth(ALL[0])


@pytest.mark.parametrize(
    ("term", "a", "b"),
    [
        ("net_total", Decimal("100.00"), Decimal("100")),
        ("payee_iban", "DE17 1234 5678 0000 0000 01", "de17123456780000000001"),
        ("seller_vat_id", "DE 999000017", "DE999000017"),
        ("seller_name", "Muster  Bürobedarf\nGmbH", "Muster Bürobedarf GmbH"),
        ("currency", "eur", "EUR"),
        ("unit_code", "H87", "C62"),
        # A full-width M (NFKC folds it), as an escape so the source stays ASCII.
        ("seller_name", "\N{FULLWIDTH LATIN CAPITAL LETTER M}uster", "Muster"),
    ],
)
def test_equal_after_normalising(term: str, a: object, b: object) -> None:
    assert normalise(term, a) == normalise(term, b)


@pytest.mark.parametrize(
    ("term", "a", "b"),
    [
        ("net_total", Decimal("100.00"), Decimal("100.01")),
        ("seller_name", "Muster GmbH", "muster gmbh"),
        ("unit_code", "HUR", "C62"),
        ("due_date", date(2026, 1, 1), None),
    ],
)
def test_different_after_normalising(term: str, a: object, b: object) -> None:
    assert normalise(term, a) != normalise(term, b)


def test_a_perfect_extraction_scores_every_term_right() -> None:
    fields, lines = score(TRUTH, TRUTH)

    assert all(f.correct for f in fields)
    assert [line.correct for line in lines] == [True, True]


def test_wrong_terms_carry_their_confidence() -> None:
    wrong = TRUTH.model_copy(update={"payee_iban": "DE00000000000000000000"})
    confidences = [FieldConfidence("payee_iban", "BT-84", None, Decimal("0.9"), None)]

    fields, _ = score(TRUTH, wrong, confidences)

    (bad,) = [f for f in fields if not f.correct]
    assert (bad.term, bad.expected, bad.actual, bad.confidence) == (
        "payee_iban",
        TRUTH.payee_iban,
        "DE00000000000000000000",
        Decimal("0.9"),
    )


def test_missing_lines_and_failed_extractions_score_wrong() -> None:
    one_line = TRUTH.model_copy(update={"lines": TRUTH.lines[:1]})

    fields, lines = score(TRUTH, one_line)
    assert [line.correct for line in lines] == [True, False]
    assert not any(f.correct for f in fields if f.line_no == 2)

    fields, lines = score(TRUTH, None)
    assert not any(f.correct for f in fields)
    assert not any(line.correct for line in lines)


def test_auroc() -> None:
    assert auroc([(Decimal(1), True), (Decimal("0.5"), False)]) == 1.0
    assert auroc([(Decimal("0.5"), True), (Decimal(1), False)]) == 0.0
    assert auroc([(Decimal(1), True), (Decimal(1), False)]) == 0.5
    assert auroc([(Decimal(1), True)]) is None


def test_confidence_summary_counts_confident_errors() -> None:
    pairs = [
        (Decimal(1), True),
        (Decimal(1), False),
        (Decimal("0.85"), False),
        (Decimal("0.3"), False),
    ]

    summary = confidence_summary(pairs, Decimal("0.8"))

    assert (summary["errors"], summary["confident_errors"]) == (3, 2)
    buckets = {b["range"]: (b["fields"], b["accuracy"]) for b in summary["buckets"]}
    assert buckets["1.0"] == (2, 0.5)
    assert buckets["0.8-<0.9"] == (1, 0.0)
    assert buckets["0-<0.5"] == (1, 0.0)
    assert buckets["0.95-<1"] == (0, None)


def test_percentile() -> None:
    assert percentile([], 0.5) is None
    assert percentile([3.0, 1.0, 2.0], 0.5) == 2.0
    assert percentile([float(n) for n in range(1, 21)], 0.95) == 19.0


def _decision(
    case: str,
    status: str,
    flags: set[str],
    expected: str,
    expected_flags: set[str],
    fraud: str | None = None,
    primary: str | None = None,
) -> Decision:
    return Decision(
        case, "xml", status, frozenset(flags), expected, frozenset(expected_flags), fraud, primary
    )


def test_decision_summary() -> None:
    decisions = [
        _decision("clean", "ready", set(), "ready", set()),
        _decision("noisy", "blocked", {"po_match"}, "ready", set()),
        _decision("iban", "blocked", {"iban"}, "blocked", {"iban"}, "changed_iban", "iban"),
        _decision("missed", "ready", set(), "blocked", {"vat_math"}, "changed_totals", "vat_math"),
    ]

    summary = decision_summary(decisions)

    assert (summary["as_expected"], summary["clean_blocked"], summary["clean_flagged"]) == (2, 1, 1)
    assert summary["fraud_types"]["changed_iban"] == {
        "cases": 1,
        "flagged": 1,
        "blocked": 1,
        "as_expected": 1,
    }
    assert summary["fraud_types"]["changed_totals"]["flagged"] == 0
    assert summary["checks"]["po_match"]["precision"] == 0.0
    assert summary["checks"]["vat_math"]["recall"] == 0.0
    assert summary["checks"]["iban"]["precision"] == 1.0
    assert not as_expected(decisions[1])
