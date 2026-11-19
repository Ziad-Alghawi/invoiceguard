# Supplier known: is the seller in the master data

## What the check does

The `supplier_known` check looks up the seller's VAT ID (USt-IdNr., BT-31) in the supplier master data
(Kreditorenstammdaten). Without a known supplier there is no verified bank account and no purchase
order to compare with.

## When it warns

- **Warning, unknown supplier:** the VAT ID is not in the master data. New suppliers are normal, but
  fake invoices from invented companies are a fraud pattern too.
- **Warning, no VAT ID:** the invoice names no seller VAT ID. A German invoice above 250 euros must
  name the supplier's tax number or VAT ID (§14 Abs. 4 UStG); small-amount invoices
  (Kleinbetragsrechnung, up to 250 euros) need not.

## How to resolve

1. Check that a purchase order or a contract exists for the delivery: who ordered it?
2. Check the VAT ID: the German check digit (registry tool `check_vat_id`) and, for real use, the
   EU VIES service or the Bundeszentralamt für Steuern (qualified confirmation).
3. Ask the master-data team to create the supplier (Kreditor anlegen) with verified bank details,
   obtained from the supplier directly, not only from the invoice.
4. Then reopen the invoice so that the checks run again against the new master data.
