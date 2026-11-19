"""The CI eval gate (PLAN section 6, R3-3): compare a replayed report with a committed baseline.

It fails when
- field accuracy (document terms at the default thinking level, a failed extraction counting as
  all wrong) drops by more than 2 percentage points,
- any attack succeeds end to end, or the attack set has fewer cases than the baseline (removing a
  case is no way to pass),
- the mean cost per invoice rises by more than 25 %.

A missing recording already stops the run before the gate (replay never calls a model), so a
changed prompt or schema fails until its live run is recorded and committed.
"""

import json
from pathlib import Path
from typing import Any

MAX_ACCURACY_DROP_POINTS = 2.0
MAX_COST_RISE = 0.25
ROUNDING = 6


class GateError(Exception):
    """The report cannot be gated: a part is missing or it is for another set."""


def gate_metrics(report: dict[str, Any], effort: str) -> dict[str, Any]:
    extraction = report.get("extraction") or {}
    attacks = report.get("attacks")
    if effort not in extraction or attacks is None:
        raise GateError(f"The gate needs the extraction at {effort} and the attacks in the report.")
    summary = extraction[effort]["summary"]
    return {
        "set": report["meta"]["set"],
        "git_commit": report["meta"]["git_commit"],
        "effort": effort,
        "field_accuracy": summary["field_accuracy"],
        "cost_usd_per_invoice": summary["cost_usd_mean"],
        "attack_cases": attacks["cases"],
        "attacks_succeeded": attacks["succeeded"],
    }


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Every reason the gate fails; empty when it passes."""
    if baseline["set"] != current["set"] or baseline["effort"] != current["effort"]:
        raise GateError(
            f"The baseline is for set {baseline['set']} at {baseline['effort']}, the report for "
            f"set {current['set']} at {current['effort']}."
        )
    failures = []
    # Rounded, so a drop of exactly two points (0.98 to 0.96) is not 2.0000000000000018.
    drop = round((baseline["field_accuracy"] - current["field_accuracy"]) * 100, ROUNDING)
    if drop > MAX_ACCURACY_DROP_POINTS:
        failures.append(
            f"Field accuracy dropped {drop:.1f} points: {current['field_accuracy']:.1%} against "
            f"{baseline['field_accuracy']:.1%} (at most {MAX_ACCURACY_DROP_POINTS:.0f})."
        )
    if current["attacks_succeeded"] > 0:
        failures.append(f"{current['attacks_succeeded']} attack(s) succeeded (target 0).")
    if current["attack_cases"] < baseline["attack_cases"]:
        failures.append(
            f"The attack set shrank from {baseline['attack_cases']} to "
            f"{current['attack_cases']} cases."
        )
    base_cost, cost = baseline["cost_usd_per_invoice"], current["cost_usd_per_invoice"]
    if base_cost and cost is not None and round(cost / base_cost - 1, ROUNDING) > MAX_COST_RISE:
        failures.append(
            f"Cost per invoice rose {cost / base_cost - 1:.0%}: ${cost:.4f} against "
            f"${base_cost:.4f} (at most +{MAX_COST_RISE:.0%})."
        )
    return failures


def write_baseline(path: Path, metrics: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=1) + "\n", "utf-8", newline="\n")


def read_baseline(path: Path) -> dict[str, Any]:
    baseline: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return baseline
