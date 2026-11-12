"""Deterministic e-invoice reader (ADR-005): XRechnung UBL/CII and ZUGFeRD 2.x / Factur-X.

Pure functions with no database access. Invoice content is untrusted data throughout.
"""

from invoiceguard_api.models import SourceType
from invoiceguard_api.parsing import cii, ubl
from invoiceguard_api.parsing.model import (
    InvalidInvoice,
    NoEmbeddedXml,
    ParsedInvoice,
    ParsedLine,
    ParseError,
    UnsupportedFormat,
)
from invoiceguard_api.parsing.pdf import extract_xml
from invoiceguard_api.parsing.safe_xml import parse_xml

ZUGFERD_1_TAG = "{urn:ferd:CrossIndustryDocument:invoice:1p0}CrossIndustryDocument"
# The root tag comes from the file; keep it short in the reason shown to users.
MAX_TAG_IN_REASON = 120

__all__ = [
    "InvalidInvoice",
    "NoEmbeddedXml",
    "ParseError",
    "ParsedInvoice",
    "ParsedLine",
    "UnsupportedFormat",
    "parse_invoice",
]


def parse_invoice(content: bytes, source_type: SourceType) -> ParsedInvoice:
    """Read an uploaded file; raises ParseError subclasses or NoEmbeddedXml (plain PDF)."""
    xml = extract_xml(content) if source_type is SourceType.PDF else content
    root = parse_xml(xml)
    if root.tag == cii.ROOT_TAG:
        return cii.read(root)
    if root.tag == ubl.ROOT_TAG:
        return ubl.read(root)
    if root.tag == ubl.CREDIT_NOTE_TAG:
        raise UnsupportedFormat("UBL credit notes are not supported yet.")
    if root.tag == ZUGFERD_1_TAG:
        raise UnsupportedFormat(
            "ZUGFeRD 1.0 is not supported (superseded by ZUGFeRD 2 in 2019). "
            "Ask the supplier for ZUGFeRD 2.x, Factur-X or XRechnung."
        )
    tag = str(root.tag)[:MAX_TAG_IN_REASON]
    raise UnsupportedFormat(f"Unknown invoice format (root element {tag}).")
