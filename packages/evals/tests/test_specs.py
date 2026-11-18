"""The generated set: specs add up, the committed files are current, and every UBL twin reads back
to exactly the truth, so the truth is what both documents state."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from invoiceguard_api.checks.iban import iban_checksum_ok
from invoiceguard_api.parsing import read_invoice_xml

from invoiceguard_evals import specs
from invoiceguard_evals.datasets import GENERATED_DIR, generated_files, write_generated
from invoiceguard_evals.render import grouped_iban, money, number
from invoiceguard_evals.specs import ALL, InvoiceSpec, iban, truth
from invoiceguard_evals.ubl import to_ubl

IDS = [spec.case_id for spec in ALL]


@pytest.mark.parametrize("spec", ALL, ids=IDS)
def test_ubl_twin_reads_back_to_the_truth(spec: InvoiceSpec) -> None:
    parsed = read_invoice_xml(to_ubl(spec))

    assert parsed.model_copy(update={"syntax": "pdf"}) == truth(spec)


@pytest.mark.parametrize("spec", ALL, ids=IDS)
def test_committed_files_are_current(spec: InvoiceSpec) -> None:
    """Run `invoiceguard-eval generate` after changing a spec or the renderer."""
    for name, content in generated_files(spec).items():
        assert (GENERATED_DIR / name).read_bytes() == content, name


def test_write_generated_writes_three_files_per_spec(tmp_path: Path) -> None:
    assert write_generated(tmp_path) == 3 * len(ALL)
    assert sorted(p.name for p in tmp_path.iterdir())[:3] == [
        "c01_order_note.pdf",
        "c01_order_note.truth.json",
        "c01_order_note.ubl.xml",
    ]


def test_every_iban_has_valid_check_digits() -> None:
    assert all(iban_checksum_ok(spec.iban) for spec in ALL)
    assert all(
        iban_checksum_ok(c.decoy) for spec in ALL for c in spec.conflicts if c.term == "payee_iban"
    )
    assert iban("DE", "370400440532013000") == "DE89370400440532013000"


def test_totals_add_up_except_for_the_changed_totals_fraud() -> None:
    for spec in ALL:
        invoice = truth(spec)
        difference = invoice.gross_total - (invoice.net_total + (invoice.tax_total or 0))
        assert difference == spec.gross_tamper, spec.case_id
    assert specs.FRAUD[2].gross_tamper == Decimal("100.00")


def test_a_discount_needs_a_single_rate() -> None:
    mixed = next(spec for spec in ALL if spec.case_id == "g06_mixed_rates")
    with pytest.raises(ValueError, match="single VAT rate"):
        replace(mixed, discount_percent=Decimal(5)).vat_breakdown()


def test_ids_are_unique_and_the_duplicate_follows_its_original() -> None:
    assert len(set(IDS)) == len(IDS)
    assert IDS.index("g01_buerobedarf_classic") < IDS.index("f04_duplicate_number")


def test_german_number_formats() -> None:
    assert money(Decimal("1234.5")) == "1.234,50"
    assert number(Decimal("19.00")) == "19"
    assert number(Decimal("7.5")) == "7,5"
    assert grouped_iban("DE17123456780000000001") == "DE17 1234 5678 0000 0000 01"
