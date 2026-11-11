"""Decide the type of an uploaded invoice from its content, not from what the client claims.

This is a cheap first gate. The parser (ADR-005) still rejects XML that is not UBL or CII.
"""

import re
from pathlib import PureWindowsPath

from invoiceguard_api.models import SourceType

UTF8_BOM = b"\xef\xbb\xbf"
# An XML declaration, or a root element (optionally prefixed, e.g. <rsm:CrossIndustryInvoice>).
# Comments, doctypes and processing instructions other than the declaration are not accepted.
XML_START = re.compile(rb"<\?xml[\s?]|<[A-Za-z_][\w.\-]*(:[A-Za-z_][\w.\-]*)?[\s/>]")
EXTENSIONS = {".xml": SourceType.XML, ".pdf": SourceType.PDF}


def detect_source_type(content: bytes) -> SourceType | None:
    if content.startswith(b"%PDF-"):
        return SourceType.PDF
    text_start = content.removeprefix(UTF8_BOM).lstrip(b" \t\r\n")
    if XML_START.match(text_start):
        return SourceType.XML
    return None


def source_type_for(filename: str, content: bytes) -> SourceType | None:
    """The type when the file extension and the content agree, otherwise None."""
    detected = detect_source_type(content)
    claimed = EXTENSIONS.get(PureWindowsPath(filename).suffix.lower())
    return detected if detected is not None and detected == claimed else None


def safe_filename(filename: str) -> str:
    """The base name the client sent, for display only; never used to build a path."""
    # PureWindowsPath splits on both / and \, so "C:\\Users\\x\\a.pdf" and "../a.pdf" give "a.pdf".
    return PureWindowsPath(filename).name[:255]
