"""The JSON the model must return (ADR-010): one value, confidence and evidence per field.

Values are strings, as printed and normalised; `extract.py` turns them into a `ParsedInvoice`,
whose validation does the typing (dates, decimals). `extra="forbid"` everywhere: a reply with
keys we did not ask for (for example an injected `"approved": true`) is rejected as a whole.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Confidence = Annotated[
    float,
    Field(ge=0, le=1, description="0 to 1: how sure you are that the value is what is printed."),
]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1, description="1-based page number the value is printed on.")
    snippet: str = Field(max_length=200, description="The printed text the value comes from.")


class ExtractedField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | None = Field(description="The value, normalised; null if not on the invoice.")
    confidence: Confidence
    evidence: Evidence | None = Field(description="Where the value is printed; null if absent.")


class ExtractedLine(BaseModel):
    """One invoice line (BG-25); confidence and evidence cover the whole line."""

    model_config = ConfigDict(extra="forbid")

    line_id: str | None = Field(description="BT-126 line number or ID as printed.")
    item_name: str | None = Field(description="BT-153 item name.")
    quantity: str | None = Field(description="BT-129 invoiced quantity.")
    unit_code: str | None = Field(description="BT-130 unit, UN/ECE Rec. 20 (C62 piece, HUR hour).")
    net_price: str | None = Field(description="BT-146 net unit price.")
    net_amount: str | None = Field(description="BT-131 line net amount.")
    vat_rate: str | None = Field(description="BT-152 VAT rate in percent, for example 19.")
    confidence: Confidence
    evidence: Evidence | None


class ExtractedVat(BaseModel):
    """One VAT breakdown row (BG-23); confidence and evidence cover the whole row."""

    model_config = ConfigDict(extra="forbid")

    category_code: str | None = Field(
        description="BT-118 UNCL5305 code: S standard, Z zero, E exempt, AE reverse charge."
    )
    rate: str | None = Field(description="BT-119 VAT rate in percent.")
    taxable_amount: str | None = Field(description="BT-116 taxable amount.")
    tax_amount: str | None = Field(description="BT-117 VAT amount.")
    confidence: Confidence
    evidence: Evidence | None


class ExtractedInvoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_number: Annotated[ExtractedField, Field(description="BT-1 invoice number.")]
    issue_date: Annotated[ExtractedField, Field(description="BT-2 issue date, YYYY-MM-DD.")]
    type_code: Annotated[
        ExtractedField, Field(description="BT-3 UNTDID 1001: 380 invoice, 381 credit note.")
    ]
    currency: Annotated[
        ExtractedField, Field(description="BT-5 ISO 4217 currency code, for example EUR.")
    ]
    due_date: Annotated[ExtractedField, Field(description="BT-9 payment due date, YYYY-MM-DD.")]
    seller_name: Annotated[ExtractedField, Field(description="BT-27 seller (supplier) name.")]
    seller_vat_id: Annotated[
        ExtractedField, Field(description="BT-31 seller VAT ID, for example DE123456789.")
    ]
    buyer_name: Annotated[ExtractedField, Field(description="BT-44 buyer name.")]
    buyer_vat_id: Annotated[ExtractedField, Field(description="BT-48 buyer VAT ID.")]
    payee_iban: Annotated[
        ExtractedField, Field(description="BT-84 IBAN to pay to, without spaces.")
    ]
    order_reference: Annotated[
        ExtractedField, Field(description="BT-13 purchase order number of the buyer.")
    ]
    line_total: Annotated[ExtractedField, Field(description="BT-106 sum of line net amounts.")]
    allowance_total: Annotated[
        ExtractedField, Field(description="BT-107 sum of document-level allowances.")
    ]
    charge_total: Annotated[
        ExtractedField, Field(description="BT-108 sum of document-level charges.")
    ]
    net_total: Annotated[ExtractedField, Field(description="BT-109 total without VAT.")]
    tax_total: Annotated[ExtractedField, Field(description="BT-110 total VAT amount.")]
    gross_total: Annotated[ExtractedField, Field(description="BT-112 total with VAT.")]
    amount_due: Annotated[ExtractedField, Field(description="BT-115 amount due for payment.")]
    lines: list[ExtractedLine]
    vat_breakdown: list[ExtractedVat]
