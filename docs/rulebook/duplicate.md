# Duplicate check: the same invoice twice

## What the check does

The `duplicate` check looks for invoices from the same seller (by VAT ID) that were received before.
Paying an invoice twice (Doppelzahlung) is one of the most frequent and most avoidable losses in
accounts payable.

## When it fails or warns

- **Failed:** the same invoice number (Rechnungsnummer, BT-1) from the same seller already exists.
  The invoice is `blocked`.
- **Warning, similar invoice:** same seller, same gross total (BT-112, within one cent) and an
  issue date (BT-2) within **7 days** of another invoice, but another number. This can be a resent
  invoice with a new number, or a regular monthly service with the same amount.
- Exact file copies are refused at upload already (same SHA-256), before any check runs.

## How to resolve

- Open the earlier invoice linked in the evidence and compare number, date, lines and amounts.
- If it is the same invoice (a reminder, Zahlungserinnerung or Mahnung, sent as a new document):
  reject the new one with the reason "duplicate of ...". Never approve both.
- If it is a correction (Rechnungskorrektur), the earlier invoice should be cancelled
  (Stornorechnung) by the supplier first; ask for it.
- A regular service with the same monthly amount (rent, Miete; maintenance, Wartung) is not a
  duplicate: check the service period (Leistungszeitraum) and approve.
