"""mcp-registry: a read-only MCP server with supplier registry checks for the exception agent
(ADR-017).

Tools: is a VAT ID well formed and a known supplier, which supplier an IBAN is registered to,
and a supplier's bank accounts with who verified them since when. The checksums are computed
here; there is no call to an outside register (VIES, banks), which the demo cannot use.

Run with `invoiceguard-mcp-registry` (streamable HTTP on port 8000, path /mcp).
"""

import os
from datetime import date
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from invoiceguard_mcp_registry.db import Database

VatId = Annotated[
    str,
    Field(pattern=r"^[A-Z]{2}[0-9A-Z]{2,13}$", description="VAT ID, e.g. DE999000033"),
]
Iban = Annotated[
    str,
    Field(
        pattern=r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$",
        description="IBAN without spaces, e.g. DE60123456780000000003",
    ),
]
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


class KnownSupplier(BaseModel):
    name: str
    vat_id: str
    country_code: str


class VatIdCheck(BaseModel):
    vat_id: str
    # German VAT IDs only (ISO 7064 MOD 11,10); other countries are not_checked.
    checksum: Literal["valid", "invalid", "not_checked"]
    known_supplier: KnownSupplier | None


class Registration(BaseModel):
    supplier_name: str
    supplier_vat_id: str
    verified: bool
    since: date
    verified_by: str | None


class IbanCheck(BaseModel):
    iban: str
    checksum_valid: bool
    # Empty when no supplier has this IBAN in the registry.
    registered_to: list[Registration]


class BankAccount(BaseModel):
    iban: str
    verified: bool
    since: date
    verified_by: str | None


class BankAccounts(BaseModel):
    vat_id: str
    supplier_found: bool
    supplier_name: str | None
    accounts: list[BankAccount]


# Only the supplier columns this role may read: id, name, vat_id, country_code (migration 0010).
SUPPLIER_SQL = "SELECT id, name, vat_id, country_code FROM suppliers WHERE vat_id = %(vat_id)s"
IBAN_SQL = """
SELECT s.name AS supplier_name, s.vat_id AS supplier_vat_id, a.verified, a.since, a.verified_by
FROM supplier_bank_accounts a JOIN suppliers s ON s.id = a.supplier_id
WHERE a.iban = %(iban)s
ORDER BY a.since
"""
ACCOUNTS_SQL = """
SELECT iban, verified, since, verified_by FROM supplier_bank_accounts
WHERE supplier_id = %(supplier_id)s
ORDER BY since DESC, iban
"""


def iban_checksum_valid(iban: str) -> bool:
    """ISO 13616: move the first four characters to the end, letters to numbers, mod 97 == 1."""
    rearranged = iban[4:] + iban[:4]
    return int("".join(str(int(char, 36)) for char in rearranged)) % 97 == 1


def german_vat_checksum_valid(vat_id: str) -> bool:
    """The German USt-IdNr. check digit (ISO 7064 MOD 11,10): DE and nine digits."""
    digits = vat_id[2:]
    if len(digits) != 9 or not digits.isdigit():
        return False
    product = 10
    for char in digits[:8]:
        total = (int(char) + product) % 10 or 10
        product = (2 * total) % 11
    check = 11 - product
    return (0 if check == 10 else check) == int(digits[8])


def build_server(database: Database) -> MCPServer:
    server = MCPServer(
        name="invoiceguard-mcp-registry",
        instructions="Read-only supplier registry: VAT IDs, IBANs and verified bank accounts.",
        version="0.1.0",
    )

    def known_supplier(vat_id: str) -> dict[str, object] | None:
        rows = database.rows(SUPPLIER_SQL, {"vat_id": vat_id})
        return rows[0] if rows else None

    @server.tool(annotations=READ_ONLY)
    def check_vat_id(vat_id: VatId) -> VatIdCheck:
        """Checks a VAT ID's check digit (German IDs) and whether it is a known supplier."""
        checksum: Literal["valid", "invalid", "not_checked"] = "not_checked"
        if vat_id.startswith("DE"):
            checksum = "valid" if german_vat_checksum_valid(vat_id) else "invalid"
        supplier = known_supplier(vat_id)
        return VatIdCheck(
            vat_id=vat_id,
            checksum=checksum,
            known_supplier=None if supplier is None else KnownSupplier.model_validate(supplier),
        )

    @server.tool(annotations=READ_ONLY)
    def check_iban(iban: Iban) -> IbanCheck:
        """Checks an IBAN's checksum and which suppliers have it in the registry."""
        rows = database.rows(IBAN_SQL, {"iban": iban})
        return IbanCheck(
            iban=iban,
            checksum_valid=iban_checksum_valid(iban),
            registered_to=[Registration.model_validate(row) for row in rows],
        )

    @server.tool(annotations=READ_ONLY)
    def get_bank_accounts(vat_id: VatId) -> BankAccounts:
        """A supplier's bank accounts in the registry: verified or not, since when, by whom."""
        supplier = known_supplier(vat_id)
        if supplier is None:
            return BankAccounts(
                vat_id=vat_id, supplier_found=False, supplier_name=None, accounts=[]
            )
        rows = database.rows(ACCOUNTS_SQL, {"supplier_id": supplier["id"]})
        return BankAccounts(
            vat_id=vat_id,
            supplier_found=True,
            supplier_name=str(supplier["name"]),
            accounts=[BankAccount.model_validate(row) for row in rows],
        )

    return server


def transport_security(allowed_hosts: list[str]) -> TransportSecuritySettings:
    """Only these Host headers are served (DNS rebinding protection); no browser origin."""
    return TransportSecuritySettings(allowed_hosts=allowed_hosts, allowed_origins=[])


def main() -> None:
    database = Database(os.environ["INVOICEGUARD_MCP_REGISTRY_DATABASE_URL"])
    hosts = os.environ.get(
        "INVOICEGUARD_MCP_ALLOWED_HOSTS", "mcp-registry:*,localhost:*,127.0.0.1:*"
    )
    build_server(database).run(
        "streamable-http",
        # All interfaces inside the container; Compose decides who can reach the port.
        host="0.0.0.0",
        port=int(os.environ.get("INVOICEGUARD_MCP_PORT", "8000")),
        stateless_http=True,
        json_response=True,
        transport_security=transport_security(hosts.split(",")),
    )
