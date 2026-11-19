# IBAN check: bank details against the registry

## What the check does

The `iban` check compares the payee IBAN on the invoice (BT-84, Bankverbindung des Zahlungsempfängers)
with the supplier's bank accounts in the registry (Kreditorenstammdaten). It first validates the IBAN's
format and check digits (ISO 13616, mod 97). The supplier is found by the seller's VAT ID
(USt-IdNr., BT-31).

## When it fails or warns

- **Failed, possible bank-detail fraud:** the IBAN is valid but is not a verified account of this
  supplier. This is the most common pattern of invoice fraud (Rechnungsbetrug, CEO fraud with changed
  bank details, "Kontoänderungsbetrug"). The invoice is `blocked`.
- **Failed, invalid IBAN:** wrong format or check digits. Often a typing error, sometimes a forgery.
- **Warning `no_payee_iban`:** the invoice names no IBAN, for example because it is paid by direct
  debit (Lastschrift, SEPA-Mandat). Check how it will be paid.
- **Warning `multiple_payee_ibans`:** the invoice names more than one IBAN; only the first is checked.
- **Warning, no verified account:** the supplier exists but has no verified bank account yet.

## How to resolve a changed IBAN

1. Do not pay to the new IBAN, and do not trust contact details printed on the invoice or in an
   email that announces the change.
2. Call the supplier on a phone number from the master data (Stammdaten), not from the invoice, and
   ask the accounts department to confirm the change.
3. Only after the confirmation, the master-data team adds the new account to the registry as
   verified, with the date and who verified it. The approver then reopens or approves the invoice.
4. If the supplier denies the change: reject the invoice, keep it as evidence, and report it to the
   security team.

An override of a blocked IBAN needs a written reason by a reviewer and confirmation by a second user
with the approver role (four eyes, Vier-Augen-Prinzip); see the review rules.

## Foreign IBANs

A German supplier with a foreign IBAN (for example a Lithuanian or Cypriot account) is not wrong in
itself, but it is a classic fraud signal. Treat it like a changed IBAN: verify by phone first.
