import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from invoiceguard_api import seed
from invoiceguard_api.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    SupplierBankAccount,
)
from invoiceguard_api.settings import get_settings


def count(session: Session, model: type[object]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def iban_checksum_ok(iban: str) -> bool:
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(char, 36)) for char in rearranged)
    return int(digits) % 97 == 1


def german_vat_id_checksum_ok(vat_id: str) -> bool:
    """ISO 7064 MOD 11,10, as used for the German USt-IdNr."""
    product = 10
    for char in vat_id[2:10]:
        total = (int(char) + product) % 10 or 10
        product = (2 * total) % 11
    check = 11 - product
    return (0 if check == 10 else check) == int(vat_id[10])


def test_seed_data_has_valid_checksums() -> None:
    for supplier in seed.SUPPLIERS:
        assert iban_checksum_ok(supplier.iban), supplier.iban
        assert german_vat_id_checksum_ok(supplier.vat_id), supplier.vat_id


def test_checksum_helpers_reject_a_wrong_digit() -> None:
    assert not iban_checksum_ok("DE17123456780000000002")
    assert not german_vat_id_checksum_ok("DE999000018")


def test_seed_creates_demo_data(db_session: Session) -> None:
    seed.seed_demo_data(db_session)
    db_session.commit()

    assert count(db_session, Supplier) == 5
    assert count(db_session, SupplierBankAccount) == 5
    assert count(db_session, PurchaseOrder) == 10
    assert count(db_session, PurchaseOrderLine) == sum(len(o.lines) for o in seed.ORDERS)
    accounts = db_session.scalars(select(SupplierBankAccount)).all()
    assert all(account.verified and account.verified_by for account in accounts)
    suppliers = db_session.scalars(select(Supplier)).all()
    assert all(supplier.contact_email for supplier in suppliers)
    assert count(db_session, GoodsReceipt) == len(seed.RECEIPTS)
    assert count(db_session, GoodsReceiptLine) == sum(len(r.lines) for r in seed.RECEIPTS)


def test_goods_receipts_deliver_existing_order_lines() -> None:
    orders = {order.number: order for order in seed.ORDERS}
    for receipt in seed.RECEIPTS:
        order = orders[receipt.order_number]
        for line_no, quantity in receipt.lines:
            assert 1 <= line_no <= len(order.lines), receipt.number
            assert quantity <= order.lines[line_no - 1].quantity, receipt.number


def test_seed_twice_is_idempotent(db_session: Session) -> None:
    seed.seed_demo_data(db_session)
    db_session.commit()
    supplier_ids = set(db_session.scalars(select(Supplier.id)))

    seed.seed_demo_data(db_session)
    db_session.commit()

    assert set(db_session.scalars(select(Supplier.id))) == supplier_ids
    assert count(db_session, SupplierBankAccount) == 5
    assert count(db_session, PurchaseOrder) == 10
    assert count(db_session, PurchaseOrderLine) == sum(len(o.lines) for o in seed.ORDERS)
    assert count(db_session, GoodsReceiptLine) == sum(len(r.lines) for r in seed.RECEIPTS)


def test_seed_resets_changed_demo_rows(db_session: Session) -> None:
    seed.seed_demo_data(db_session)
    db_session.commit()
    supplier = db_session.scalars(select(Supplier).where(Supplier.vat_id == "DE999000017")).one()
    supplier.name = "Changed by a visitor"
    account = supplier.bank_accounts[0]
    account.verified = False
    order = db_session.scalars(
        select(PurchaseOrder).where(PurchaseOrder.number == "PO-2026-0002")
    ).one()
    order.lines.append(
        PurchaseOrderLine(
            line_no=99, description="extra", quantity=1, unit_code="C62", unit_price=1, vat_rate=19
        )
    )
    db_session.commit()

    seed.seed_demo_data(db_session)
    db_session.commit()
    db_session.expire_all()

    assert supplier.name == "Muster Bürobedarf GmbH"
    assert account.verified is True
    assert [line.line_no for line in order.lines] == [1]


def test_main_seeds_the_configured_database(
    engine: Engine, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        seed.main()
    finally:
        get_settings.cache_clear()

    with Session(engine) as session:
        assert count(session, Supplier) == 5
