"""What the exception agent may do (ADR-018): the allow-listed read-only tools and the one JSON
action the model returns per step.

Each tool takes exactly one argument, so a tool call is a name from a closed list and a short
string, which must match the tool's pattern before anything is sent (the MCP server checks it
again). There is no action that approves, changes a status or sends anything.
"""

import re
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Server = Literal["erp", "registry", "history"]
ToolName = Literal[
    "get_supplier",
    "list_purchase_orders",
    "get_purchase_order",
    "get_goods_receipts",
    "check_vat_id",
    "check_iban",
    "get_bank_accounts",
    "get_invoice_history",
    "search_similar_invoices",
    "search_rulebook",
]
# The argument shapes, as the MCP servers define them.
VAT_ID = r"[A-Z]{2}[0-9A-Z]{2,13}"
IBAN = r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}"
ORDER_NUMBER = r"[A-Za-z0-9][A-Za-z0-9./_-]{0,49}"
# search_similar_invoices compares the invoice under investigation only: the model writes
# "current" and the loop passes that invoice's id, so the model never sees or chooses an id.
CURRENT_INVOICE = "current"
# A question in words: no control characters, 3 to 200 characters.
QUERY = r"[^\x00-\x1f\x7f]{3,200}"
MAX_ARGUMENT_CHARS = 200


@dataclass(frozen=True)
class ToolSpec:
    server: Server
    # The MCP tool's one parameter.
    parameter: str
    # What the prompt tells the model about the tool.
    description: str
    # The argument's pattern, matched in full in code before the call.
    pattern: str
    # The api embeds the argument and passes the vector too (`query_vector`): the MCP server
    # has no model key, and the cost counts against the agent's cost cap.
    embeds_query: bool = False
    # The argument is CURRENT_INVOICE; the server gets the investigated invoice's id instead.
    current_invoice: bool = False

    def accepts(self, argument: str) -> bool:
        return re.fullmatch(self.pattern, argument) is not None


# The allow-list (ADR-017's tools). Only these names reach an MCP server.
TOOLS: dict[str, ToolSpec] = {
    "get_supplier": ToolSpec(
        "erp", "vat_id", "ERP supplier master data (name, address, contact) by VAT ID.", VAT_ID
    ),
    "list_purchase_orders": ToolSpec(
        "erp", "vat_id", "The supplier's purchase orders, newest first, with net amounts.", VAT_ID
    ),
    "get_purchase_order": ToolSpec(
        "erp",
        "number",
        "One purchase order by number: lines, prices, VAT rates and the quantity received.",
        ORDER_NUMBER,
    ),
    "get_goods_receipts": ToolSpec(
        "erp",
        "po_number",
        "The goods receipts (deliveries) booked against an order number.",
        ORDER_NUMBER,
    ),
    "check_vat_id": ToolSpec(
        "registry",
        "vat_id",
        "Registry: is the VAT ID valid (German check digit) and known?",
        VAT_ID,
    ),
    "check_iban": ToolSpec(
        "registry",
        "iban",
        "Registry: IBAN checksum and the suppliers the IBAN is registered to.",
        IBAN,
    ),
    "get_bank_accounts": ToolSpec(
        "registry",
        "vat_id",
        "Registry: the supplier's bank accounts, verified since when, by whom.",
        VAT_ID,
    ),
    "get_invoice_history": ToolSpec(
        "history",
        "vat_id",
        "History: the supplier's past approved invoices, newest first, with the accounts booked "
        "and, where known, totals and payee IBAN.",
        VAT_ID,
    ),
    "search_similar_invoices": ToolSpec(
        "history",
        "invoice_id",
        "History: past approved invoices with lines like those of the invoice under "
        f'investigation (argument: "{CURRENT_INVOICE}"), with the accounts booked.',
        CURRENT_INVOICE,
        current_invoice=True,
    ),
    "search_rulebook": ToolSpec(
        "history",
        "query",
        "Our accounts-payable rulebook: what a check means, its thresholds, how to resolve it, "
        "SKR03 accounts. The argument is a short question in English or German.",
        QUERY,
        embeds_query=True,
    ),
}
MAX_CALLS_PER_STEP = 3


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: ToolName
    # A VAT ID, an IBAN, an order number, "current" or a question; each tool's pattern is
    # checked in code before the call (ToolSpec.accepts).
    argument: str = Field(min_length=1, max_length=MAX_ARGUMENT_CHARS)


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
