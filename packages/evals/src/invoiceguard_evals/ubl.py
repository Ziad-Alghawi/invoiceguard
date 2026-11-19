"""Write an `InvoiceSpec` as XRechnung 3.0 UBL, laid out like the demo samples, so the fraud set
also runs through the XML path (no model) with the same truth as its PDF."""

from decimal import Decimal

from lxml import etree

from invoiceguard_evals.specs import BUYER, InvoiceSpec, Party

UBL = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CUSTOMIZATION = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
PROFILE = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
# Leitweg-ID of the made-up buyer, as in the demo samples (BT-10 is required by XRechnung).
BUYER_REFERENCE = "04011000-12345-34"


def _cac(parent: etree._Element, name: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{CAC}}}{name}")


def _cbc(parent: etree._Element, name: str, text: str, **attributes: str) -> etree._Element:
    element = etree.SubElement(parent, f"{{{CBC}}}{name}", attributes)
    element.text = text
    return element


def _amount(parent: etree._Element, name: str, value: Decimal) -> None:
    _cbc(parent, name, f"{value:.2f}", currencyID="EUR")


def _vat_category(parent: etree._Element, name: str, rate: Decimal) -> None:
    category = _cac(parent, name)
    _cbc(category, "ID", "S")
    _cbc(category, "Percent", f"{rate.normalize():f}")
    _cbc(_cac(category, "TaxScheme"), "ID", "VAT")


def _party(parent: etree._Element, name: str, party: Party, contact: bool) -> None:
    element = _cac(_cac(parent, name), "Party")
    _cbc(element, "EndpointID", party.email, schemeID="EM")
    address = _cac(element, "PostalAddress")
    _cbc(address, "StreetName", party.street)
    _cbc(address, "CityName", party.city)
    _cbc(address, "PostalZone", party.postal_code)
    _cbc(_cac(address, "Country"), "IdentificationCode", "DE")
    tax_scheme = _cac(element, "PartyTaxScheme")
    _cbc(tax_scheme, "CompanyID", party.vat_id)
    _cbc(_cac(tax_scheme, "TaxScheme"), "ID", "VAT")
    _cbc(_cac(element, "PartyLegalEntity"), "RegistrationName", party.name)
    if contact:
        details = _cac(element, "Contact")
        _cbc(details, "Name", "Buchhaltung")
        _cbc(details, "Telephone", "+49 30 1234567")
        _cbc(details, "ElectronicMail", party.email)


def to_ubl(spec: InvoiceSpec) -> bytes:
    root = etree.Element(f"{{{UBL}}}Invoice", nsmap={"ubl": UBL, "cac": CAC, "cbc": CBC})
    _cbc(root, "CustomizationID", CUSTOMIZATION)
    _cbc(root, "ProfileID", PROFILE)
    _cbc(root, "ID", spec.number)
    _cbc(root, "IssueDate", spec.issue_date.isoformat())
    if spec.due_date is not None:
        _cbc(root, "DueDate", spec.due_date.isoformat())
    _cbc(root, "InvoiceTypeCode", "380")
    attack = spec.attack
    if attack is not None and attack.place == "xml_note":
        _cbc(root, "Note", attack.text)
    _cbc(root, "DocumentCurrencyCode", "EUR")
    _cbc(root, "BuyerReference", BUYER_REFERENCE)
    if spec.order_reference is not None:
        _cbc(_cac(root, "OrderReference"), "ID", spec.order_reference)
    _party(root, "AccountingSupplierParty", spec.seller, contact=True)
    _party(root, "AccountingCustomerParty", BUYER, contact=False)
    _cbc(_cac(root, "Delivery"), "ActualDeliveryDate", spec.delivery_date.isoformat())

    means = _cac(root, "PaymentMeans")
    _cbc(means, "PaymentMeansCode", "58")
    _cbc(_cac(means, "PayeeFinancialAccount"), "ID", spec.iban)
    terms = "Zahlbar sofort ohne Abzug." if spec.due_date is None else "Zahlbar ohne Abzug."
    _cbc(_cac(root, "PaymentTerms"), "Note", terms)

    if spec.allowance_total is not None:
        allowance = _cac(root, "AllowanceCharge")
        _cbc(allowance, "ChargeIndicator", "false")
        _cbc(allowance, "AllowanceChargeReason", "Rabatt")
        _amount(allowance, "Amount", spec.allowance_total)
        _vat_category(allowance, "TaxCategory", spec.lines[0].vat_rate)

    tax_total = _cac(root, "TaxTotal")
    _amount(tax_total, "TaxAmount", spec.tax_total)
    for rate, taxable, tax in spec.vat_breakdown():
        subtotal = _cac(tax_total, "TaxSubtotal")
        _amount(subtotal, "TaxableAmount", taxable)
        _amount(subtotal, "TaxAmount", tax)
        _vat_category(subtotal, "TaxCategory", rate)

    totals = _cac(root, "LegalMonetaryTotal")
    _amount(totals, "LineExtensionAmount", spec.line_total)
    _amount(totals, "TaxExclusiveAmount", spec.net_total)
    _amount(totals, "TaxInclusiveAmount", spec.gross_total)
    if spec.allowance_total is not None:
        _amount(totals, "AllowanceTotalAmount", spec.allowance_total)
    _amount(totals, "PayableAmount", spec.gross_total)

    for n, line in enumerate(spec.lines, start=1):
        element = _cac(root, "InvoiceLine")
        _cbc(element, "ID", str(n))
        if n == 1 and attack is not None and attack.place == "xml_line_note":
            _cbc(element, "Note", attack.text)
        _cbc(element, "InvoicedQuantity", f"{line.quantity.normalize():f}", unitCode=line.unit_code)
        _amount(element, "LineExtensionAmount", line.net)
        item = _cac(element, "Item")
        _cbc(item, "Name", line.description)
        _vat_category(item, "ClassifiedTaxCategory", line.vat_rate)
        _amount(_cac(element, "Price"), "PriceAmount", line.price)
    return bytes(etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True))
