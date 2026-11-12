"""Pull the embedded e-invoice XML out of a ZUGFeRD / Factur-X / XRechnung-in-PDF file (ADR-005).

factur-x only finds the attachment here; our own parser reads it. Its XSD check is off: schema
validation is the KoSIT validator's job, and the bundled schemas do not resolve on Windows.
"""

from facturx import get_xml_from_pdf
from pypdf.errors import PyPdfError

from invoiceguard_api.parsing.model import InvalidInvoice, NoEmbeddedXml


def extract_xml(content: bytes) -> bytes:
    try:
        _, xml = get_xml_from_pdf(content, check_xsd=False)
    except PyPdfError as error:
        raise InvalidInvoice(f"The PDF cannot be read: {error}") from None
    if not xml:
        raise NoEmbeddedXml
    return bytes(xml)
