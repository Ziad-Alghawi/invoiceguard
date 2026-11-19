# PO match: invoice against purchase order

## What the check does

The `po_match` check compares the invoice with the purchase order (Bestellung) named in its order
reference (BT-13): supplier, currency, and line by line the unit, unit price (BT-146) and quantity
(BT-129), then the net total. Lines are paired by position. Goods receipts (Wareneingang,
Lieferschein) show what was actually delivered; together with the order this is the three-way match.

## Thresholds

- Unit price: more than **0.01** above the order fails; below the order is a warning.
- Quantity: any quantity above the order fails; below the order is a warning (partial delivery,
  Teillieferung).
- Net total above the order by more than 0.01 fails; below it warns.
- A line that is not on the order, another unit, another currency, or an order of another supplier
  fails.
- An order number that is not in the order data is a warning.

## How to resolve a price above the order

1. Look at the order and its goods receipts: was the quantity delivered, at which price was it
   ordered?
2. If the price was agreed later (a price increase, Preiserhöhung), the buyer who placed the order
   confirms it in writing and the order is updated; then reopen the invoice.
3. Otherwise ask the supplier for a credit note (Gutschrift) or a corrected invoice
   (Rechnungskorrektur) at the ordered price.

## How to resolve a partial delivery

If less was invoiced than ordered, check the goods receipts. Approve what was delivered and invoiced;
the rest of the order stays open. Never pay for quantities without a goods receipt.

## Lines in another order

Pairing by position means reordered or split lines show false differences. Compare item names
before asking the supplier.
