"""The generated set: specs add up, the committed files are current, and every UBL twin reads back
to exactly the truth, so the truth is what both documents state."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from invoiceguard_api.checks.iban import iban_checksum_ok
from invoiceguard_api.demo import sample_invoices
from invoiceguard_api.parsing import read_invoice_xml
from invoiceguard_api.parsing.fields import DOCUMENT_TERMS

from invoiceguard_evals import specs
from invoiceguard_evals.attacks import ATTACKS
from invoiceguard_evals.datasets import (
    DEMO_DIR,
    GENERATED_DIR,
    demo_cases,
    demo_files,
    generated_files,
    write_demo,
    write_generated,
)
from invoiceguard_evals.render import grouped_iban, money, number
from invoiceguard_evals.specs import (
    ALL,
    InvoiceSpec,
    demo_sample,
    demo_spec,
    demo_specs,
    iban,
    truth,
)
from invoiceguard_evals.ubl import to_ubl

IDS = [spec.case_id for spec in ALL]


@pytest.mark.parametrize("spec", ALL, ids=IDS)
def test_ubl_twin_reads_back_to_the_truth(spec: InvoiceSpec) -> None:
    parsed = read_invoice_xml(to_ubl(spec))

    assert parsed.model_copy(update={"syntax": "pdf"}) == truth(spec)


@pytest.mark.parametrize("spec", (*ALL, *ATTACKS), ids=[*IDS, *(s.case_id for s in ATTACKS)])
def test_committed_files_are_current(spec: InvoiceSpec) -> None:
    """Run `invoiceguard-eval generate` after changing a spec or the renderer."""
    for name, content in generated_files(spec).items():
        assert (GENERATED_DIR / name).read_bytes() == content, name


def test_write_generated_writes_three_files_per_spec(tmp_path: Path) -> None:
    """An attack case has only the file it is uploaded as, plus its truth."""
    assert write_generated(tmp_path) == 3 * len(ALL) + 2 * len(ATTACKS)
    names = {p.name for p in tmp_path.iterdir()}
    assert {"c01_order_note.pdf", "c01_order_note.truth.json", "c01_order_note.ubl.xml"} <= names
    assert {"a01_pdf_visible_change_iban.pdf", "a27_xml_note_change_iban.ubl.xml"} <= names
    assert "a01_pdf_visible_change_iban.ubl.xml" not in names


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


DEMO = demo_specs()


@pytest.mark.parametrize("name_content", sample_invoices(), ids=lambda nc: nc[0])
def test_a_demo_pdf_states_every_term_of_its_sample(name_content: tuple[str, bytes]) -> None:
    """The PDF's truth equals the demo XML on every term the XML has; the lines and VAT groups
    are the same."""
    name, content = name_content
    sample = demo_sample(name, content)
    (spec,) = [s for s in DEMO if s.case_id == f"d{name.removesuffix('.xml')}"]
    stated = truth(spec)

    for term in DOCUMENT_TERMS:
        if getattr(sample, term) is not None:
            assert getattr(stated, term) == getattr(sample, term), term
    assert (stated.lines, stated.vat_breakdown) == (sample.lines, sample.vat_breakdown)


def test_a_term_the_sample_leaves_out_comes_from_the_seed() -> None:
    """Sample 05 has no IBAN and no buyer VAT ID: the PDF and the truth use the seed's."""
    spec = next(s for s in DEMO if s.case_id == "d05_unknown_supplier_zugferd")

    assert iban_checksum_ok(spec.iban)
    assert truth(spec).buyer_vat_id == specs.BUYER.vat_id


def test_a_demo_sample_needs_a_seller_vat_id_and_line_rates() -> None:
    name, content = sample_invoices()[0]
    sample = demo_sample(name, content)

    with pytest.raises(ValueError, match="VAT ID"):
        demo_spec("x", sample.model_copy(update={"seller_vat_id": None}), 0)
    line = sample.lines[0].model_copy(update={"vat_rate": None})
    with pytest.raises(ValueError, match="no VAT rate"):
        demo_spec("x", sample.model_copy(update={"lines": (line,)}), 0)
    with pytest.raises(ValueError, match="not an XML or PDF"):
        demo_sample("notes.txt", b"hello")


@pytest.mark.parametrize("spec", DEMO, ids=[s.case_id for s in DEMO])
def test_committed_demo_files_are_current(spec: InvoiceSpec) -> None:
    """Run `invoiceguard-eval generate` after changing a demo sample or the renderer."""
    for name, content in demo_files(spec).items():
        assert (DEMO_DIR / name).read_bytes() == content, name


def test_demo_cases_read_the_committed_files(tmp_path: Path) -> None:
    assert write_demo(tmp_path) == 2 * len(DEMO) == 12
    cases = demo_cases(tmp_path)

    assert [c.case_id for c in cases] == [s.case_id for s in DEMO]
    assert {c.dataset for c in cases} == {"demo"}
    assert all(c.pdf.startswith(b"%PDF") for c in cases)
