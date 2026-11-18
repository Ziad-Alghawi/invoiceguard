"""Turn an eval report (JSON) into `docs/results.md`. Numbers only come from the report."""

from typing import Any

from invoiceguard_api.parsing.fields import DOCUMENT_TERMS

PERCENT_DIGITS = 1


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.{PERCENT_DIGITS}f} %"


def num(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def usd(value: float | None) -> str:
    return "-" if value is None else f"${value:.4f}"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    return lines + ["| " + " | ".join(row) + " |" for row in rows]


def _parser(parser: dict[str, Any]) -> list[str]:
    lines = [
        "## Parser: KoSIT testsuite (no model)",
        "",
        f"- Files read: **{parser['parsed']} of {parser['files']}**"
        + (
            f" (failed: {', '.join(f['file'] for f in parser['parse_failures'])})"
            if parser["parse_failures"]
            else ""
        ),
        f"- UBL and CII of the same business case identical in every term: "
        f"**{parser['pairs_identical']} of {parser['pairs_compared']}** pairs",
        f"- VAT math check fails on: {', '.join(parser['vat_math_failures']) or 'none'}",
    ]
    if parser["pair_differences"]:
        lines += ["", "Differences between the two files of a pair:", ""]
        lines += _table(
            ["Case", "Term", "UBL", "CII"],
            [
                [d["case"], d["term"], str(d["ubl"]), str(d["cii"])]
                for d in parser["pair_differences"]
            ],
        )
    return lines


def completed_field_accuracy(details: list[dict[str, Any]]) -> float | None:
    """Document-term accuracy over the extractions that returned an invoice: separates a wrong
    value from a failed call (quota, timeout), which `field_accuracy` counts as all wrong."""
    completed = [d for d in details if not d["failure"]]
    wrong = sum(1 for d in completed for w in d["wrong"] if w["line_no"] is None)
    total = len(completed) * len(DOCUMENT_TERMS)
    return None if total == 0 else 1 - wrong / total


def _efforts(extraction: dict[str, Any]) -> list[str]:
    rows = []
    for effort, result in extraction.items():
        s = result["summary"]
        c, k = s["confidence"], s["conflicts"]
        rows.append(
            [
                effort,
                str(s["invoices"]),
                str(s["failed"]),
                pct(s["field_accuracy"]),
                pct(completed_field_accuracy(result["details"])),
                pct(s["line_term_accuracy"]),
                pct(s["document_accuracy"]),
                f"{c['confident_errors']} of {c['errors']}",
                num(c["auroc"]),
                f"{k['right']} / {k['decoy']} / {k['other']} ({k['flagged']} flagged)",
                usd(s["cost_usd_mean"]),
                num(s["output_tokens_mean"], 0),
                num(s["latency_s_p50"], 1),
                num(s["latency_s_p95"], 1),
            ]
        )
    return [
        "## Extraction by thinking level",
        "",
        "One row per reasoning effort; every invoice and repeat counts once. Fields: a failed "
        "extraction counts as all wrong; Completed: only extractions that returned an invoice. "
        "Confident errors are "
        "wrong fields at or above the `low_confidence` threshold; AUROC is how well the confidence "
        "separates right from wrong fields (0.5 = no better than chance). Conflicts: right / decoy "
        "/ other value, and how many got a confidence below the threshold.",
        "",
        *_table(
            [
                "Effort",
                "Invoices",
                "Failed",
                "Fields",
                "Completed",
                "Line terms",
                "Documents",
                "Confident errors",
                "AUROC",
                "Conflicts",
                "Cost / invoice",
                "Output tokens",
                "p50 s",
                "p95 s",
            ],
            rows,
        ),
    ]


def _chosen(effort: str, result: dict[str, Any]) -> list[str]:
    lines = [f"## Extraction at `{effort}`", ""]
    by_dataset = result["by_dataset"]
    lines += _table(
        [
            "Dataset",
            "Invoices",
            "Fields",
            "Line terms",
            "Documents",
            "Line counts",
            "Cost / invoice",
        ],
        [
            [
                name,
                str(s["invoices"]),
                pct(s["field_accuracy"]),
                pct(s["line_term_accuracy"]),
                pct(s["document_accuracy"]),
                pct(s["line_count_match"]),
                usd(s["cost_usd_mean"]),
            ]
            for name, s in by_dataset.items()
        ],
    )
    summary = result["summary"]
    lines += ["", "Accuracy per term (all datasets):", ""]
    lines += _table(
        ["Term", "Accuracy"], [[term, pct(value)] for term, value in summary["per_term"].items()]
    )
    lines += ["", "Confidence buckets:", ""]
    lines += _table(
        ["Confidence", "Fields", "Accuracy"],
        [
            [b["range"], str(b["fields"]), pct(b["accuracy"])]
            for b in summary["confidence"]["buckets"]
        ],
    )
    wrong = [(d, w) for d in result["details"] for w in d["wrong"]]
    if wrong:
        lines += ["", "Wrong fields:", ""]
        lines += _table(
            ["Invoice", "Run", "Term", "Line", "Expected", "Extracted", "Confidence"],
            [
                [
                    d["case"],
                    str(d["run"]),
                    w["term"],
                    str(w["line_no"] or ""),
                    str(w["expected"]),
                    str(w["actual"]),
                    str(w["confidence"]),
                ]
                for d, w in wrong
            ],
        )
    conflicts = [(d, c) for d in result["details"] for c in d["conflicts"]]
    if conflicts:
        lines += ["", "Conflicting printed values:", ""]
        lines += _table(
            ["Invoice", "Run", "Conflict", "Term", "Picked", "Confidence"],
            [
                [d["case"], str(d["run"]), c["kind"], c["term"], c["picked"], str(c["confidence"])]
                for d, c in conflicts
            ],
        )
    failures = [d for d in result["details"] if d["failure"]]
    if failures:
        lines += ["", "Failed extractions:", ""]
        lines += [f"- {d['case']} (run {d['run']}): {d['failure']}" for d in failures]
    return lines


def _decisions(decisions: dict[str, Any]) -> list[str]:
    lines = ["## Decisions: fraud set through the app", ""]
    for variant, result in decisions.items():
        s = result["summary"]
        lines += [
            f"### {variant.upper()}",
            "",
            f"- Cases exactly as expected (status and every flag): **{s['as_expected']} of "
            f"{s['cases']}**",
            f"- Clean invoices blocked: {s['clean_blocked']} of {s['clean_cases']}; with any flag: "
            f"{s['clean_flagged']}",
            "",
        ]
        lines += _table(
            ["Fraud type", "Cases", "Flagged", "Blocked"],
            [
                [name, str(t["cases"]), str(t["flagged"]), str(t["blocked"])]
                for name, t in s["fraud_types"].items()
            ],
        )
        lines += [""]
        lines += _table(
            ["Check", "True pos.", "False pos.", "False neg.", "Precision", "Recall"],
            [
                [
                    name,
                    str(c["true_positives"]),
                    str(c["false_positives"]),
                    str(c["false_negatives"]),
                    pct(c["precision"]),
                    pct(c["recall"]),
                ]
                for name, c in s["checks"].items()
            ],
        )
        surprises = [c for c in result["cases"] if not c["as_expected"]]
        if surprises:
            lines += ["", "Not as expected:", ""]
            lines += [
                f"- {c['case']}: {c['status']} with flags {', '.join(c['flags']) or 'none'} "
                f"(expected {c['expected_status']} with {', '.join(c['expected_flags']) or 'none'})"
                for c in surprises
            ]
        lines += [""]
    return lines


def render_results(
    report: dict[str, Any], chosen_effort: str, source: str, notes: str | None = None
) -> str:
    meta = report["meta"]
    calls = (
        f"live: {meta['live_calls']} model calls for ${meta['live_spend_usd']}"
        if meta.get("mode") == "live"
        else f"replayed: {meta.get('replayed_calls', 0)} recorded replies, no model calls"
    )
    lines = [
        "# Results",
        "",
        f"Generated by `invoiceguard-eval report` from `{source}` (ADR-019). Run of "
        f"{meta['created_at']} on commit `{meta['git_commit']}`, set `{meta['set']}`, model "
        f"`{meta['model']}`, {meta['runs']} run(s) per invoice, `low_confidence` threshold "
        f"{meta['threshold']}; {calls}.",
        "",
        "Rerun it from the recorded replies, free and offline: `make eval` (see "
        "`packages/evals/README.md`).",
        "",
    ]
    if report.get("parser"):
        lines += [*_parser(report["parser"]), ""]
    extraction = report.get("extraction")
    if extraction:
        lines += [*_efforts(extraction), ""]
        if chosen_effort in extraction:
            lines += [*_chosen(chosen_effort, extraction[chosen_effort]), ""]
    if report.get("decisions"):
        lines += _decisions(report["decisions"])
    if notes:
        lines += ["## Notes on this run", "", notes.strip(), ""]
    return "\n".join(lines).rstrip() + "\n"
