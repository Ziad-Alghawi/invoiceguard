"""Parse untrusted XML without entity expansion, DTD loading or network access.

Invoices never need a DTD, so any document type declaration is rejected outright. That blocks
external entities (XXE: reading local files or calling URLs) and entity expansion bombs
("billion laughs") even if a parser default changes in a later lxml version.
"""

from lxml import etree

from invoiceguard_api.parsing.model import InvalidInvoice


def _parser() -> etree.XMLParser:
    # A new parser per call: lxml parsers must not be shared between threads.
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
    )


def parse_xml(content: bytes) -> etree._Element:
    try:
        root = etree.fromstring(content, _parser())
    except etree.XMLSyntaxError as error:
        raise InvalidInvoice(f"The XML is not well-formed: {error}") from None
    # lxml-stubs 0.5.1 lacks DocInfo.doctype, which lxml has had since 2.x.
    if root.getroottree().docinfo.doctype:  # type: ignore[union-attr]
        raise InvalidInvoice("XML with a document type declaration (DTD) is rejected for safety.")
    return root
