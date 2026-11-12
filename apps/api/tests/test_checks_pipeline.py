"""Checks with the database: loading the context, storing results, and the invoice status they
lead to, end to end through the API on the seeded demo data."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from invoiceguard_api import processing
from invoiceguard_api.checks import CheckResult, load_context, replace_results
from invoiceguard_api.checks.model import Validation
from invoiceguard_api.models import (
    AuditEvent,
    Check,
    CheckStatus,
    Invoice,
    InvoiceField,
    InvoiceStatus,
    SourceType,
    SupplierBankAccount,
)
from invoiceguard_api.parsing import parse_invoice

# Fictitious (fake bank code), as in ubl_fraud_iban.xml; not a secret.
FRAUD_IBAN = "DE58876543210000000099"  # pragma: allowlist secret
NOT_VALIDATED = Validation(outcome="unavailable", reason="not configured in this test")
Upload = Callable[[str, bytes], dict[str, Any]]
FinishedInvoice = Callable[[str], dict[str, Any]]


@pytest.fixture
def upload(client: TestClient, finished: FinishedInvoice) -> Upload:
    """Upload a file and return the invoice detail once processing has finished."""

    def run(filename: str, content: bytes) -> dict[str, Any]:
        response = client.post("/invoices", files={"file": (filename, content, "text/xml")})
        assert response.status_code == 202, response.text
        return finished(response.headers["location"])

    return run


def _checks(detail: dict[str, Any]) -> dict[str, str]:
    return {check["type"]: check["status"] for check in detail["checks"]}


def _renumbered(xml: bytes, number: bytes) -> bytes:
    return xml.replace(b"<cbc:ID>2026-IT-0815</cbc:ID>", b"<cbc:ID>" + number + b"</cbc:ID>")


# --- End to end: one invoice per final status -----------------------------------------------


@pytest.mark.usefixtures("seeded")
def test_clean_invoice_ends_ready(upload: Upload, samples: dict[str, bytes]) -> None:
    detail = upload("rechnung.xml", samples["ubl_xrechnung"])

    assert (detail["status"], detail["status_reason"]) == ("ready", None)
    assert _checks(detail) == {
        "kosit": "skipped",
        "vat_math": "passed",
        "duplicate": "passed",
        "supplier_known": "passed",
        "iban": "passed",
        "po_match": "passed",
    }
    # Worst first, so the reviewer sees problems at the top.
    assert detail["checks"][0]["type"] == "kosit"


@pytest.mark.usefixtures("seeded")
def test_changed_iban_ends_blocked_with_evidence(
    upload: Upload, samples: dict[str, bytes], db_session: Session
) -> None:
    detail = upload("rechnung.xml", samples["ubl_fraud_iban"])

    assert detail["status"] == "blocked"
    assert detail["status_reason"] == "Failed checks: iban."
    iban = detail["checks"][0]
    assert (iban["type"], iban["status"]) == ("iban", "failed")
    assert "possible bank-detail fraud" in iban["message"]
    assert iban["evidence"]["invoice_iban"] == FRAUD_IBAN
    assert [account["iban"] for account in iban["evidence"]["verified_ibans"]] == [
        "DE60123456780000000003"
    ]
    assert _checks(detail)["vat_math"] == "passed"

    event = db_session.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity_id == detail["id"], AuditEvent.action == "invoice.status_changed")
        .order_by(AuditEvent.id.desc())
    ).first()
    assert event is not None
    assert (event.details["to"], event.details["reason"]) == ("blocked", "Failed checks: iban.")
    assert event.details["checks"] == {
        "passed": 4,
        "warning": 0,
        "failed": 1,
        "skipped": 1,
        "failed_checks": ["iban"],
    }


@pytest.mark.usefixtures("seeded")
def test_same_invoice_number_again_ends_blocked_as_duplicate(
    upload: Upload, samples: dict[str, bytes]
) -> None:
    first = upload("rechnung.xml", samples["ubl_xrechnung"])
    # Another file (so not caught by the SHA-256 check) with the same number, written differently.
    second = upload("kopie.xml", _renumbered(samples["ubl_xrechnung"], b"2026 it 0815"))

    assert second["status"] == "blocked"
    duplicate = next(check for check in second["checks"] if check["type"] == "duplicate")
    assert duplicate["status"] == "failed"
    assert [other["invoice_id"] for other in duplicate["evidence"]["invoices"]] == [first["id"]]


@pytest.mark.usefixtures("seeded")
def test_renumbered_copy_with_same_amount_is_only_a_warning(
    upload: Upload, samples: dict[str, bytes]
) -> None:
    upload("rechnung.xml", samples["ubl_xrechnung"])
    second = upload("rechnung-2.xml", _renumbered(samples["ubl_xrechnung"], b"2026-IT-0901"))

    assert second["status"] == "ready"
    assert _checks(second)["duplicate"] == "warning"


def test_unseeded_database_warns_but_does_not_block(
    upload: Upload, samples: dict[str, bytes]
) -> None:
    detail = upload("rechnung.xml", samples["ubl_xrechnung"])

    assert detail["status"] == "ready"
    assert _checks(detail) | {"kosit": "-"} == {
        "kosit": "-",
        "vat_math": "passed",
        "duplicate": "passed",
        "supplier_known": "warning",
        "iban": "warning",
        "po_match": "warning",
    }


def test_plain_pdf_waits_without_checks(upload: Upload, samples: dict[str, bytes]) -> None:
    detail = upload("scan.pdf", samples["plain_pdf"])

    assert (detail["status"], detail["checks"]) == ("awaiting_extraction", [])


@pytest.mark.usefixtures("seeded")
def test_rerun_replaces_the_check_results(
    upload: Upload, samples: dict[str, bytes], client: TestClient, db_session: Session
) -> None:
    detail = upload("rechnung.xml", samples["ubl_fraud_iban"])
    invoice_id = uuid.UUID(detail["id"])
    invoice = db_session.get(Invoice, invoice_id)
    assert invoice is not None
    invoice.status = InvoiceStatus.RECEIVED
    db_session.commit()

    app = client.app
    processing.process_invoice(
        app.state.session_factory,  # type: ignore[attr-defined]
        app.state.storage,  # type: ignore[attr-defined]
        app.state.validator,  # type: ignore[attr-defined]
        app.state.extractor,  # type: ignore[attr-defined]
        invoice_id,
    )

    rerun = client.get(f"/invoices/{invoice_id}").json()
    assert rerun["status"] == "blocked"
    assert [c["type"] for c in rerun["checks"]] == [c["type"] for c in detail["checks"]]
    rows = db_session.scalars(select(Check).where(Check.invoice_id == invoice_id)).all()
    assert len(rows) == len(detail["checks"])


@pytest.mark.usefixtures("seeded")
def test_error_in_a_check_rolls_back_fields_and_results(
    upload: Upload, samples: dict[str, bytes], db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_: object) -> list[CheckResult]:
        raise RuntimeError("check crashed")

    monkeypatch.setattr(processing, "run_checks", explode)

    detail = upload("rechnung.xml", samples["ubl_xrechnung"])

    assert (detail["status"], detail["checks"]) == ("failed", [])
    invoice_id = uuid.UUID(detail["id"])
    fields = db_session.scalars(select(InvoiceField).where(InvoiceField.invoice_id == invoice_id))
    assert fields.all() == []


# --- Loading the context ------------------------------------------------------------------------


def _store(db_session: Session, xml: bytes, sha: str, status: InvoiceStatus) -> uuid.UUID:
    """An invoice row with its fields, as processing leaves it."""
    parsed = parse_invoice(xml, SourceType.XML)
    invoice = Invoice(
        id=uuid.uuid4(),
        status=status,
        source_type=SourceType.XML,
        original_filename="r.xml",
        sha256=sha.ljust(64, "0"),
        size_bytes=len(xml),
        storage_path="x",
    )
    db_session.add(invoice)
    db_session.flush()
    db_session.add_all(processing._xml_fields(invoice.id, parsed))
    db_session.commit()
    return invoice.id


@pytest.mark.usefixtures("seeded")
def test_context_has_the_supplier_registry_and_the_order(
    db_session: Session, samples: dict[str, bytes]
) -> None:
    parsed = parse_invoice(samples["ubl_xrechnung"], SourceType.XML)

    context = load_context(db_session, uuid.uuid4(), parsed, NOT_VALIDATED)

    assert context.supplier is not None
    assert context.supplier.name == "Demo IT-Service GmbH"
    assert [account.iban for account in context.supplier.verified_ibans] == [
        "DE60123456780000000003"
    ]
    assert context.order is not None
    assert context.order.supplier_id == context.supplier.id
    assert [(line.line_no, line.unit_code) for line in context.order.lines] == [
        (1, "C62"),
        (2, "HUR"),
    ]
    assert context.other_invoices == ()


@pytest.mark.usefixtures("seeded")
def test_context_without_known_order_reference_has_no_order(
    db_session: Session, samples: dict[str, bytes]
) -> None:
    parsed = parse_invoice(samples["ubl_xrechnung"], SourceType.XML)
    unknown = parsed.model_copy(update={"order_reference": "PO-1999-0001"})

    without = parsed.model_copy(update={"order_reference": None})

    assert load_context(db_session, uuid.uuid4(), unknown, NOT_VALIDATED).order is None
    assert load_context(db_session, uuid.uuid4(), without, NOT_VALIDATED).order is None


def test_context_without_seed_has_no_supplier_or_order(
    db_session: Session, samples: dict[str, bytes]
) -> None:
    parsed = parse_invoice(samples["ubl_xrechnung"], SourceType.XML)

    context = load_context(db_session, uuid.uuid4(), parsed, NOT_VALIDATED)

    assert (context.supplier, context.order) == (None, None)


@pytest.mark.usefixtures("seeded")
def test_unverified_accounts_are_not_in_the_registry(
    db_session: Session, samples: dict[str, bytes]
) -> None:
    account = db_session.scalars(
        select(SupplierBankAccount).where(SupplierBankAccount.iban == "DE60123456780000000003")
    ).one()
    account.verified = False
    db_session.commit()
    parsed = parse_invoice(samples["ubl_xrechnung"], SourceType.XML)

    context = load_context(db_session, uuid.uuid4(), parsed, NOT_VALIDATED)

    assert context.supplier is not None
    assert context.supplier.verified_ibans == ()


def test_other_invoices_of_the_same_seller_by_vat_id(
    db_session: Session, samples: dict[str, bytes]
) -> None:
    ubl = samples["ubl_xrechnung"]
    earlier = _store(
        db_session,
        ubl.replace(b"<cbc:CompanyID>DE999000033", b"<cbc:CompanyID>de 999 000 033"),
        "a",
        InvoiceStatus.READY,
    )
    _store(db_session, samples["cii_xrechnung"], "b", InvoiceStatus.READY)
    current = _store(db_session, _renumbered(ubl, b"2026-IT-0900"), "c", InvoiceStatus.PROCESSING)

    parsed = parse_invoice(_renumbered(ubl, b"2026-IT-0900"), SourceType.XML)
    others = load_context(db_session, current, parsed, NOT_VALIDATED).other_invoices

    # The CII sample is another seller; the current invoice itself is left out.
    assert [(o.id, o.invoice_number, str(o.gross_total), o.status) for o in others] == [
        (earlier, "2026-IT-0815", "5137.23", "ready")
    ]
    assert others[0].issue_date.isoformat() == "2026-11-05"


def test_other_invoices_by_seller_name_without_vat_id(
    db_session: Session, samples: dict[str, bytes]
) -> None:
    without_vat_id = samples["ubl_xrechnung"].replace(
        b"<cbc:CompanyID>DE999000033</cbc:CompanyID>", b"<cbc:CompanyID></cbc:CompanyID>"
    )
    earlier = _store(db_session, without_vat_id, "a", InvoiceStatus.READY)
    parsed = parse_invoice(without_vat_id, SourceType.XML)
    assert parsed.seller_vat_id is None

    others = load_context(db_session, uuid.uuid4(), parsed, NOT_VALIDATED).other_invoices

    assert [other.id for other in others] == [earlier]


def test_replace_results_is_idempotent(db_session: Session, samples: dict[str, bytes]) -> None:
    invoice_id = _store(db_session, samples["ubl_xrechnung"], "a", InvoiceStatus.PROCESSING)
    results = [
        CheckResult("iban", CheckStatus.FAILED, "changed", {"invoice_iban": "DE58"}),
        CheckResult("vat_math", CheckStatus.PASSED, "ok"),
    ]

    for _ in range(2):
        replace_results(db_session, invoice_id, results)
        db_session.commit()

    rows = db_session.scalars(
        select(Check).where(Check.invoice_id == invoice_id).order_by(Check.type)
    ).all()
    assert [(r.type, r.status, r.message, r.evidence) for r in rows] == [
        ("iban", CheckStatus.FAILED, "changed", {"invoice_iban": "DE58"}),
        ("vat_math", CheckStatus.PASSED, "ok", {}),
    ]
