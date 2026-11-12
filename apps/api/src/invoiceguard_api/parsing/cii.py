"""UN/CEFACT CII reader: XRechnung CII and ZUGFeRD 2.x / Factur-X (all profiles).

One explicit path per EN 16931 business term (ADR-005). Profiles below EN 16931 (MINIMUM,
BASIC WL) carry no invoice lines, so `lines` is empty for them.
"""

from decimal import Decimal

from lxml import etree

from invoiceguard_api.parsing.model import ParsedInvoice, ParsedLine, VatBreakdown
from invoiceguard_api.parsing.values import ValueReader, cii_date, first_payee_iban, to_decimal

RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
ROOT_TAG = f"{{{RSM}}}CrossIndustryInvoice"

_read = ValueReader(
    {
        "rsm": RSM,
        "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
        "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    }
)

_DOCUMENT = "rsm:ExchangedDocument"
_TRANSACTION = "rsm:SupplyChainTradeTransaction"
_AGREEMENT = f"{_TRANSACTION}/ram:ApplicableHeaderTradeAgreement"
_SETTLEMENT = f"{_TRANSACTION}/ram:ApplicableHeaderTradeSettlement"
_TOTALS = f"{_SETTLEMENT}/ram:SpecifiedTradeSettlementHeaderMonetarySummation"
_SELLER = f"{_AGREEMENT}/ram:SellerTradeParty"
_BUYER = f"{_AGREEMENT}/ram:BuyerTradeParty"
_VAT_ID = "ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']"


def _tax_total(root: etree._Element, currency: str) -> Decimal | None:
    # BT-110 is the amount in the invoice currency; a second one may give BT-111 (VAT currency).
    for amount in _read.nodes(root, f"{_TOTALS}/ram:TaxTotalAmount"):
        if amount.get("currencyID", currency) == currency and amount.text:
            return to_decimal(amount.text.strip(), "BT-110")
    return None


def _vat_breakdown(node: etree._Element) -> VatBreakdown:
    return VatBreakdown(
        category_code=_read.required_text(node, "ram:CategoryCode", "BT-118"),
        rate=_read.decimal(node, "ram:RateApplicablePercent", "BT-119"),
        taxable_amount=_read.required_decimal(node, "ram:BasisAmount", "BT-116"),
        tax_amount=_read.required_decimal(node, "ram:CalculatedAmount", "BT-117"),
    )


def _line(node: etree._Element) -> ParsedLine:
    settlement = "ram:SpecifiedLineTradeSettlement"
    quantity = "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity"
    return ParsedLine(
        line_id=_read.required_text(
            node, "ram:AssociatedDocumentLineDocument/ram:LineID", "BT-126"
        ),
        item_name=_read.required_text(node, "ram:SpecifiedTradeProduct/ram:Name", "BT-153"),
        quantity=_read.required_decimal(node, quantity, "BT-129"),
        unit_code=_read.required_attribute(node, quantity, "unitCode", "BT-130"),
        net_price=_read.required_decimal(
            node,
            "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount",
            "BT-146",
        ),
        net_amount=_read.required_decimal(
            node,
            f"{settlement}/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount",
            "BT-131",
        ),
        vat_rate=_read.decimal(
            node, f"{settlement}/ram:ApplicableTradeTax/ram:RateApplicablePercent", "BT-152"
        ),
    )


def read(root: etree._Element) -> ParsedInvoice:
    issue_date_path = f"{_DOCUMENT}/ram:IssueDateTime/udt:DateTimeString"
    issue_date = _read.required_text(root, issue_date_path, "BT-2")
    due_date_path = (
        f"{_SETTLEMENT}/ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString"
    )
    due_date = _read.text(root, due_date_path)
    currency = _read.required_text(root, f"{_SETTLEMENT}/ram:InvoiceCurrencyCode", "BT-5")
    payee_iban, warnings = first_payee_iban(
        _read.texts(
            root,
            f"{_SETTLEMENT}/ram:SpecifiedTradeSettlementPaymentMeans"
            "/ram:PayeePartyCreditorFinancialAccount/ram:IBANID",
        )
    )
    lines = _read.nodes(root, f"{_TRANSACTION}/ram:IncludedSupplyChainTradeLineItem")
    return ParsedInvoice(
        syntax="cii",
        invoice_number=_read.required_text(root, f"{_DOCUMENT}/ram:ID", "BT-1"),
        issue_date=cii_date(issue_date, _read.attribute(root, issue_date_path, "format"), "BT-2"),
        type_code=_read.required_text(root, f"{_DOCUMENT}/ram:TypeCode", "BT-3"),
        currency=currency,
        due_date=(
            None
            if due_date is None
            else cii_date(due_date, _read.attribute(root, due_date_path, "format"), "BT-9")
        ),
        seller_name=_read.required_text(root, f"{_SELLER}/ram:Name", "BT-27"),
        seller_vat_id=_read.text(root, f"{_SELLER}/{_VAT_ID}"),
        buyer_name=_read.required_text(root, f"{_BUYER}/ram:Name", "BT-44"),
        buyer_vat_id=_read.text(root, f"{_BUYER}/{_VAT_ID}"),
        payee_iban=payee_iban,
        order_reference=_read.text(
            root, f"{_AGREEMENT}/ram:BuyerOrderReferencedDocument/ram:IssuerAssignedID"
        ),
        line_total=_read.decimal(root, f"{_TOTALS}/ram:LineTotalAmount", "BT-106"),
        allowance_total=_read.decimal(root, f"{_TOTALS}/ram:AllowanceTotalAmount", "BT-107"),
        charge_total=_read.decimal(root, f"{_TOTALS}/ram:ChargeTotalAmount", "BT-108"),
        net_total=_read.required_decimal(root, f"{_TOTALS}/ram:TaxBasisTotalAmount", "BT-109"),
        tax_total=_tax_total(root, currency),
        gross_total=_read.required_decimal(root, f"{_TOTALS}/ram:GrandTotalAmount", "BT-112"),
        amount_due=_read.required_decimal(root, f"{_TOTALS}/ram:DuePayableAmount", "BT-115"),
        lines=tuple(_line(line) for line in lines),
        vat_breakdown=tuple(
            _vat_breakdown(group)
            for group in _read.nodes(root, f"{_SETTLEMENT}/ram:ApplicableTradeTax")
        ),
        warnings=warnings,
    )
