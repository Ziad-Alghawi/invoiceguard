"""German demo master data: suppliers with verified bank accounts, and purchase orders.

Every name, VAT ID and IBAN is fictitious (bank code 12345678, account numbers 1-5), but the
checksums are valid, so the IBAN and VAT checks treat them like real data.

Running the seed again resets the demo rows to these values (upsert on natural keys) and leaves
other rows alone. Run with `make seed` or `uv run invoiceguard-seed`.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.logging import configure_logging
from invoiceguard_api.models import PurchaseOrder, PurchaseOrderLine, Supplier, SupplierBankAccount
from invoiceguard_api.settings import get_settings

logger = logging.getLogger(__name__)

VERIFIED_BY = "Stammdatenpflege (Demo)"


@dataclass(frozen=True)
class SupplierSeed:
    name: str
    vat_id: str
    street: str
    postal_code: str
    city: str
    iban: str
    iban_verified_since: date


@dataclass(frozen=True)
class LineSeed:
    description: str
    quantity: Decimal
    unit_code: str
    unit_price: Decimal
    vat_rate: Decimal


@dataclass(frozen=True)
class OrderSeed:
    number: str
    supplier_vat_id: str
    order_date: date
    lines: tuple[LineSeed, ...]


def _line(description: str, quantity: str, unit: str, price: str, vat: str = "19") -> LineSeed:
    return LineSeed(description, Decimal(quantity), unit, Decimal(price), Decimal(vat))


SUPPLIERS = (
    SupplierSeed(
        "Muster Bürobedarf GmbH", "DE999000017", "Musterstraße 1", "10115", "Berlin",
        "DE17123456780000000001", date(2024, 3, 1),
    ),
    SupplierSeed(
        "Beispiel Logistik AG", "DE999000025", "Hafenweg 12", "20457", "Hamburg",
        "DE87123456780000000002", date(2023, 11, 15),
    ),
    SupplierSeed(
        "Demo IT-Service GmbH", "DE999000033", "Testallee 5", "80331", "München",
        "DE60123456780000000003", date(2025, 1, 10),
    ),
    SupplierSeed(
        "Fiktiv Gebäudereinigung GmbH", "DE999000041", "Probeweg 7", "50667", "Köln",
        "DE33123456780000000004", date(2024, 7, 22),
    ),
    SupplierSeed(
        "Exempel Druck & Medien GmbH", "DE999000050", "Platzhalterplatz 3", "70173", "Stuttgart",
        "DE06123456780000000005", date(2025, 6, 2),
    ),
)  # fmt: skip

ORDERS = (
    OrderSeed("PO-2026-0001", "DE999000017", date(2026, 9, 1), (
        _line("Kopierpapier A4, 80 g/m², Karton à 2.500 Blatt", "10", "C62", "24.90"),
        _line("Ordner DIN A4, 8 cm, blau", "50", "C62", "2.35"),
    )),
    OrderSeed("PO-2026-0002", "DE999000017", date(2026, 10, 6), (
        _line("Toner schwarz für Bürodrucker", "6", "C62", "79.00"),
    )),
    OrderSeed("PO-2026-0003", "DE999000025", date(2026, 9, 15), (
        _line("Palettentransport Hamburg nach München", "4", "C62", "185.00"),
        _line("Lagerung pro Palette und Monat", "12", "C62", "14.50"),
    )),
    OrderSeed("PO-2026-0004", "DE999000025", date(2026, 10, 20), (
        _line("Expresszustellung Ersatzteile", "1", "C62", "320.00"),
    )),
    OrderSeed("PO-2026-0005", "DE999000033", date(2026, 9, 3), (
        _line("Notebook 14 Zoll, 32 GB RAM", "3", "C62", "1249.00"),
        _line("Einrichtung und Inbetriebnahme", "6", "HUR", "95.00"),
    )),
    OrderSeed("PO-2026-0006", "DE999000033", date(2026, 10, 1), (
        _line("IT-Support-Pauschale Oktober 2026", "1", "MON", "890.00"),
    )),
    OrderSeed("PO-2026-0007", "DE999000041", date(2026, 9, 25), (
        _line("Unterhaltsreinigung Büroflächen Oktober 2026", "1", "MON", "1450.00"),
        _line("Glasreinigung Fensterfronten", "1", "C62", "380.00"),
    )),
    OrderSeed("PO-2026-0008", "DE999000041", date(2026, 10, 27), (
        _line("Unterhaltsreinigung Büroflächen November 2026", "1", "MON", "1450.00"),
    )),
    OrderSeed("PO-2026-0009", "DE999000050", date(2026, 9, 10), (
        _line("Visitenkarten, 4/4-farbig, 500 Stück", "8", "C62", "39.00"),
        _line("Imagebroschüre A4, 16 Seiten, Auflage 1.000", "1", "C62", "1180.00"),
    )),
    OrderSeed("PO-2026-0010", "DE999000050", date(2026, 10, 14), (
        _line("Fachbuch Rechnungswesen, gedruckt", "5", "C62", "49.90", vat="7"),
    )),
)  # fmt: skip


def _upsert_supplier(session: Session, seed: SupplierSeed) -> uuid.UUID:
    values = {
        "name": seed.name,
        "street": seed.street,
        "postal_code": seed.postal_code,
        "city": seed.city,
        "country_code": "DE",
    }
    statement = (
        insert(Supplier)
        .values(vat_id=seed.vat_id, **values)
        .on_conflict_do_update(index_elements=[Supplier.vat_id], set_=values)
        .returning(Supplier.id)
    )
    supplier_id: uuid.UUID = session.execute(statement).scalar_one()

    account = {"verified": True, "since": seed.iban_verified_since, "verified_by": VERIFIED_BY}
    session.execute(
        insert(SupplierBankAccount)
        .values(supplier_id=supplier_id, iban=seed.iban, **account)
        .on_conflict_do_update(
            index_elements=[SupplierBankAccount.supplier_id, SupplierBankAccount.iban],
            set_=account,
        )
    )
    return supplier_id


def _upsert_order(session: Session, seed: OrderSeed, supplier_id: uuid.UUID) -> None:
    values = {"supplier_id": supplier_id, "order_date": seed.order_date, "currency": "EUR"}
    statement = (
        insert(PurchaseOrder)
        .values(number=seed.number, **values)
        .on_conflict_do_update(index_elements=[PurchaseOrder.number], set_=values)
        .returning(PurchaseOrder.id)
    )
    order_id: uuid.UUID = session.execute(statement).scalar_one()

    for line_no, line in enumerate(seed.lines, start=1):
        line_values = {
            "description": line.description,
            "quantity": line.quantity,
            "unit_code": line.unit_code,
            "unit_price": line.unit_price,
            "vat_rate": line.vat_rate,
        }
        session.execute(
            insert(PurchaseOrderLine)
            .values(purchase_order_id=order_id, line_no=line_no, **line_values)
            .on_conflict_do_update(
                index_elements=[PurchaseOrderLine.purchase_order_id, PurchaseOrderLine.line_no],
                set_=line_values,
            )
        )
    session.execute(
        delete(PurchaseOrderLine).where(
            PurchaseOrderLine.purchase_order_id == order_id,
            PurchaseOrderLine.line_no > len(seed.lines),
        )
    )


def seed_demo_data(session: Session) -> None:
    supplier_ids = {seed.vat_id: _upsert_supplier(session, seed) for seed in SUPPLIERS}
    for order in ORDERS:
        _upsert_order(session, order, supplier_ids[order.supplier_vat_id])


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = make_engine(str(settings.database_url))
    try:
        with make_session_factory(engine).begin() as session:
            seed_demo_data(session)
    finally:
        engine.dispose()
    logger.info("Seeded %d suppliers and %d purchase orders", len(SUPPLIERS), len(ORDERS))
