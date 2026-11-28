"""The queue's columns (P1): supplier, gross amount, currency and due date from the stored
terms, and the order by due date."""

from typing import Any

from fastapi.testclient import TestClient

from conftest import poll_until_done

# Read by the parser; no due date, so it sorts last.
NO_TERMS = b'<?xml version="1.0" encoding="UTF-8"?>\n<Invoice xmlns="urn:oasis:ubl"/>\n'


def _upload(client: TestClient, name: str, content: bytes) -> str:
    response = client.post("/invoices", files={"file": (name, content, "application/xml")})
    assert response.status_code == 202, response.text
    detail: dict[str, Any] = poll_until_done(client, response.headers["location"])
    return str(detail["id"])


def _queue(client: TestClient, **params: str) -> list[dict[str, Any]]:
    response = client.get("/invoices", params=params)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()
    return items


def test_queue_items_carry_supplier_amount_and_due_date(
    client: TestClient, samples: dict[str, bytes]
) -> None:
    ubl = _upload(client, "ubl.xml", samples["ubl_xrechnung"])
    empty = _upload(client, "empty.xml", NO_TERMS)

    by_id = {item["id"]: item for item in _queue(client)}
    assert {k: by_id[ubl][k] for k in ("supplier", "gross_total", "currency", "due_date")} == {
        "supplier": "Demo IT-Service GmbH",
        "gross_total": "5137.23",
        "currency": "EUR",
        "due_date": "2026-11-19",
    }
    # An invoice that could not be read has none of them.
    assert [by_id[empty][k] for k in ("supplier", "gross_total", "currency", "due_date")] == [
        None,
        None,
        None,
        None,
    ]


def test_queue_sorts_by_due_date_with_the_undated_last(
    client: TestClient, samples: dict[str, bytes]
) -> None:
    empty = _upload(client, "empty.xml", NO_TERMS)
    ubl = _upload(client, "ubl.xml", samples["ubl_xrechnung"])  # due 2026-11-19
    cii = _upload(client, "cii.xml", samples["cii_xrechnung"])  # due 2026-12-03

    assert [i["id"] for i in _queue(client)] == [cii, ubl, empty]
    assert [i["id"] for i in _queue(client, sort="due_date")] == [ubl, cii, empty]
    assert [i["id"] for i in _queue(client, sort="-due_date")] == [cii, ubl, empty]
    # Paging keeps the order.
    assert [i["id"] for i in _queue(client, sort="due_date", limit="1", offset="1")] == [cii]


def test_queue_refuses_an_unknown_sort(client: TestClient) -> None:
    assert client.get("/invoices", params={"sort": "amount"}).status_code == 422
