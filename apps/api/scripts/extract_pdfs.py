"""Manual check of LLM extraction with a real API key; not run in CI (ADR-010).

Sends each PDF to the configured model (INVOICEGUARD_EXTRACTION_MODEL) and prints every field
with its confidence and evidence, then cost and time per invoice. Nothing is stored. If a file
`<name>.expected.json` (a `ParsedInvoice` as JSON, for example read from the XML the PDF came
with) lies next to a PDF, each document-level field is compared with it.

Only send made-up or public sample invoices: the Gemini free tier may use inputs to improve
Google's models.

Run from apps/api, with INVOICEGUARD_LLM_API_KEY set in the root .env:

    uv run --env-file ../../.env python scripts/extract_pdfs.py a.pdf b.pdf c.pdf
"""

import argparse
import sys
import time
from decimal import Decimal
from pathlib import Path

from invoiceguard_api.extraction import ExtractionResult, PdfExtractor
from invoiceguard_api.main import make_extractor
from invoiceguard_api.parsing import ParsedInvoice
from invoiceguard_api.parsing.fields import DOCUMENT_TERMS
from invoiceguard_api.settings import get_settings

SNIPPET_WIDTH = 50


def _expected(path: Path) -> ParsedInvoice | None:
    expected = path.with_suffix(".expected.json")
    if not expected.exists():
        return None
    return ParsedInvoice.model_validate_json(expected.read_text("utf-8"))


def _print_result(
    path: Path,
    result: ExtractionResult,
    threshold: Decimal,
    seconds: float,
    expected: ParsedInvoice | None,
) -> tuple[int, int]:
    """Print one result; returns (fields equal to the expected values, fields compared)."""
    equal = compared = 0
    print(f"\n=== {path.name}")
    for call in result.calls:
        print(
            f"call: {call.status.value}, {call.input_tokens} in / {call.output_tokens} out tokens, "
            f"${call.cost_usd}, {call.latency_ms} ms" + (f" ({call.error})" if call.error else "")
        )
    if result.extraction is None:
        print(f"FAILED: {result.failure}")
    else:
        invoice: ParsedInvoice = result.extraction.invoice
        print(f"{'field':<17} {'code':<7} {'conf':>5}  {'value':<30} evidence")
        for field in result.extraction.confidences:
            if field.code is not None:
                value = getattr(invoice, field.name)
            elif field.line_no is not None:
                line = invoice.lines[field.line_no - 1]
                value = f"{line.quantity} {line.unit_code} x {line.net_price} = {line.net_amount}"
            else:
                value = ""
            flag = "  LOW" if field.confidence < threshold else ""
            if expected is not None and field.code is not None:
                compared += 1
                want = getattr(expected, field.name)
                if want == value:
                    equal += 1
                else:
                    flag += f"  DIFF (XML: {want})"
            evidence = field.evidence or {}
            # Snippets can span lines on the page; one line per field keeps the table readable.
            snippet = " ".join(str(evidence.get("snippet", "")).split())[:SNIPPET_WIDTH]
            page = f"p{evidence['page']}: " if evidence else ""
            print(
                f"{field.name:<17} {field.code or '':<7} {field.confidence:>5}  "
                f"{str(value)[:30]:<30} {page}{snippet}{flag}"
            )
    cost = sum((call.cost_usd or Decimal(0) for call in result.calls), Decimal(0))
    if expected is not None and result.extraction is not None:
        lines = (len(result.extraction.invoice.lines), len(expected.lines))
        print(f"fields equal to the XML: {equal}/{compared}; lines {lines[0]} (XML: {lines[1]})")
    print(f"total: ${cost} in {seconds:.1f} s ({len(result.calls)} call(s))")
    return equal, compared


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pdfs", nargs="+", type=Path, help="PDF invoices without e-invoice XML")
    args = parser.parse_args()

    settings = get_settings()
    extractor: PdfExtractor | None = make_extractor(settings, None)
    if extractor is None:
        print("INVOICEGUARD_LLM_API_KEY is not set; see the docstring.", file=sys.stderr)
        return 2
    print(
        f"model: {extractor.model}, reasoning effort: {extractor.reasoning_effort}, "
        f"confidence threshold: {extractor.confidence_threshold}"
    )

    costs: list[Decimal] = []
    seconds: list[float] = []
    equal = compared = 0
    for path in args.pdfs:
        start = time.perf_counter()
        result = extractor.extract(path.read_bytes())
        seconds.append(time.perf_counter() - start)
        costs.append(sum((call.cost_usd or Decimal(0) for call in result.calls), Decimal(0)))
        counts = _print_result(
            path, result, extractor.confidence_threshold, seconds[-1], _expected(path)
        )
        equal, compared = equal + counts[0], compared + counts[1]

    print(
        f"\n{len(costs)} invoice(s): mean ${sum(costs) / len(costs):.6f} and "
        f"{sum(seconds) / len(seconds):.1f} s per invoice, total ${sum(costs)}"
    )
    if compared:
        print(
            f"document fields equal to the XML: {equal}/{compared} "
            f"({len(DOCUMENT_TERMS)} per invoice)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
