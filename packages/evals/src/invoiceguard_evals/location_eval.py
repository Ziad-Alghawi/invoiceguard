"""Field locations (P1, ADR-029): the share of stored field values that the app's code finds in
each PDF's text layer, the way click-to-highlight finds them. No model is called.

Each case's fields are the rows the app stores for its truth (`to_field_rows`), searched with
their value as an XML field is; LLM fields would use their evidence first. "Located" means a
match was found, not that its box was checked against a hand-marked one.
"""

from collections import Counter
from collections.abc import Sequence
from typing import Any

from invoiceguard_api.locations import FieldToLocate, locate_fields, read_text_layer
from invoiceguard_api.parsing.fields import DOCUMENT_TERMS, LINE_TERMS, to_field_rows

from invoiceguard_evals.datasets import ExtractionCase
from invoiceguard_evals.report import table

TERM_NAMES = {code: name for name, code in (DOCUMENT_TERMS | LINE_TERMS).items()}


def evaluate_locations(cases: Sequence[ExtractionCase]) -> dict[str, Any]:
    fields: Counter[tuple[str, str]] = Counter()
    located: Counter[tuple[str, str]] = Counter()
    invoices: Counter[str] = Counter()
    missed = []
    for case in cases:
        invoices[case.dataset] += 1
        rows = to_field_rows(case.truth)
        found = locate_fields(
            [FieldToLocate(row.code, row.line_no, row.value) for row in rows],
            read_text_layer(case.pdf),
        )
        for row, location in zip(rows, found, strict=True):
            fields[(case.dataset, row.code)] += 1
            located[(case.dataset, row.code)] += location.located
            if not location.located:
                missed.append({"case": case.case_id, "code": row.code, "line": row.line_no})
    datasets = sorted(invoices)
    return {
        "datasets": {
            name: {
                "invoices": invoices[name],
                "fields": sum(n for (d, _), n in fields.items() if d == name),
                "located": sum(n for (d, _), n in located.items() if d == name),
            }
            for name in datasets
        },
        "terms": {
            code: {
                "fields": sum(n for (_, c), n in fields.items() if c == code),
                "located": sum(n for (_, c), n in located.items() if c == code),
            }
            for code in sorted({c for _, c in fields}, key=lambda c: int(c.split("-")[1]))
        },
        "missed": missed,
    }


def _share(located: int, total: int) -> str:
    return f"{located / total:.1%}" if total else "-"


def render_locations(result: dict[str, Any]) -> list[str]:
    datasets = result["datasets"]
    total = sum(d["fields"] for d in datasets.values())
    found = sum(d["located"] for d in datasets.values())
    lines = [
        "## Field locations in the PDF text layer (P1)",
        "",
        "Click-to-highlight finds each stored value in the PDF's text layer by code "
        "(ADR-029): German and English number and date forms, IBANs with spaces, line terms on "
        "their printed row. Computed from the committed PDFs and the pinned corpus, no model. "
        "Located means a match was found; boxes were spot-checked by eye in the browser, not "
        "against hand-marked boxes.",
        "",
        f"- Fields located: **{found} of {total} ({_share(found, total)})**",
        "",
    ]
    counts = ("invoices", "fields", "located")
    rows = [
        [name, *(str(d[key]) for key in counts), _share(d["located"], d["fields"])]
        for name, d in datasets.items()
    ]
    lines += table(["PDFs", "Invoices", "Fields", "Located", "Share"], rows)
    partial = [
        [code, TERM_NAMES.get(code, code), f"{t['located']} of {t['fields']}"]
        for code, t in result["terms"].items()
        if t["located"] < t["fields"]
    ]
    if partial:
        lines += ["", "Terms not always located:", ""]
        lines += table(["Term", "Name", "Located"], partial)
    return [*lines, ""]
