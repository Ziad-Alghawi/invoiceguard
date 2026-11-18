"""The eval cases: generated invoices (committed files), the ZUGFeRD corpus and the KoSIT
testsuite (pinned downloads, `sources.py`)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from invoiceguard_api.parsing import ParsedInvoice, read_invoice_xml
from invoiceguard_api.parsing.pdf import extract_xml

from invoiceguard_evals.render import render
from invoiceguard_evals.sources import (
    CACHE_DIR,
    PACKAGE_DIR,
    Manifest,
    SourceFile,
    read_source,
    without_attachments,
)
from invoiceguard_evals.specs import ALL, Conflict, InvoiceSpec, truth
from invoiceguard_evals.ubl import to_ubl

GENERATED_DIR = PACKAGE_DIR / "datasets" / "generated"
SetName = Literal["small", "full"]


@dataclass(frozen=True)
class ExtractionCase:
    case_id: str
    dataset: Literal["corpus", "generated"]
    # What the model sees: a PDF without embedded XML.
    pdf: bytes
    truth: ParsedInvoice
    conflicts: tuple[Conflict, ...] = ()


def generated_files(spec: InvoiceSpec) -> dict[str, bytes]:
    """The committed files of one spec: the PDF, its UBL twin and the truth as JSON."""
    return {
        f"{spec.case_id}.pdf": render(spec),
        f"{spec.case_id}.ubl.xml": to_ubl(spec),
        f"{spec.case_id}.truth.json": (truth(spec).model_dump_json(indent=1) + "\n").encode(),
    }


def write_generated(directory: Path = GENERATED_DIR) -> int:
    """Write every spec's files (`invoiceguard-eval generate`); returns the number of files."""
    directory.mkdir(parents=True, exist_ok=True)
    written = 0
    for spec in ALL:
        for name, content in generated_files(spec).items():
            (directory / name).write_bytes(content)
            written += 1
    return written


def selected(tags: frozenset[str], which: SetName) -> bool:
    return which == "full" or "small" in tags


def generated_cases(which: SetName, directory: Path = GENERATED_DIR) -> list[ExtractionCase]:
    """Read from the committed files, so the model sees exactly the bytes the recordings name."""
    return [
        ExtractionCase(
            spec.case_id,
            "generated",
            (directory / f"{spec.case_id}.pdf").read_bytes(),
            ParsedInvoice.model_validate_json(
                (directory / f"{spec.case_id}.truth.json").read_text("utf-8")
            ),
            spec.conflicts,
        )
        for spec in ALL
        if selected(spec.tags, which)
    ]


def corpus_truth(source: SourceFile, pdf: bytes) -> ParsedInvoice:
    """The embedded XML read by our parser, with the per-file overrides from `sources.json`."""
    parsed = read_invoice_xml(extract_xml(pdf))
    if not source.truth_overrides:
        return parsed
    return ParsedInvoice.model_validate({**parsed.model_dump(), **source.truth_overrides})


def corpus_cases(
    manifest: Manifest, which: SetName, cache: Path = CACHE_DIR
) -> list[ExtractionCase]:
    cases = []
    for source in manifest.files:
        if source.set != "corpus" or not selected(source.tags, which):
            continue
        pdf = read_source(source, cache)
        cases.append(
            ExtractionCase(source.id, "corpus", without_attachments(pdf), corpus_truth(source, pdf))
        )
    return cases


def kosit_files(
    manifest: Manifest, which: SetName, cache: Path = CACHE_DIR
) -> list[tuple[SourceFile, bytes]]:
    return [
        (source, read_source(source, cache))
        for source in manifest.files
        if source.set == "kosit" and selected(source.tags, which)
    ]
