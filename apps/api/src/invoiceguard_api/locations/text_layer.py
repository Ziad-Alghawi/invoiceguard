"""The text layer of a PDF with a box for every character, read with pdfminer.six.

pdfminer groups characters into lines; each page becomes one string (lines joined by line
breaks) and a list with the box of every character in it, so a regular expression match on the
string maps back to boxes on the page. Boxes are fractions of the page with the origin at the
top left, the way the browser draws them.
"""

import io
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTChar, LTComponent, LTContainer, LTPage, LTTextLine
from pdfminer.pdfparser import PDFSyntaxError
from pdfminer.psparser import PSException

# A long PDF is read only this far: invoices print what matters on the first pages, and an
# uploaded file must not keep a worker busy for long.
MAX_PAGES = 20


@dataclass(frozen=True)
class Box:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class PageText:
    number: int
    text: str
    # One entry per character of `text`; None for the spaces and line breaks pdfminer inserts.
    boxes: tuple[Box | None, ...]
    # The index of the text line each character belongs to, so a match over two lines gets a
    # box per line.
    lines: tuple[int, ...]


class UnreadablePdf(Exception):
    """pdfminer could not read the file's text layer."""


def _text_lines(item: LTComponent) -> Iterator[LTTextLine]:
    if isinstance(item, LTTextLine):
        yield item
    elif isinstance(item, LTContainer):
        for child in item:
            yield from _text_lines(child)


def _page(number: int, layout: LTPage) -> PageText:
    x0, y0, x1, y1 = layout.bbox
    width, height = (x1 - x0) or 1, (y1 - y0) or 1
    text: list[str] = []
    boxes: list[Box | None] = []
    lines: list[int] = []
    for line_index, line in enumerate(_text_lines(layout)):
        for item in line:
            char = item.get_text()
            box = (
                Box(
                    number,
                    (item.x0 - x0) / width,
                    (y1 - item.y1) / height,
                    (item.x1 - x0) / width,
                    (y1 - item.y0) / height,
                )
                if isinstance(item, LTChar)
                else None
            )
            # NFKC turns ligatures and full-width forms into the letters a value is stored in;
            # one character may become several, all with the same box.
            for normal in unicodedata.normalize("NFKC", char):
                text.append(normal)
                boxes.append(box)
                lines.append(line_index)
        if not text or text[-1] != "\n":
            text.append("\n")
            boxes.append(None)
            lines.append(line_index)
    return PageText(number, "".join(text), tuple(boxes), tuple(lines))


def read_text_layer(pdf: bytes, max_pages: int = MAX_PAGES) -> list[PageText]:
    """The pages' text with character boxes; an empty list for a PDF without a text layer."""
    try:
        return [
            _page(number, layout)
            for number, layout in enumerate(
                extract_pages(io.BytesIO(pdf), maxpages=max_pages, laparams=LAParams()), start=1
            )
        ]
    except (PDFSyntaxError, PSException, ValueError, KeyError, TypeError) as error:
        raise UnreadablePdf(str(error)) from error
