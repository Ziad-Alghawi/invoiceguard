"""What the exception agent may do (ADR-018): the allow-listed read-only tools and the one JSON
action the model returns per step.

Each tool takes exactly one argument, so a tool call is a name from a closed list and a short
string. There is no action that approves, changes a status or sends anything.
"""

from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Server = Literal["erp", "registry"]
ToolName = Literal[
    "get_supplier",
    "list_purchase_orders",
    "get_purchase_order",
    "get_goods_receipts",
    "check_vat_id",
    "check_iban",
    "get_bank_accounts",
]


@dataclass(frozen=True)
class ToolSpec:
    server: Server
    # The MCP tool's one parameter.
    parameter: str
    # What the prompt tells the model about the tool.
    description: str


# The allow-list (ADR-017's tools). Only these names reach an MCP server.
TOOLS: dict[str, ToolSpec] = {
    "get_supplier": ToolSpec(
        "erp", "vat_id", "ERP supplier master data (name, address, contact) by VAT ID."
    ),
    "list_purchase_orders": ToolSpec(
        "erp", "vat_id", "The supplier's purchase orders, newest first, with net amounts."
    ),
    "get_purchase_order": ToolSpec(
        "erp",
        "number",
        "One purchase order by number: lines, prices, VAT rates and the quantity received.",
    ),
    "get_goods_receipts": ToolSpec(
        "erp", "po_number", "The goods receipts (deliveries) booked against an order number."
    ),
    "check_vat_id": ToolSpec(
        "registry", "vat_id", "Registry: is the VAT ID valid (German check digit) and known?"
    ),
    "check_iban": ToolSpec(
        "registry", "iban", "Registry: IBAN checksum and the suppliers the IBAN is registered to."
    ),
    "get_bank_accounts": ToolSpec(
        "registry",
        "vat_id",
        "Registry: the supplier's bank accounts, verified since when, by whom.",
    ),
}
MAX_CALLS_PER_STEP = 3


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: ToolName
    # A VAT ID (DE999000033), an IBAN without spaces, or an order number (PO-2026-0005).
    argument: str = Field(min_length=1, max_length=50)


class AgentAction(BaseModel):
    """One step's reply: call up to three tools, or finish with a finding and an email draft.

    Every field is required (null or empty when unused): models with structured output leave
    out optional fields, and a `finish` without its email is useless (journal, 2026-11-18).
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["call_tools", "finish"]
    tool_calls: list[ToolCall] = Field(max_length=MAX_CALLS_PER_STEP)
    # English, for the reviewer: what the investigation found, with the evidence.
    finding: str | None = Field(max_length=2000)
    # German, to the supplier; a draft a person may send or not.
    email_subject: str | None = Field(max_length=200)
    email_body: str | None = Field(max_length=4000)

    @model_validator(mode="after")
    def _complete(self) -> Self:
        if self.action == "call_tools" and not self.tool_calls:
            raise ValueError("call_tools needs at least one tool call")
        if self.action == "finish":
            if self.tool_calls:
                raise ValueError("finish must not call tools")
            if not (self.finding and self.email_subject and self.email_body):
                raise ValueError("finish needs finding, email_subject and email_body")
        return self


SCHEMA_NAME = "exception_agent_action"
SCHEMA = AgentAction.model_json_schema()
