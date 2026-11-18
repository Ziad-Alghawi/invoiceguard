"""The fraud set through the real app: XML without a model, PDFs with a fake one."""

from decimal import Decimal

import pytest

from invoiceguard_evals.decisions import EvalDatabaseError, app_client, evaluate_decisions
from invoiceguard_evals.metrics import as_expected
from invoiceguard_evals.specs import ALL, CLEAN, FRAUD, truth

from .fakes import ScriptedModel, reply_for

THRESHOLD = Decimal("0.8")


def test_the_xml_fraud_set_is_decided_as_expected(eval_database_url: str) -> None:
    with app_client(eval_database_url, None, "low", None, THRESHOLD) as client:
        decisions = evaluate_decisions(client, ALL, "xml", validator=False)

    assert [d.case_id for d in decisions] == [spec.case_id for spec in (*CLEAN, *FRAUD)]
    assert [d.case_id for d in decisions if not as_expected(d)] == []
    changed_totals = next(d for d in decisions if d.fraud_type == "changed_totals")
    # Without a validator KoSIT is skipped, so it is not expected to flag the totals.
    assert changed_totals.expected_flags == {"vat_math"}


def test_pdfs_go_through_extraction(eval_database_url: str) -> None:
    specs = [CLEAN[0], FRAUD[0]]
    model = ScriptedModel([reply_for(truth(spec)) for spec in specs])

    with app_client(eval_database_url, model, "low", None, THRESHOLD) as client:
        decisions = evaluate_decisions(client, specs, "pdf", validator=False)

    assert [(d.status, sorted(d.flags)) for d in decisions] == [
        ("ready", []),
        ("blocked", ["iban"]),
    ]
    assert model.replies == []


def test_only_an_eval_database_is_dropped() -> None:
    with (
        pytest.raises(EvalDatabaseError, match="_eval"),
        app_client("postgresql+psycopg://u:p@127.0.0.1/invoiceguard", None, "low", None, THRESHOLD),
    ):
        pass
