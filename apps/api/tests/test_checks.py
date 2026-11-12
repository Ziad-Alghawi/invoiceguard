"""Unit tests for the checks: pure functions of a CheckContext built from the samples and the
demo seed's suppliers and orders, without a database or a validator."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from invoiceguard_api.checks import (
    duplicate,
    final_status,
    iban,
    kosit,
    po_match,
    run_checks,
    summarise,
    supplier,
    vat,
)
from invoiceguard_api.checks.model import (
    CheckContext,
    CheckResult,
    KnownSupplier,
    Order,
    OrderLine,
    OtherInvoice,
    Validation,
    ValidationMessage,
    VerifiedIban,
)
from invoiceguard_api.models import CheckStatus, InvoiceStatus, SourceType
from invoiceguard_api.parsing import ParsedInvoice, ParsedLine, VatBreakdown, parse_invoice
from invoiceguard_api.seed import ORDERS, SUPPLIERS, VERIFIED_BY

# Demo IT-Service GmbH and its order PO-2026-0005, which ubl_xrechnung.xml invoices.
IT_SERVICE_VAT_ID = "DE999000033"
IT_SERVICE_IBAN = "DE60123456780000000003"
# Fictitious (fake bank code), as in ubl_fraud_iban.xml; not a secret.
FRAUD_IBAN = "DE58876543210000000099"  # pragma: allowlist secret
NOT_VALIDATED = Validation(outcome="unavailable", reason="not configured in this test")


def _supplier_id(vat_id: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, vat_id)


def seeded_supplier(vat_id: str) -> KnownSupplier:
    seed = next(s for s in SUPPLIERS if s.vat_id == vat_id)
    return KnownSupplier(
        id=_supplier_id(vat_id),
        name=seed.name,
        vat_id=seed.vat_id,
        verified_ibans=(VerifiedIban(seed.iban, seed.iban_verified_since, VERIFIED_BY),),
    )


def seeded_order(number: str) -> Order:
    seed = next(o for o in ORDERS if o.number == number)
    return Order(
        id=uuid.uuid5(uuid.NAMESPACE_URL, number),
        number=seed.number,
        supplier_id=_supplier_id(seed.supplier_vat_id),
        currency="EUR",
        lines=tuple(
            OrderLine(position, line.description, line.quantity, line.unit_code, line.unit_price)
            for position, line in enumerate(seed.lines, start=1)
        ),
    )


@pytest.fixture
def clean(samples: dict[str, bytes]) -> ParsedInvoice:
    return parse_invoice(samples["ubl_xrechnung"], SourceType.XML)


def context(invoice: ParsedInvoice, **changes: Any) -> CheckContext:
    """The context the database would give for this invoice after `make seed`."""
    if "supplier" not in changes:
        vat_id = invoice.seller_vat_id
        changes["supplier"] = seeded_supplier(vat_id) if vat_id else None
    if "order" not in changes:
        reference = invoice.order_reference
        changes["order"] = seeded_order(reference) if reference else None
    return CheckContext(
        **{"invoice": invoice, "validation": NOT_VALIDATED, "other_invoices": (), **changes}
    )


def changed(invoice: ParsedInvoice, **update: Any) -> ParsedInvoice:
    return invoice.model_copy(update=update)


def line(invoice: ParsedInvoice, position: int, **update: Any) -> tuple[ParsedLine, ...]:
    lines = list(invoice.lines)
    lines[position] = lines[position].model_copy(update=update)
    return tuple(lines)


# --- The samples pass ---------------------------------------------------------------------------


@pytest.mark.parametrize("sample", ["ubl_xrechnung", "cii_xrechnung"])
def test_clean_samples_pass_every_check_but_kosit(samples: dict[str, bytes], sample: str) -> None:
    results = run_checks(context(parse_invoice(samples[sample], SourceType.XML)))

    assert {(r.type, r.status) for r in results} == {
        ("kosit", CheckStatus.SKIPPED),
        ("vat_math", CheckStatus.PASSED),
        ("duplicate", CheckStatus.PASSED),
        ("supplier_known", CheckStatus.PASSED),
        ("iban", CheckStatus.PASSED),
        ("po_match", CheckStatus.PASSED),
    }
    assert final_status(results) is InvoiceStatus.READY


def test_direct_debit_sample_warns_about_the_missing_payee_iban(
    samples: dict[str, bytes],
) -> None:
    results = run_checks(context(parse_invoice(samples["zugferd2_pdf"], SourceType.PDF)))

    statuses = {r.type: r.status for r in results}
    assert statuses["no_payee_iban"] is CheckStatus.WARNING
    assert "iban" not in statuses
    assert final_status(results) is InvoiceStatus.READY


def test_fraud_sample_fails_only_the_iban_check(samples: dict[str, bytes]) -> None:
    results = run_checks(context(parse_invoice(samples["ubl_fraud_iban"], SourceType.XML)))

    failed = [r for r in results if r.status is CheckStatus.FAILED]
    assert [r.type for r in failed] == ["iban"]
    assert final_status(results) is InvoiceStatus.BLOCKED


# --- KoSIT ------------------------------------------------------------------------------------


def _kosit(validation: Validation, invoice: ParsedInvoice) -> CheckResult:
    return kosit.check(context(invoice, validation=validation))


def test_kosit_accepted_passes(clean: ParsedInvoice) -> None:
    result = _kosit(Validation(outcome="accepted", scenario="EN16931 XRechnung (UBL)"), clean)

    assert result.status is CheckStatus.PASSED
    assert "EN16931 XRechnung (UBL)" in result.message


def test_kosit_accepted_with_rule_warnings_warns(clean: ParsedInvoice) -> None:
    messages = (
        ValidationMessage("information", "INFO-1", "fyi"),
        ValidationMessage("warning", "BR-DE-21", "should be"),
    )
    validation = Validation(outcome="accepted", scenario="X", messages=messages)

    result = _kosit(validation, clean)

    assert result.status is CheckStatus.WARNING
    assert result.message == "Valid (X), with 1 warning(s)."


def test_kosit_accepted_with_only_information_passes(clean: ParsedInvoice) -> None:
    validation = Validation(
        outcome="accepted", scenario="X", messages=(ValidationMessage("information", "I", "i"),)
    )

    assert _kosit(validation, clean).status is CheckStatus.PASSED


def test_kosit_rejected_fails_with_the_rule_codes(clean: ParsedInvoice) -> None:
    messages = tuple(ValidationMessage("error", f"BR-{n:02d}", "broken") for n in range(25))
    validation = Validation(outcome="rejected", scenario="X", messages=(*messages, messages[0]))

    result = _kosit(validation, clean)

    assert result.status is CheckStatus.FAILED
    assert result.message.startswith("The KoSIT validator rejected the invoice (BR-00, BR-01,")
    assert result.evidence["message_count"] == 26
    assert len(result.evidence["messages"]) == kosit.MAX_MESSAGES


def test_kosit_without_matching_scenario_warns(clean: ParsedInvoice) -> None:
    result = _kosit(Validation(outcome="no_scenario"), clean)

    assert result.status is CheckStatus.WARNING
    assert "no scenario" in result.message


def test_kosit_unavailable_is_skipped_with_the_reason(clean: ParsedInvoice) -> None:
    result = _kosit(Validation(outcome="unavailable", reason="connection refused"), clean)

    assert result == CheckResult(
        "kosit", CheckStatus.SKIPPED, "connection refused", {"reason": "connection refused"}
    )


# --- VAT math ---------------------------------------------------------------------------------


def _vat(invoice: ParsedInvoice) -> CheckResult:
    return vat.check(context(invoice))


def _broken_rules(result: CheckResult) -> list[str]:
    return [difference["rule"] for difference in result.evidence["differences"]]


def test_vat_math_passes_and_lists_the_rules(clean: ParsedInvoice) -> None:
    result = _vat(clean)

    assert result.status is CheckStatus.PASSED
    assert len(result.evidence["checked"]) == 7
    assert result.evidence["differences"] == []


def test_vat_math_allows_one_cent(clean: ParsedInvoice) -> None:
    result = _vat(changed(clean, gross_total=clean.gross_total + Decimal("0.01")))

    assert result.status is CheckStatus.PASSED


def test_vat_math_fails_on_two_cents(clean: ParsedInvoice) -> None:
    result = _vat(changed(clean, gross_total=Decimal("5137.25")))

    assert result.status is CheckStatus.FAILED
    assert result.evidence["differences"] == [
        {
            "rule": "net total + tax total = gross total (BT-112)",
            "expected": "5137.23",
            "actual": "5137.25",
            "difference": "0.02",
        }
    ]


def test_vat_math_fails_when_lines_do_not_add_up(clean: ParsedInvoice) -> None:
    result = _vat(changed(clean, lines=line(clean, 1, net_amount=Decimal("580.00"))))

    assert result.status is CheckStatus.FAILED
    assert _broken_rules(result) == [
        "sum of line amounts = line total (BT-106)",
        "line amounts at rate 19% = taxable amount at that rate",
    ]


def test_vat_math_fails_on_wrong_tax_for_a_rate(clean: ParsedInvoice) -> None:
    wrong = VatBreakdown(
        category_code="S",
        rate=Decimal("19"),
        taxable_amount=Decimal("4317.00"),
        tax_amount=Decimal("800.00"),
    )

    result = _vat(changed(clean, vat_breakdown=(wrong,)))

    assert result.status is CheckStatus.FAILED
    assert _broken_rules(result) == [
        "tax for rate 19% = taxable amount x rate",
        "sum of tax per rate = tax total",
    ]


def test_vat_math_checks_each_rate(clean: ParsedInvoice) -> None:
    # Line 2 at 7 %: 570.00 x 7 % = 39.90; line 1 at 19 %: 3747.00 x 19 % = 711.93.
    invoice = changed(
        clean,
        lines=line(clean, 1, vat_rate=Decimal("7.00")),
        vat_breakdown=(
            VatBreakdown(
                category_code="S",
                rate=Decimal("19"),
                taxable_amount=Decimal("3747.00"),
                tax_amount=Decimal("711.93"),
            ),
            VatBreakdown(
                category_code="S",
                rate=Decimal("7"),
                taxable_amount=Decimal("570.00"),
                tax_amount=Decimal("39.90"),
            ),
        ),
        tax_total=Decimal("751.83"),
        gross_total=Decimal("5068.83"),
    )

    result = _vat(invoice)

    assert result.status is CheckStatus.PASSED
    assert "line amounts at rate 7% = taxable amount at that rate" in result.evidence["checked"]


def test_vat_math_with_allowances_skips_the_line_to_rate_rule(clean: ParsedInvoice) -> None:
    # 4317.00 - 17.00 + 5.00 = 4305.00 net; 19 % = 817.95 tax.
    invoice = changed(
        clean,
        allowance_total=Decimal("17.00"),
        charge_total=Decimal("5.00"),
        net_total=Decimal("4305.00"),
        tax_total=Decimal("817.95"),
        gross_total=Decimal("5122.95"),
        vat_breakdown=(
            VatBreakdown(
                category_code="S",
                rate=Decimal("19"),
                taxable_amount=Decimal("4305.00"),
                tax_amount=Decimal("817.95"),
            ),
        ),
    )

    result = _vat(invoice)

    assert result.status is CheckStatus.PASSED
    assert not any("line amounts at rate" in rule for rule in result.evidence["checked"])


def test_vat_math_without_lines_and_breakdown_checks_the_totals(clean: ParsedInvoice) -> None:
    # A MINIMUM-profile invoice: totals only.
    invoice = changed(clean, lines=(), vat_breakdown=(), line_total=None)

    result = _vat(invoice)

    assert result.evidence["checked"] == ["net total + tax total = gross total (BT-112)"]


def test_vat_math_treats_a_missing_tax_total_as_zero(clean: ParsedInvoice) -> None:
    result = _vat(changed(clean, tax_total=None))

    assert result.status is CheckStatus.FAILED
    assert "net total + tax total = gross total (BT-112)" in _broken_rules(result)


def test_vat_math_skips_the_rate_rule_for_categories_without_rate(clean: ParsedInvoice) -> None:
    exempt = VatBreakdown(
        category_code="O", rate=None, taxable_amount=Decimal("4317.00"), tax_amount=Decimal("0")
    )
    invoice = changed(
        clean,
        lines=tuple(item.model_copy(update={"vat_rate": None}) for item in clean.lines),
        vat_breakdown=(exempt,),
        tax_total=Decimal("0"),
        gross_total=Decimal("4317.00"),
    )

    result = _vat(invoice)

    assert result.status is CheckStatus.PASSED
    assert "line amounts at rate none% = taxable amount at that rate" in result.evidence["checked"]


# --- Duplicate --------------------------------------------------------------------------------


def other(
    number: str = "2026-IT-0700", issue_date: date = date(2026, 11, 5), gross: str = "1.00"
) -> OtherInvoice:
    return OtherInvoice(
        id=uuid.uuid4(),
        invoice_number=number,
        issue_date=issue_date,
        gross_total=Decimal(gross),
        status="ready",
    )


def _duplicate(invoice: ParsedInvoice, *others: OtherInvoice) -> CheckResult:
    return duplicate.check(context(invoice, other_invoices=others))


def test_duplicate_passes_without_matches(clean: ParsedInvoice) -> None:
    result = _duplicate(clean, other())

    assert result.status is CheckStatus.PASSED
    assert result.evidence == {"compared_with": 1}


def test_duplicate_fails_on_the_same_number_written_differently(clean: ParsedInvoice) -> None:
    earlier = other(number=" 2026 it/0815", gross="99.00")

    result = _duplicate(clean, earlier)

    assert result.status is CheckStatus.FAILED
    assert str(earlier.id) in result.message
    assert result.evidence["match"] == "same_number"
    assert result.evidence["invoices"] == [
        {
            "invoice_id": str(earlier.id),
            "invoice_number": " 2026 it/0815",
            "issue_date": "2026-11-05",
            "gross_total": "99.00",
            "status": "ready",
        }
    ]


def test_duplicate_warns_on_same_amount_and_close_date(clean: ParsedInvoice) -> None:
    earlier = other(issue_date=clean.issue_date - timedelta(days=7), gross="5137.24")

    result = _duplicate(clean, earlier)

    assert result.status is CheckStatus.WARNING
    assert result.evidence["match"] == "similar_amount_and_date"


@pytest.mark.parametrize(
    "candidate",
    [
        other(issue_date=date(2026, 11, 13), gross="5137.23"),
        other(issue_date=date(2026, 11, 5), gross="5137.25"),
    ],
    ids=["eight-days-apart", "two-cents-apart"],
)
def test_duplicate_ignores_invoices_that_are_not_similar(
    clean: ParsedInvoice, candidate: OtherInvoice
) -> None:
    assert _duplicate(clean, candidate).status is CheckStatus.PASSED


# --- Supplier known ---------------------------------------------------------------------------


def test_supplier_known_passes_for_a_seeded_supplier(clean: ParsedInvoice) -> None:
    result = supplier.check(context(clean))

    assert result.status is CheckStatus.PASSED
    assert result.evidence["supplier_name"] == "Demo IT-Service GmbH"


def test_supplier_unknown_warns(clean: ParsedInvoice) -> None:
    result = supplier.check(context(clean, supplier=None))

    assert result.status is CheckStatus.WARNING
    assert result.message.startswith("Unknown supplier: VAT ID DE999000033")


def test_supplier_without_vat_id_warns(clean: ParsedInvoice) -> None:
    result = supplier.check(context(changed(clean, seller_vat_id=None)))

    assert result.status is CheckStatus.WARNING
    assert "no seller VAT ID" in result.message


def test_vat_ids_are_compared_without_spaces_and_case() -> None:
    assert supplier.normalise_vat_id(" de 999 000-033") == IT_SERVICE_VAT_ID


# --- IBAN ---------------------------------------------------------------------------------------


def _iban(invoice: ParsedInvoice, **changes: Any) -> list[CheckResult]:
    return iban.check(context(invoice, **changes))


@pytest.mark.parametrize(
    "value",
    [IT_SERVICE_IBAN, "GB82WEST12345698765432", "de60 1234 5678 0000 0000 03", FRAUD_IBAN],
)
def test_iban_checksum_accepts_valid_ibans(value: str) -> None:
    assert iban.iban_checksum_ok(value)


@pytest.mark.parametrize(
    "value", ["DE61123456780000000003", "DE60", "DE6012345678000000000X!", "6012345678000000000003"]
)
def test_iban_checksum_rejects_invalid_ibans(value: str) -> None:
    assert not iban.iban_checksum_ok(value)


def test_iban_matching_the_registry_passes(clean: ParsedInvoice) -> None:
    (result,) = _iban(changed(clean, payee_iban="de60 1234 5678 0000 0000 03"))

    assert result.status is CheckStatus.PASSED


def test_changed_iban_fails_with_the_registry_evidence(clean: ParsedInvoice) -> None:
    (result,) = _iban(changed(clean, payee_iban=FRAUD_IBAN))

    assert result.status is CheckStatus.FAILED
    assert "possible bank-detail fraud" in result.message
    assert result.evidence == {
        "invoice_iban": FRAUD_IBAN,
        "supplier_id": str(_supplier_id(IT_SERVICE_VAT_ID)),
        "supplier_name": "Demo IT-Service GmbH",
        "verified_ibans": [
            {"iban": IT_SERVICE_IBAN, "since": "2025-01-10", "verified_by": VERIFIED_BY}
        ],
    }


def test_iban_with_wrong_check_digits_fails(clean: ParsedInvoice) -> None:
    (result,) = _iban(changed(clean, payee_iban="DE61123456780000000003"))

    assert result.status is CheckStatus.FAILED
    assert "not a valid IBAN" in result.message


def test_no_payee_iban_is_its_own_warning(clean: ParsedInvoice) -> None:
    (result,) = _iban(changed(clean, payee_iban=None))

    assert (result.type, result.status) == ("no_payee_iban", CheckStatus.WARNING)


def test_iban_of_an_unknown_supplier_warns(clean: ParsedInvoice) -> None:
    (result,) = _iban(clean, supplier=None)

    assert result.status is CheckStatus.WARNING
    assert "not in the registry" in result.message


def test_iban_without_verified_accounts_warns(clean: ParsedInvoice) -> None:
    unverified = KnownSupplier(_supplier_id(IT_SERVICE_VAT_ID), "Demo", IT_SERVICE_VAT_ID, ())

    (result,) = _iban(clean, supplier=unverified)

    assert result.status is CheckStatus.WARNING
    assert "no verified bank account" in result.message


def test_several_payee_ibans_add_a_warning(clean: ParsedInvoice) -> None:
    invoice = changed(clean, warnings=("multiple_payee_ibans: 2 found, stored the first",))

    results = _iban(invoice)

    assert [(r.type, r.status) for r in results] == [
        ("iban", CheckStatus.PASSED),
        ("multiple_payee_ibans", CheckStatus.WARNING),
    ]


# --- PO match ---------------------------------------------------------------------------------


def _po(invoice: ParsedInvoice, **changes: Any) -> CheckResult:
    return po_match.check(context(invoice, **changes))


def _differences(result: CheckResult) -> list[tuple[str, str, int | None]]:
    return [(d["severity"], d["what"], d["line"]) for d in result.evidence["differences"]]


def test_po_match_passes_for_the_ordered_amounts(clean: ParsedInvoice) -> None:
    result = _po(clean)

    assert result.status is CheckStatus.PASSED
    assert result.evidence["ordered_net"] == "4317.00"
    assert result.evidence["line_pairing"] == "by position"


def test_po_match_without_reference_warns(clean: ParsedInvoice) -> None:
    result = _po(changed(clean, order_reference=None))

    assert result.status is CheckStatus.WARNING
    assert "no order reference" in result.message


def test_po_match_with_unknown_order_warns(clean: ParsedInvoice) -> None:
    result = _po(changed(clean, order_reference="PO-1999-0001"), order=None)

    assert result.status is CheckStatus.WARNING
    assert result.message == "Order PO-1999-0001 is not in the order data."


def test_po_of_another_supplier_fails(clean: ParsedInvoice) -> None:
    result = _po(changed(clean, order_reference="PO-2026-0001"))

    assert result.status is CheckStatus.FAILED
    assert "belongs to another supplier" in result.message


def test_po_match_with_unknown_seller_fails(clean: ParsedInvoice) -> None:
    assert _po(clean, supplier=None).status is CheckStatus.FAILED


def test_higher_price_fails_with_the_difference(clean: ParsedInvoice) -> None:
    invoice = changed(
        clean,
        lines=line(clean, 1, net_price=Decimal("99.00"), net_amount=Decimal("594.00")),
        net_total=Decimal("4341.00"),
    )

    result = _po(invoice)

    assert result.status is CheckStatus.FAILED
    assert _differences(result) == [
        ("failed", "net total", None),
        ("failed", "unit price", 2),
    ]
    unit_price = result.evidence["differences"][1]
    assert (unit_price["ordered"], unit_price["invoiced"]) == ("95.00", "99.00")


def test_higher_quantity_and_other_unit_fail(clean: ParsedInvoice) -> None:
    invoice = changed(clean, lines=line(clean, 0, quantity=Decimal("4"), unit_code="H87"))

    result = _po(invoice)

    assert result.status is CheckStatus.FAILED
    assert _differences(result) == [("failed", "unit", 1), ("failed", "quantity", 1)]


def test_line_not_on_the_order_fails(clean: ParsedInvoice) -> None:
    extra = clean.lines[1].model_copy(update={"line_id": "3", "item_name": "Schulung"})

    result = _po(changed(clean, lines=(*clean.lines, extra)))

    assert result.status is CheckStatus.FAILED
    assert ("failed", "line not on the order", 3) in _differences(result)


def test_partial_delivery_warns(clean: ParsedInvoice) -> None:
    invoice = changed(clean, lines=clean.lines[:1], net_total=Decimal("3747.00"))

    result = _po(invoice)

    assert result.status is CheckStatus.WARNING
    assert _differences(result) == [
        ("warning", "net total", None),
        ("warning", "ordered line not invoiced", 2),
    ]


def test_lower_quantity_warns(clean: ParsedInvoice) -> None:
    invoice = changed(clean, lines=line(clean, 0, quantity=Decimal("2")))

    result = _po(invoice)

    assert result.status is CheckStatus.WARNING
    assert _differences(result) == [("warning", "quantity", 1)]


def test_po_in_another_currency_fails(clean: ParsedInvoice) -> None:
    assert _po(changed(clean, currency="CHF")).status is CheckStatus.FAILED


def test_po_match_without_lines_compares_the_totals(clean: ParsedInvoice) -> None:
    result = _po(changed(clean, lines=()))

    assert result.status is CheckStatus.PASSED


def test_price_within_one_cent_passes(clean: ParsedInvoice) -> None:
    invoice = changed(clean, lines=line(clean, 1, net_price=Decimal("95.01")))

    assert _po(invoice).status is CheckStatus.PASSED


# --- Runner -----------------------------------------------------------------------------------


def test_any_failed_check_blocks() -> None:
    results = [
        CheckResult("a", CheckStatus.PASSED, ""),
        CheckResult("b", CheckStatus.WARNING, ""),
        CheckResult("c", CheckStatus.SKIPPED, ""),
    ]
    assert final_status(results) is InvoiceStatus.READY
    assert final_status([*results, CheckResult("d", CheckStatus.FAILED, "")]) is (
        InvoiceStatus.BLOCKED
    )


def test_summary_counts_every_status() -> None:
    results = [
        CheckResult("iban", CheckStatus.FAILED, ""),
        CheckResult("po_match", CheckStatus.FAILED, ""),
        CheckResult("vat_math", CheckStatus.PASSED, ""),
    ]

    assert summarise(results) == {
        "passed": 1,
        "warning": 0,
        "failed": 2,
        "skipped": 0,
        "failed_checks": ["iban", "po_match"],
    }
