"""Booking suggestions (R3-4, ADR-020): embedding line texts, retrieval and the vote, the
bookings endpoint, accounts chosen at approval, and the index command."""

import logging
import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from conftest import FinishedInvoice, poll_until_done
from fakes import KeywordEmbedder
from invoiceguard_api import main
from invoiceguard_api.auth import SESSION_COOKIE
from invoiceguard_api.booking import history
from invoiceguard_api.booking.embedding import (
    EMBEDDING_PURPOSE,
    EmbeddingFailed,
    embed_invoice_lines,
    embed_missing,
)
from invoiceguard_api.booking.suggest import Neighbour, neighbours, vote
from invoiceguard_api.booking.text import normalise, text_sha256
from invoiceguard_api.checks.injection import CHECK_TYPE as INJECTION_CHECK
from invoiceguard_api.db import make_session_factory
from invoiceguard_api.demo import sample_invoices
from invoiceguard_api.filetype import source_type_for
from invoiceguard_api.models import (
    AuditEvent,
    Booking,
    BookingSource,
    Check,
    CheckStatus,
    Embedding,
    FieldSource,
    Invoice,
    InvoiceField,
    ModelCall,
    ModelCallStatus,
    SourceType,
    User,
)
from invoiceguard_api.parsing import invoice_xml, read_invoice_xml
from invoiceguard_api.settings import Settings

MODEL = "gemini/gemini-embedding-001"
IT_SERVICE = "DE999000033"
OFFICE = "DE999000017"
NOTEBOOK = "Notebook 14 Zoll, 32 GB RAM"
SETUP = "Einrichtung und Inbetriebnahme"
AXES = {"notebook": 0, "laptop": 0, "einrichtung": 1, "support": 1, "papier": 2, "toner": 3}


def embedder(**options: Any) -> KeywordEmbedder:
    return KeywordEmbedder(AXES, **options)


def add_booking(
    session: Session,
    text: str,
    account: str,
    vat_id: str = IT_SERVICE,
    *,
    searchable: bool = True,
    invoice_id: uuid.UUID | None = None,
) -> None:
    normalised = normalise(text)
    session.add(
        Booking(
            source=BookingSource.IMPORT if invoice_id is None else BookingSource.INVOICE,
            invoice_id=invoice_id,
            line_no=1,
            supplier_vat_id=vat_id,
            supplier_name="Lieferant",
            invoice_number="H-1",
            issue_date=date(2026, 1, 5),
            text=normalised,
            text_sha256=text_sha256(normalised),
            account=account,
            suggested_account=None,
            searchable=searchable,
        )
    )
    session.flush()


def calls(session: Session) -> list[ModelCall]:
    return list(session.scalars(select(ModelCall).order_by(ModelCall.id)))


# --- Embedding -----------------------------------------------------------------------------------


def test_each_text_is_embedded_once_and_the_call_logged(db_session: Session) -> None:
    fake = embedder()

    first = embed_missing(db_session, fake, MODEL, ["Toner  schwarz", "Toner schwarz", " "])
    again = embed_missing(db_session, fake, MODEL, ["Toner schwarz"])

    assert (first, again) == (1, 0)
    assert fake.calls == [["Toner schwarz"]]
    stored = db_session.scalars(select(Embedding)).one()
    assert (stored.model, stored.text) == (MODEL, "Toner schwarz")
    assert stored.text_sha256 == text_sha256("Toner schwarz")
    assert len(stored.vector) == 768
    (call,) = calls(db_session)
    assert (call.purpose, call.status, call.model) == (EMBEDDING_PURPOSE, ModelCallStatus.OK, MODEL)
    assert (call.input_tokens, call.output_tokens, call.cost_usd) == (3, 0, Decimal("0.000002"))


def test_texts_are_embedded_in_batches_of_100(db_session: Session) -> None:
    fake = embedder()

    count = embed_missing(db_session, fake, MODEL, [f"Artikel {n}" for n in range(205)])

    assert count == 205
    assert [len(batch) for batch in fake.calls] == [100, 100, 5]
    assert len(calls(db_session)) == 3


@pytest.mark.parametrize(
    ("options", "status"),
    [
        ({"fail": True}, ModelCallStatus.ERROR),
        ({"cost_usd": None}, ModelCallStatus.PRICE_UNKNOWN),
        ({"dimensions": 12}, ModelCallStatus.INVALID_OUTPUT),
    ],
)
def test_a_failed_embedding_is_logged_and_stores_nothing(
    db_session: Session, options: dict[str, Any], status: ModelCallStatus
) -> None:
    with pytest.raises(EmbeddingFailed):
        embed_missing(db_session, embedder(**options), MODEL, ["Toner schwarz"])

    assert db_session.scalar(select(func.count(Embedding.id))) == 0
    (call,) = calls(db_session)
    assert call.status is status
    assert call.error


def test_a_long_text_is_cut_before_it_is_embedded() -> None:
    assert len(normalise("x" * 5000)) == 500
    assert normalise("Papier  80 g/m²\n") == "Papier 80 g/m²"


# --- Retrieval and vote ----------------------------------------------------------------------


@pytest.fixture
def booked(db_session: Session) -> Session:
    """Booked lines of two suppliers, all embedded with the keyword embedder."""
    add_booking(db_session, NOTEBOOK, "0410")
    add_booking(db_session, "Laptop 15,6 Zoll, 16 GB RAM", "0410")
    add_booking(db_session, SETUP, "4806")
    add_booking(db_session, "Kopierpapier DIN A4", "4930", OFFICE)
    add_booking(db_session, "Toner schwarz", "4930", OFFICE)
    db_session.commit()
    texts = db_session.scalars(select(Booking.text)).all()
    embed_missing(db_session, embedder(), MODEL, [*texts, "Laptop für den Vertrieb"])
    return db_session


def test_vectors_find_bookings_by_meaning_and_vote(booked: Session) -> None:
    method, found = neighbours(booked, MODEL, "Laptop für den Vertrieb", IT_SERVICE)

    assert method == "vector"
    assert {n.text for n in found[:2]} == {NOTEBOOK, "Laptop 15,6 Zoll, 16 GB RAM"}
    assert found[0].same_supplier and found[0].similarity == pytest.approx(1, abs=0.001)
    suggestions = vote(found)
    assert suggestions[0].account == "0410"
    assert suggestions[0].name == "Geschäftsausstattung"
    assert len(suggestions[0].sources) == 2
    assert len(suggestions) <= 3
    assert sum(s.share for s in suggestions) <= 1 + 1e-9
    assert suggestions[0].share > 0.5


def test_a_line_without_a_vector_uses_the_text_match(booked: Session) -> None:
    for model in (None, MODEL):
        method, found = neighbours(booked, model, "Kopierpapier DIN A5", OFFICE)

        assert method == "text"
        assert vote(found)[0].account == "4930"


def test_the_same_supplier_wins_a_tie(db_session: Session) -> None:
    add_booking(db_session, "Wartung Anlage", "4806", IT_SERVICE)
    add_booking(db_session, "Wartung Anlage", "4260", OFFICE)

    for vat_id, account in ((OFFICE, "4260"), (IT_SERVICE, "4806")):
        _, found = neighbours(db_session, None, "Wartung Anlage", f" {vat_id.lower()} ")
        assert vote(found)[0].account == account


def test_unsearchable_bookings_and_the_invoice_itself_are_never_retrieved(
    db_session: Session,
) -> None:
    own = uuid.uuid4()
    db_session.add(
        Invoice(
            id=own,
            source_type=SourceType.XML,
            original_filename="x.xml",
            sha256="0" * 64,
            size_bytes=1,
            storage_path="x",
        )
    )
    add_booking(db_session, "Wartung Anlage", "4806", searchable=False)
    add_booking(db_session, "Wartung Anlage", "4260", invoice_id=own)
    add_booking(db_session, "Wartung Anlage", "4950")

    _, found = neighbours(db_session, None, "Wartung Anlage", None, exclude_invoice_id=own)

    assert [n.account for n in found] == ["4950"]


def test_no_evidence_no_suggestion() -> None:
    nothing = Neighbour(None, None, None, None, "Fremd", "4930", False, 0.0, 0.0)

    assert vote([]) == ()
    assert vote([nothing]) == ()


# --- The bookings endpoint and approval ---------------------------------------------------------


def upload(client: TestClient, finished: FinishedInvoice, name: str, content: bytes) -> str:
    response = client.post("/invoices", files={"file": (name, content, "text/plain")})
    assert response.status_code == 202, response.text
    invoice_id: str = finished(response.headers["location"])["id"]
    return invoice_id


@pytest.fixture
def ready_id(
    client: TestClient, finished: FinishedInvoice, samples: dict[str, bytes], seeded: None
) -> str:
    """The clean Demo IT-Service invoice (notebooks and setup): `ready`."""
    return upload(client, finished, "rechnung.xml", samples["ubl_xrechnung"])


@pytest.fixture
def packaged(db_session: Session) -> None:
    """The packaged history and vectors, as the demo has them."""
    history.import_packaged(db_session, MODEL)
    db_session.commit()


def test_suggestions_per_line_with_their_sources(
    client: TestClient, ready_id: str, packaged: None
) -> None:
    response = client.get(f"/invoices/{ready_id}/bookings")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["default_account"] == "4900"
    assert {"number": "4930", "name": "Bürobedarf"} in body["accounts"]
    first, second = body["lines"]
    assert (first["line_no"], first["text"], first["booked"]) == (1, NOTEBOOK, None)
    # The demo's packaged vectors cover the samples' lines (ADR-020).
    assert first["method"] == "vector"
    assert first["suggestions"][0]["account"] == "0410"
    source = first["suggestions"][0]["sources"][0]
    assert source["invoice_id"] is None
    assert source["supplier_name"] == "Demo IT-Service GmbH"
    assert source["same_supplier"] is True
    assert source["similarity"] == pytest.approx(1, abs=0.001)
    assert second["suggestions"][0]["account"] == "4806"


def test_without_vectors_the_endpoint_uses_the_text_match(
    client: TestClient, ready_id: str, db_session: Session
) -> None:
    history.import_history(db_session, history.packaged_history())
    db_session.commit()

    lines = client.get(f"/invoices/{ready_id}/bookings").json()["lines"]

    assert [line["method"] for line in lines] == ["text", "text"]
    assert [line["suggestions"][0]["account"] for line in lines] == ["0410", "4806"]


def test_bookings_of_an_unknown_invoice(client: TestClient) -> None:
    assert client.get(f"/invoices/{uuid.uuid4()}/bookings").status_code == 404


def bookings_of(session: Session, invoice_id: str) -> list[Booking]:
    return list(
        session.scalars(
            select(Booking)
            .where(Booking.invoice_id == uuid.UUID(invoice_id))
            .order_by(Booking.line_no)
        )
    )


CHOSEN = [{"line_no": 1, "account": "0410"}, {"line_no": 2, "account": "4900"}]


def test_approval_stores_the_chosen_accounts_with_the_decision(
    client: TestClient, ready_id: str, packaged: None, db_session: Session, reviewer: User
) -> None:
    response = client.post(f"/invoices/{ready_id}/approve", json={"bookings": CHOSEN})

    assert response.status_code == 200, response.text
    first, second = bookings_of(db_session, ready_id)
    assert (first.account, first.suggested_account) == ("0410", "0410")
    # The reviewer chose another account than the suggestion: both are kept.
    assert (second.account, second.suggested_account) == ("4900", "4806")
    assert first.source is BookingSource.INVOICE
    assert (first.user_id, first.searchable) == (reviewer.id, True)
    assert (first.supplier_vat_id, first.supplier_name) == (IT_SERVICE, "Demo IT-Service GmbH")
    assert (first.invoice_number, first.issue_date) == ("2026-IT-0815", date(2026, 11, 5))
    assert first.text == NOTEBOOK
    event = db_session.scalars(
        select(AuditEvent).where(AuditEvent.action == "invoice.approved")
    ).one()
    assert event.details["bookings"] == [
        {"line_no": 1, "account": "0410", "suggested_account": "0410"},
        {"line_no": 2, "account": "4900", "suggested_account": "4806"},
    ]
    lines = client.get(f"/invoices/{ready_id}/bookings").json()["lines"]
    assert lines[1]["booked"] == {
        "account": "4900",
        "name": "Sonstige betriebliche Aufwendungen",
        "suggested_account": "4806",
    }
    # Its own bookings are no evidence for itself.
    sources = [s for line in lines for g in line["suggestions"] for s in g["sources"]]
    assert all(source["invoice_id"] != ready_id for source in sources)


def test_an_approval_without_accounts_books_nothing(
    client: TestClient, ready_id: str, db_session: Session
) -> None:
    assert client.post(f"/invoices/{ready_id}/approve", json={}).status_code == 200

    assert bookings_of(db_session, ready_id) == []


@pytest.mark.parametrize(
    "bookings",
    [
        [{"line_no": 1, "account": "0410"}],
        [{"line_no": 1, "account": "0410"}, {"line_no": 1, "account": "0410"}],
        [*CHOSEN, {"line_no": 3, "account": "0410"}],
        [{"line_no": 1, "account": "0410"}, {"line_no": 2, "account": "9999"}],
        [{"line_no": 1, "account": "0410"}, {"line_no": 2, "account": "4900", "note": "x"}],
        [{"line_no": 0, "account": "0410"}, {"line_no": 2, "account": "4900"}],
    ],
)
def test_accounts_for_every_line_once_from_the_chart(
    client: TestClient, ready_id: str, db_session: Session, bookings: list[dict[str, Any]]
) -> None:
    response = client.post(f"/invoices/{ready_id}/approve", json={"bookings": bookings})

    assert response.status_code == 422, response.text
    assert client.get(f"/invoices/{ready_id}").json()["status"] == "ready"
    assert bookings_of(db_session, ready_id) == []


def test_an_approved_invoice_is_evidence_for_the_next_one(
    client: TestClient,
    ready_id: str,
    finished: FinishedInvoice,
    samples: dict[str, bytes],
) -> None:
    chosen = [{"line_no": 1, "account": "4855"}, {"line_no": 2, "account": "4806"}]
    assert client.post(f"/invoices/{ready_id}/approve", json={"bookings": chosen}).is_success
    # The same supplier and notebook line, with a changed IBAN (blocked; still suggested).
    blocked_id = upload(client, finished, "betrug.xml", samples["ubl_fraud_iban"])

    line = client.get(f"/invoices/{blocked_id}/bookings").json()["lines"][0]

    assert line["suggestions"][0]["account"] == "4855"
    assert line["suggestions"][0]["sources"][0]["invoice_id"] == ready_id
    assert line["suggestions"][0]["sources"][0]["invoice_number"] == "2026-IT-0815"


def test_an_injection_flagged_invoice_is_booked_but_never_retrieved(
    client: TestClient, ready_id: str, db_session: Session
) -> None:
    db_session.add(
        Check(
            invoice_id=uuid.UUID(ready_id),
            type=INJECTION_CHECK,
            status=CheckStatus.FAILED,
            message="Instructions to an AI in the text.",
            evidence={},
        )
    )
    db_session.commit()

    approved = client.post(f"/invoices/{ready_id}/approve", json={"bookings": CHOSEN})

    assert approved.status_code == 200, approved.text
    assert [b.searchable for b in bookings_of(db_session, ready_id)] == [False, False]
    _, found = neighbours(db_session, None, NOTEBOOK, IT_SERVICE)
    assert found == []


def test_the_approver_chooses_the_accounts_when_confirming_an_override(
    client: TestClient,
    approver_client: TestClient,
    finished: FinishedInvoice,
    samples: dict[str, bytes],
    seeded: None,
    db_session: Session,
    approver: User,
) -> None:
    blocked_id = upload(client, finished, "betrug.xml", samples["ubl_fraud_iban"])
    assert client.post(
        f"/invoices/{blocked_id}/override", json={"reason": "Telefonisch"}
    ).is_success

    confirmed = approver_client.post(
        f"/invoices/{blocked_id}/override/confirm",
        json={"reason": "Bestätigt", "bookings": CHOSEN},
    )

    assert confirmed.status_code == 200, confirmed.text
    booking = bookings_of(db_session, blocked_id)[0]
    # No history in this database: nothing was suggested.
    assert (booking.account, booking.user_id, booking.suggested_account) == (
        "0410",
        approver.id,
        None,
    )


# --- Embedding after processing ------------------------------------------------------------------


@pytest.fixture
def embedding_client(
    settings: Settings,
    engine: Engine,
    session_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, KeywordEmbedder]]:
    """A logged-in client whose app embeds with the keyword embedder. Startup recovery is off,
    so the upload's own background tasks process and embed the invoice, in that order."""
    monkeypatch.setattr(main, "recover_unfinished", lambda *_: None)
    fake = embedder()
    with TestClient(main.create_app(settings, embedder=fake)) as test_client:
        test_client.cookies.set(SESSION_COOKIE, session_token)
        yield test_client, fake


def test_the_lines_of_a_new_invoice_are_embedded_after_processing(
    embedding_client: tuple[TestClient, KeywordEmbedder],
    samples: dict[str, bytes],
    seeded: None,
    db_session: Session,
) -> None:
    client, fake = embedding_client

    invoice_id = upload(
        client, lambda url: poll_until_done(client, url), "rechnung.xml", samples["ubl_xrechnung"]
    )

    assert fake.calls == [[NOTEBOOK, SETUP]]
    (call,) = calls(db_session)
    assert (call.invoice_id, call.purpose) == (uuid.UUID(invoice_id), EMBEDDING_PURPOSE)
    lines = client.get(f"/invoices/{invoice_id}/bookings").json()["lines"]
    assert [line["method"] for line in lines] == ["vector", "vector"]
    # The embedding cost counts for the invoice like any model call.
    assert client.get(f"/invoices/{invoice_id}").json()["llm_cost_usd"] == "0.000002"


def _invoice_with_line(session: Session, text: str) -> uuid.UUID:
    invoice = Invoice(
        source_type=SourceType.XML,
        original_filename="x.xml",
        sha256="1" * 64,
        size_bytes=1,
        storage_path="x",
    )
    session.add(invoice)
    session.flush()
    session.add(
        InvoiceField(
            invoice_id=invoice.id, code="BT-153", line_no=1, value=text, source=FieldSource.XML
        )
    )
    session.commit()
    return invoice.id


def test_lines_are_not_embedded_over_budget_or_when_the_call_fails(
    engine: Engine, db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    session_factory = make_session_factory(engine)
    invoice_id = _invoice_with_line(db_session, "Toner schwarz")
    db_session.add(
        ModelCall(
            purpose="extraction",
            model="m",
            status=ModelCallStatus.OK,
            cost_usd=Decimal(1),
            latency_ms=1,
        )
    )
    db_session.commit()
    fake = embedder()

    embed_invoice_lines(session_factory, None, MODEL, None, invoice_id)
    embed_invoice_lines(session_factory, fake, MODEL, Decimal(1), invoice_id)
    embed_invoice_lines(session_factory, embedder(fail=True), MODEL, None, invoice_id)

    assert fake.calls == []
    assert "daily LLM budget" in caplog.text
    assert "not embedded" in caplog.text
    assert db_session.scalar(select(func.count(Embedding.id))) == 0

    embed_invoice_lines(session_factory, fake, MODEL, Decimal(2), invoice_id)
    embed_invoice_lines(session_factory, fake, MODEL, Decimal(2), invoice_id)

    assert fake.calls == [["Toner schwarz"]]


# --- The packaged index and `invoiceguard-index` -------------------------------------------------


def _demo_line_texts() -> list[str]:
    texts: list[str] = []
    for name, content in sample_invoices():
        source_type = source_type_for(name, content)
        assert source_type is not None
        parsed = read_invoice_xml(invoice_xml(content, source_type))
        texts.extend(line.item_name for line in parsed.lines if line.item_name)
    return texts


def test_the_packaged_vectors_cover_the_history_and_the_demo_samples() -> None:
    vectors = history.packaged_vectors()
    texts = {line["text"] for inv in history.packaged_history() for line in inv["lines"]}

    assert vectors["model"] == Settings.model_fields["embedding_model"].default
    assert vectors["dimensions"] == 768
    assert {normalise(text) for text in [*texts, *_demo_line_texts()]} <= set(vectors["vectors"])
    assert all(len(history.decode_vector(v)) == 768 for v in vectors["vectors"].values())


def test_importing_history_replaces_imports_and_keeps_approved_bookings(
    db_session: Session,
) -> None:
    invoice_id = _invoice_with_line(db_session, "Toner")
    add_booking(db_session, "Toner", "4930", invoice_id=invoice_id)
    invoices = history.packaged_history()

    first = history.import_history(db_session, invoices)
    second = history.import_history(db_session, invoices[:2])

    lines = sum(len(invoice["lines"]) for invoice in invoices)
    assert first == lines
    assert second == sum(len(invoice["lines"]) for invoice in invoices[:2])
    assert db_session.scalar(select(func.count(Booking.id))) == second + 1


def test_vectors_of_another_model_are_not_loaded(db_session: Session) -> None:
    vectors = history.packaged_vectors()

    assert history.load_vectors(db_session, "other/model", vectors) == 0
    assert history.load_vectors(db_session, MODEL, {**vectors, "vectors": {}}) == 0
    assert history.load_vectors(db_session, MODEL, vectors) == len(vectors["vectors"])


def test_rebuild_embeds_what_has_no_vector_and_is_safe_to_repeat(db_session: Session) -> None:
    _invoice_with_line(db_session, "Toner cyan, neu im Sortiment")
    fake = embedder()

    first = history.rebuild(db_session, MODEL, fake)
    second = history.rebuild(db_session, MODEL, fake)
    without_key = history.rebuild(db_session, MODEL, None)

    assert first["imported_bookings"] == second["imported_bookings"] > 100
    assert first["loaded_vectors"] == len(history.packaged_vectors()["vectors"])
    assert first["embedded_texts"] == 1
    assert fake.calls == [["Toner cyan, neu im Sortiment"]]
    assert (second["loaded_vectors"], second["embedded_texts"]) == (0, 0)
    assert without_key["embedded_texts"] == 0


def test_the_index_command(
    settings: Settings, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(history, "get_settings", lambda: settings)
    monkeypatch.setattr(history, "make_embedder", lambda *_: embedder(fail=True))
    with make_session_factory(engine)() as session:
        _invoice_with_line(session, "Toner cyan, neu im Sortiment")

    with pytest.raises(SystemExit, match="Embedding failed"):
        history.main()

    monkeypatch.setattr(history, "make_embedder", lambda *_: None)
    history.main()
    with make_session_factory(engine)() as session:
        assert session.scalar(select(func.count(Booking.id))) == 159
