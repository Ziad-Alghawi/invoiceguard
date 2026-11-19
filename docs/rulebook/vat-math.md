# VAT math: do the amounts add up

## What the check does

The `vat_math` check recomputes the invoice totals from its own numbers, in code, the way EN 16931
defines them: the sum of the line net amounts (BT-106), allowances and charges (BT-107, BT-108), the
net total (BT-109), the VAT per rate (Umsatzsteuer, Vorsteuer for us as buyer), the VAT total
(BT-110), the gross total (Bruttobetrag, BT-112) and the amount due (Zahlbetrag, BT-115).

## Thresholds

- Every rule may differ by at most **0.01** (one cent) for rounding.
- VAT per rate: taxable amount × rate, rounded to cents. German rates are 19 % (Regelsteuersatz) and
  7 % (ermäßigter Steuersatz); 0 % appears for reverse charge (Reverse-Charge, §13b UStG) and
  intra-community supplies (innergemeinschaftliche Lieferung).
- VAT category O ("not subject to VAT") has no rate; such lines are not taxed and the check accepts
  that.

## When it fails

A failed `vat_math` check blocks the invoice: the amounts do not add up, so the invoice is either
wrong or changed after it was written (changed totals are a fraud pattern). The evidence lists each
rule with the expected and the stated value.

## How to resolve

- Compare the stated values with the printed invoice. A wrong extraction from a PDF is possible: if
  the printed numbers add up, correct the field and reopen the invoice.
- If the invoice itself is wrong, ask the supplier for a corrected invoice (Rechnungskorrektur) or a
  credit note (Gutschrift). Do not change the amounts yourself: only the supplier may correct an
  invoice (§14 UStG, §31 UStDV).
- A wrong VAT rate is also a tax risk: input VAT (Vorsteuerabzug) is only deductible as correctly
  invoiced.
