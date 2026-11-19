"""The booking dataset (ADR-020): the packaged history is what the generator writes, the truth
uses the chart's accounts, and held-out wordings really are held out."""

import json
from pathlib import Path

from invoiceguard_api.booking.accounts import ACCOUNTS
from invoiceguard_api.booking.history import packaged_history

from invoiceguard_evals.bookings import (
    CATALOGUE,
    NEW_SUPPLIER,
    held_out_lines,
    history_invoices,
    item_of_text,
    write_history,
)


def test_the_packaged_history_is_the_generated_one(tmp_path: Path) -> None:
    # Fails when the catalogue changed without `invoiceguard-eval generate`.
    path = tmp_path / "history.json"
    lines = write_history(path)

    assert json.loads(path.read_text("utf-8"))["invoices"] == packaged_history()
    assert lines == sum(len(invoice["lines"]) for invoice in packaged_history())
    assert history_invoices() == history_invoices()


def test_every_wording_belongs_to_one_item_and_account() -> None:
    wordings = [w for s in CATALOGUE for item in s.items for w in (*item.history, item.unseen)]

    assert len(wordings) == len(set(wordings))
    assert {item.account for s in CATALOGUE for item in s.items} <= set(ACCOUNTS)


def test_held_out_lines_are_not_in_the_history() -> None:
    booked = {line["text"] for invoice in history_invoices() for line in invoice["lines"]}
    suppliers = {invoice["supplier_vat_id"] for invoice in history_invoices()}
    lines = held_out_lines()

    assert set(item_of_text()) == booked
    assert {line.kind for line in lines} == {"seen", "unseen", "new_supplier"}
    for line in lines:
        assert (line.text in booked) == (line.kind == "seen"), line.case_id
        assert line.account in ACCOUNTS
    assert NEW_SUPPLIER[0] not in suppliers
    assert len({line.case_id for line in lines}) == len(lines)
