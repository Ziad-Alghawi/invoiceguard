"""Typed value lookups by XPath, shared by the CII and UBL readers."""

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from lxml import etree

from invoiceguard_api.parsing.model import InvalidInvoice

logger = logging.getLogger(__name__)

# CII date format code 102 (UNTDID 2379): CCYYMMDD, the only one EN 16931 allows.
CII_DATE_FORMAT = "102"


class ValueReader:
    """XPath 1.0 lookups relative to a node, with fixed namespace prefixes."""

    def __init__(self, namespaces: dict[str, str]) -> None:
        self.namespaces = namespaces

    def nodes(self, node: etree._Element, path: str) -> list[etree._Element]:
        found = node.xpath(path, namespaces=self.namespaces)
        if not isinstance(found, list):
            raise TypeError(f"XPath {path!r} must select nodes")
        return [item for item in found if isinstance(item, etree._Element)]

    def texts(self, node: etree._Element, path: str) -> list[str]:
        """Stripped, non-empty texts of all matches, in document order."""
        return [
            found.text.strip()
            for found in self.nodes(node, path)
            if found.text and found.text.strip()
        ]

    def text(self, node: etree._Element, path: str) -> str | None:
        """Stripped text of the first match; None when absent or empty."""
        found = self.nodes(node, path)
        if not found or found[0].text is None:
            return None
        return found[0].text.strip() or None

    def attribute(self, node: etree._Element, path: str, name: str) -> str | None:
        found = self.nodes(node, path)
        value = found[0].get(name) if found else None
        if value is None:
            return None
        return value.strip() or None

    def required_attribute(self, node: etree._Element, path: str, name: str, term: str) -> str:
        value = self.attribute(node, path, name)
        if value is None:
            raise InvalidInvoice(f"Required field {term} is missing.")
        return value

    def required_text(self, node: etree._Element, path: str, term: str) -> str:
        value = self.text(node, path)
        if value is None:
            raise InvalidInvoice(f"Required field {term} is missing.")
        return value

    def decimal(self, node: etree._Element, path: str, term: str) -> Decimal | None:
        value = self.text(node, path)
        return None if value is None else to_decimal(value, term)

    def required_decimal(self, node: etree._Element, path: str, term: str) -> Decimal:
        return to_decimal(self.required_text(node, path, term), term)


def first_payee_iban(ibans: list[str]) -> tuple[str | None, tuple[str, ...]]:
    """The first payee IBAN (BT-84), plus a warning when the invoice names more than one.

    EN 16931 allows several payment-means groups. R1 stores only the first; the warning lets
    the IBAN check (R1-4) flag the invoice instead of silently ignoring the others.
    """
    distinct = list(dict.fromkeys(iban.replace(" ", "").upper() for iban in ibans))
    if len(distinct) <= 1:
        return (distinct[0] if distinct else None), ()
    logger.warning("Invoice names %d different payee IBANs; storing the first", len(distinct))
    return distinct[0], (f"multiple_payee_ibans: {len(distinct)} found, stored the first",)


def to_decimal(value: str, term: str) -> Decimal:
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise InvalidInvoice(f"{term} is not a number.") from None
    if not number.is_finite():
        raise InvalidInvoice(f"{term} is not a number.")
    return number


def iso_date(value: str, term: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InvalidInvoice(f"{term} is not a date (YYYY-MM-DD).") from None


def cii_date(value: str, date_format: str | None, term: str) -> date:
    if date_format != CII_DATE_FORMAT:
        raise InvalidInvoice(f"{term} uses date format {date_format!r}; only 102 is supported.")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        raise InvalidInvoice(f"{term} is not a date (CCYYMMDD).") from None
