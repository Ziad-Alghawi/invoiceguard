# KoSIT validation: is the e-invoice valid

## What the check does

The `kosit` check sends the invoice XML to the KoSIT validator (Koordinierungsstelle für
IT-Standards), the reference validator for XRechnung. It checks the XML schema and the business rules
of EN 16931 and the German CIUS XRechnung (rules such as BR-CO-10 or BR-DE-1). Since 2025 German
businesses must be able to receive e-invoices (E-Rechnungspflicht, Wachstumschancengesetz); a PDF
without structured data is no longer an e-invoice.

## When it fails or warns

- **Failed:** the validator rejected the invoice; the evidence lists the rule codes. The invoice is
  `blocked`.
- **Warning:** valid, but with warnings, or another ZUGFeRD profile that the XRechnung
  configuration does not validate ("not validated").
- **Skipped:** the validator was not reachable or not configured. The invoice keeps a `skipped`
  result; there is no automatic re-run, so reopen it later.

## How to resolve

- Read the rule codes: a BR-DE rule usually means a missing German field (for example the buyer
  reference, Leitweg-ID, BT-10, for public buyers; or the seller contact, BT-41 to BT-43).
- An invalid e-invoice is not a proper invoice for input VAT (Vorsteuerabzug). Ask the supplier
  for a corrected, valid XRechnung or ZUGFeRD file; do not fix the XML yourself.
- If the content is right and only a technical rule fails, the reviewer may decide to accept it with
  a written reason; document it.
