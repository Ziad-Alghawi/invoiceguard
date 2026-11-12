"""UBL 2.1 Invoice reader (XRechnung UBL). UBL credit notes are not read yet.

One explicit path per EN 16931 business term (ADR-005).
"""

from decimal import Decimal

from lxml import etree

from invoiceguard_api.parsing.model import ParsedInvoice, ParsedLine, VatBreakdown
from invoiceguard_api.parsing.values import ValueReader, first_payee_iban, iso_date, to_decimal

INVOICE_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
ROOT_TAG = f"{{{INVOICE_NS}}}Invoice"
CREDIT_NOTE_TAG = "{urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2}CreditNote"

_read = ValueReader(
    {
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    }
)

_SELLER = "cac:AccountingSupplierParty/cac:Party"
_BUYER = "cac:AccountingCustomerParty/cac:Party"
_TOTALS = "cac:LegalMonetaryTotal"
_NAME = "cac:PartyLegalEntity/cbc:RegistrationName"
_VAT_ID = "cac:PartyTaxScheme[cac:TaxScheme/cbc:ID='VAT']/cbc:CompanyID"


def _tax_total(root: etree._Element, currency: str) -> Decimal | None:
    # BT-110 is the TaxTotal in the invoice currency; a second one may give BT-111.
    for amount in _read.nodes(root, "cac:TaxTotal/cbc:TaxAmount"):
        if amount.get("currencyID", currency) == currency and amount.text:
            return to_decimal(amount.text.strip(), "BT-110")
    return None


def _vat_breakdown(node: etree._Element) -> VatBreakdown:
    return VatBreakdown(
        category_code=_read.required_text(node, "cac:TaxCategory/cbc:ID", "BT-118"),
        rate=_read.decimal(node, "cac:TaxCategory/cbc:Percent", "BT-119"),
        taxable_amount=_read.required_decimal(node, "cbc:TaxableAmount", "BT-116"),
        tax_amount=_read.required_decimal(node, "cbc:TaxAmount", "BT-117"),
    )


def _line(node: etree._Element) -> ParsedLine:
    return ParsedLine(
        line_id=_read.required_text(node, "cbc:ID", "BT-126"),
        item_name=_read.required_text(node, "cac:Item/cbc:Name", "BT-153"),
        quantity=_read.required_decimal(node, "cbc:InvoicedQuantity", "BT-129"),
        unit_code=_read.required_attribute(node, "cbc:InvoicedQuantity", "unitCode", "BT-130"),
        net_price=_read.required_decimal(node, "cac:Price/cbc:PriceAmount", "BT-146"),
        net_amount=_read.required_decimal(node, "cbc:LineExtensionAmount", "BT-131"),
        vat_rate=_read.decimal(node, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent", "BT-152"),
    )


def read(root: etree._Element) -> ParsedInvoice:
    currency = _read.required_text(root, "cbc:DocumentCurrencyCode", "BT-5")
    due_date = _read.text(root, "cbc:DueDate")
    # Direct debit (code 59) carries the buyer's account in PaymentMandate, not here (BT-91).
    payee_iban, warnings = first_payee_iban(
        _read.texts(root, "cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID")
    )
    return ParsedInvoice(
        syntax="ubl",
        invoice_number=_read.required_text(root, "cbc:ID", "BT-1"),
        issue_date=iso_date(_read.required_text(root, "cbc:IssueDate", "BT-2"), "BT-2"),
        type_code=_read.required_text(root, "cbc:InvoiceTypeCode", "BT-3"),
        currency=currency,
        due_date=None if due_date is None else iso_date(due_date, "BT-9"),
        seller_name=_read.required_text(root, f"{_SELLER}/{_NAME}", "BT-27"),
        seller_vat_id=_read.text(root, f"{_SELLER}/{_VAT_ID}"),
        buyer_name=_read.required_text(root, f"{_BUYER}/{_NAME}", "BT-44"),
        buyer_vat_id=_read.text(root, f"{_BUYER}/{_VAT_ID}"),
        payee_iban=payee_iban,
        order_reference=_read.text(root, "cac:OrderReference/cbc:ID"),
        line_total=_read.decimal(root, f"{_TOTALS}/cbc:LineExtensionAmount", "BT-106"),
        allowance_total=_read.decimal(root, f"{_TOTALS}/cbc:AllowanceTotalAmount", "BT-107"),
        charge_total=_read.decimal(root, f"{_TOTALS}/cbc:ChargeTotalAmount", "BT-108"),
        net_total=_read.required_decimal(root, f"{_TOTALS}/cbc:TaxExclusiveAmount", "BT-109"),
        tax_total=_tax_total(root, currency),
        gross_total=_read.required_decimal(root, f"{_TOTALS}/cbc:TaxInclusiveAmount", "BT-112"),
        amount_due=_read.required_decimal(root, f"{_TOTALS}/cbc:PayableAmount", "BT-115"),
        lines=tuple(_line(line) for line in _read.nodes(root, "cac:InvoiceLine")),
        # Only the TaxTotal in the invoice currency has the breakdown (BG-23).
        vat_breakdown=tuple(
            _vat_breakdown(group) for group in _read.nodes(root, "cac:TaxTotal/cac:TaxSubtotal")
        ),
        warnings=warnings,
    )
