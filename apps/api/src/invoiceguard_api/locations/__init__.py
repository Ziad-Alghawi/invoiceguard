"""Where each field value is printed in an invoice PDF (P1 click-to-highlight, ADR-029).

Found by code in the PDF's text layer, never by a model:

- a value read from XML (a ZUGFeRD PDF) is searched on every page with the patterns in
  `matching.py`;
- a value the LLM extracted comes with evidence: the page and the printed text it read the value
  from. The printed text is searched on that page, and the value inside it, so the box is as tight
  as the evidence allows. Without a match there, the value is searched on that page alone.

Line terms are searched row by row. The line's item name (BT-153), else its net amount (BT-131),
is found first, after where the line before was found; the line's other terms are then looked for
on the same printed row, so a quantity "1" is the one in that row and not a page number. A term
not on that row is searched after the line before, as the anchor was.

A field whose value is not in the text layer is "not located"; nothing is guessed.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from invoiceguard_api.locations.matching import text_pattern, value_pattern
from invoiceguard_api.locations.text_layer import Box, PageText, UnreadablePdf, read_text_layer

__all__ = [
    "Box",
    "FieldLocation",
    "FieldToLocate",
    "UnreadablePdf",
    "locate_fields",
    "read_text_layer",
]

Method = Literal["text", "evidence"]


@dataclass(frozen=True)
class FieldToLocate:
    code: str
    line_no: int | None
    value: str
    # LLM extraction only: {"page": 1, "snippet": "..."} (ADR-010).
    evidence: dict[str, Any] | None = None


@dataclass(frozen=True)
class FieldLocation:
    code: str
    line_no: int | None
    method: Method | None
    # Empty when the value was not located; one box per text line of the match.
    boxes: tuple[Box, ...]

    @property
    def located(self) -> bool:
        return bool(self.boxes)


@dataclass(frozen=True)
class _Match:
    page: PageText
    start: int
    end: int


def _boxes(match: _Match) -> tuple[Box, ...]:
    """The union of the matched characters' boxes, one per text line."""
    by_line: dict[int, list[Box]] = {}
    for index in range(match.start, match.end):
        box = match.page.boxes[index]
        if box is not None:
            by_line.setdefault(match.page.lines[index], []).append(box)
    return tuple(
        Box(
            boxes[0].page,
            min(b.x0 for b in boxes),
            min(b.y0 for b in boxes),
            max(b.x1 for b in boxes),
            max(b.y1 for b in boxes),
        )
        for _, boxes in sorted(by_line.items())
    )


def _search(
    pattern: re.Pattern[str], pages: Sequence[PageText], after: tuple[int, int] = (0, 0)
) -> _Match | None:
    """The first match at or after (page number, offset), in reading order."""
    for page in pages:
        if page.number < after[0]:
            continue
        start = after[1] if page.number == after[0] else 0
        found = pattern.search(page.text, start)
        if found:
            return _Match(page, found.start(), found.end())
    return None


# The terms a line is found by, in order of preference: printed once per line and long.
ANCHORS = ("BT-153", "BT-131")


def _on_row(pattern: re.Pattern[str], anchor: _Match) -> _Match | None:
    """The first match whose characters sit on the anchor's printed row (vertical overlap)."""
    rows = _boxes(anchor)
    top, bottom = rows[0].y0, rows[0].y1
    for found in pattern.finditer(anchor.page.text):
        boxes = _boxes(_Match(anchor.page, found.start(), found.end()))
        if boxes and any(min(b.y1, bottom) - max(b.y0, top) > 0 for b in boxes):
            return _Match(anchor.page, found.start(), found.end())
    return None


def _evidence_page(evidence: dict[str, Any] | None, pages: Sequence[PageText]) -> PageText | None:
    number = evidence.get("page") if evidence else None
    return next((page for page in pages if page.number == number), None)


def _by_evidence(field: FieldToLocate, pages: Sequence[PageText]) -> _Match | None:
    page = _evidence_page(field.evidence, pages)
    if page is None:
        return None
    pattern = value_pattern(field.code, field.value)
    snippet = str((field.evidence or {}).get("snippet") or "").strip()
    if snippet:
        found = re.compile(text_pattern(snippet), re.IGNORECASE).search(page.text)
        if found:
            inner = pattern.search(page.text, found.start(), found.end()) if pattern else None
            if inner:
                return _Match(page, inner.start(), inner.end())
            return _Match(page, found.start(), found.end())
    return _search(pattern, [page]) if pattern else None


def _by_text(
    field: FieldToLocate, pages: Sequence[PageText], after: tuple[int, int]
) -> _Match | None:
    pattern = value_pattern(field.code, field.value)
    if pattern is None:
        return None
    # A line printed in another order than the XML: search the whole document as well.
    return _search(pattern, pages, after) or (_search(pattern, pages) if after != (0, 0) else None)


def _locate_line(
    fields: Sequence[FieldToLocate], pages: Sequence[PageText], after: tuple[int, int]
) -> tuple[list[_Match | None], tuple[int, int]]:
    """The matches of one invoice line's terms, and where the next line's search starts."""
    anchor_field = next(
        (f for code in ANCHORS for f in fields if f.code == code and not f.evidence), None
    )
    anchor = _by_text(anchor_field, pages, after) if anchor_field else None
    matches: list[_Match | None] = []
    for field in fields:
        if field.evidence:
            matches.append(_by_evidence(field, pages))
        elif field is anchor_field:
            matches.append(anchor)
        else:
            pattern = value_pattern(field.code, field.value)
            row = _on_row(pattern, anchor) if pattern and anchor else None
            matches.append(row or _by_text(field, pages, after))
    if anchor is not None:
        after = (anchor.page.number, anchor.end)
    return matches, after


def _location(field: FieldToLocate, match: _Match | None) -> FieldLocation:
    boxes = _boxes(match) if match else ()
    method: Method = "evidence" if field.evidence else "text"
    return FieldLocation(field.code, field.line_no, method if boxes else None, boxes)


def locate_fields(
    fields: Sequence[FieldToLocate], pages: Sequence[PageText]
) -> list[FieldLocation]:
    """One location per field, in the order given."""
    matches: dict[int, _Match | None] = {}
    lines: dict[int, list[int]] = {}
    for index, field in enumerate(fields):
        if field.line_no is None:
            matches[index] = (
                _by_evidence(field, pages) if field.evidence else _by_text(field, pages, (0, 0))
            )
        else:
            lines.setdefault(field.line_no, []).append(index)
    after = (0, 0)
    for line_no in sorted(lines):
        indexes = lines[line_no]
        found, after = _locate_line([fields[i] for i in indexes], pages, after)
        matches.update(zip(indexes, found, strict=True))
    return [_location(field, matches[index]) for index, field in enumerate(fields)]
