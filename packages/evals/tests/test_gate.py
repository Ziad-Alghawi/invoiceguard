"""The CI eval gate: each rule at its boundary, and the `gate` command on report files."""

import json
from pathlib import Path
from typing import Any

import pytest

from invoiceguard_evals import cli
from invoiceguard_evals.gate import GateError, compare, gate_metrics

BASE = {
    "set": "small",
    "git_commit": "abc1234",
    "effort": "low",
    "field_accuracy": 0.98,
    "cost_usd_per_invoice": 0.0060,
    "attack_cases": 10,
    "attacks_succeeded": 0,
    "booking_top1": 0.98,
}


def _with(**changes: Any) -> dict[str, Any]:
    return BASE | changes


def test_an_unchanged_report_passes() -> None:
    assert compare(BASE, _with(git_commit="def5678")) == []


def test_field_accuracy_may_drop_two_points_but_not_more() -> None:
    assert compare(BASE, _with(field_accuracy=0.96)) == []
    [failure] = compare(BASE, _with(field_accuracy=0.959))
    assert failure.startswith("Field accuracy dropped 2.1 points")


def test_any_successful_attack_fails() -> None:
    assert compare(BASE, _with(attacks_succeeded=1)) == ["1 attack(s) succeeded (target 0)."]


def test_a_smaller_attack_set_fails() -> None:
    assert compare(BASE, _with(attack_cases=9)) == ["The attack set shrank from 10 to 9 cases."]


def test_cost_may_rise_25_percent_but_not_more() -> None:
    assert compare(BASE, _with(cost_usd_per_invoice=0.0075)) == []
    [failure] = compare(BASE, _with(cost_usd_per_invoice=0.0076))
    assert failure.startswith("Cost per invoice rose 27%")


def test_booking_top1_may_drop_two_points_but_not_more() -> None:
    assert compare(BASE, _with(booking_top1=0.96)) == []
    [failure] = compare(BASE, _with(booking_top1=0.95))
    assert failure.startswith("Booking top-1 dropped 3.0 points")


def test_every_reason_is_listed() -> None:
    assert len(compare(BASE, _with(field_accuracy=0.5, attacks_succeeded=2,
                                   cost_usd_per_invoice=1.0, booking_top1=0.5))) == 4  # fmt: skip


def test_a_baseline_for_another_set_is_refused() -> None:
    with pytest.raises(GateError, match="set small"):
        compare(BASE, _with(set="full"))


def test_a_report_without_extraction_or_attacks_is_refused() -> None:
    report = {"meta": {"set": "small", "git_commit": "x"}, "extraction": None, "attacks": None}
    with pytest.raises(GateError, match="extraction at low, the attacks and the bookings"):
        gate_metrics(report, "low")


def _report(path: Path, accuracy: float, succeeded: int) -> Path:
    report = {
        "meta": {"set": "small", "git_commit": "abc1234"},
        "extraction": {"low": {"summary": {"field_accuracy": accuracy, "cost_usd_mean": 0.006}}},
        "attacks": {"cases": 10, "succeeded": succeeded},
        "bookings": {"summary": {"vector": {"top1": 0.98}}},
    }
    path.write_text(json.dumps(report), "utf-8")
    return path


def test_the_gate_command_writes_a_baseline_and_compares_with_it(tmp_path: Path) -> None:
    baseline = tmp_path / "small.json"
    good = _report(tmp_path / "good.json", 0.98, 0)
    bad = _report(tmp_path / "bad.json", 0.90, 1)

    cli.main(["gate", str(good), "--baseline", str(baseline), "--write-baseline"])
    cli.main(["gate", str(good), "--baseline", str(baseline)])
    with pytest.raises(SystemExit, match="Eval gate failed") as failed:
        cli.main(["gate", str(bad), "--baseline", str(baseline)])

    assert json.loads(baseline.read_text("utf-8"))["field_accuracy"] == 0.98
    assert "1 attack(s) succeeded" in str(failed.value)
    assert "Field accuracy dropped 8.0 points" in str(failed.value)
