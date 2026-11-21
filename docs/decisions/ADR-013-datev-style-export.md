# ADR-013: DATEV-style booking export (EXTF Buchungsstapel), one row per invoice

- **Status:** Accepted, amended 2026-11-21 (issue #24)
- **Date:** 2026-11-14

## Context

The core story ends with approved invoices going to accounting (PLAN.md, R1). Most German companies and tax
advisors use DATEV, which imports bookings from a CSV file in its "DATEV-Format": an `EXTF` header row, a row of
column names, then one row per booking ("Buchungsstapel", header version 700, format version 13). The plan asks
for a documented, simplified DATEV-style export, not a certified interface. The real DATEV API is out of scope.

The export must never send an invoice to accounting twice, because a second import would book it twice. It must
be safe when two people click at the same moment, and it must be audited like every other action (ADR-012).

What we know per invoice (EN 16931 terms in `invoice_fields`): number (BT-1), date (BT-2), type (BT-3), currency
(BT-5), seller name (BT-27), gross total (BT-112) and per line the VAT rate (BT-152). We do not store the VAT
breakdown per rate (BG-23), suppliers have no creditor numbers yet, and booking suggestions (which account) come
in R3.

## Decision

`POST /exports/datev` (login required) puts every `approved` invoice that is not in an export yet into one new
file, links the invoices to the export (`invoices.datev_export_id`, migration 0006) and writes the audit events,
in one transaction. `GET /exports/datev/{id}/file` downloads the stored file; the web app's "Export to DATEV"
button on the queue calls both.

**File format** (from DATEV's public format description, `datev.py`):

- Windows-1252, CRLF, `;` between fields, text in double quotes (a quote inside is doubled), numbers unquoted.
  Characters Windows-1252 cannot hold become `?`; line breaks and tabs in text become spaces.
- Header: `EXTF`, 700, category 21, `Buchungsstapel`, version 13, created timestamp (UTC, with milliseconds),
  source `RE`, the reviewer's name, advisor and client number, fiscal year start, account length, the date range
  of the bookings, a description, booking type 1 (financial accounting), not fixed (`Festschreibung` 0, so the
  advisor can still correct the bookings), `EUR`, chart of accounts.
- All 125 columns of format version 13 are written (DATEV reads by position); we fill nine.

**Mapping, one booking row per invoice:**

| DATEV column | Value |
| --- | --- |
| Umsatz | Gross total (BT-112): two decimals rounded half up, decimal comma, no sign, no thousands separator |
| Soll/Haben-Kennzeichen | `H`: the Konto (creditor) is credited, the expense account debited. `S` for a credit note (BT-3 = 381) or a negative total (both: `H` again) |
| WKZ Umsatz | Currency (BT-5) |
| Konto | `INVOICEGUARD_DATEV_CREDITOR_ACCOUNT` (default 70000, one collective creditor) |
| Gegenkonto | `INVOICEGUARD_DATEV_EXPENSE_ACCOUNT` (default 4900, SKR03 "Sonstige betriebliche Aufwendungen", not an automatic tax account) |
| BU-Schlüssel | From `INVOICEGUARD_DATEV_TAX_KEYS` (default `{"19": "9", "7": "8"}`, SKR03 input VAT keys) when every line has a rate and all rates are equal; otherwise empty |
| Belegdatum | Issue date (BT-2) as DDMM; the year comes from the header |
| Belegfeld 1 | Invoice number (BT-1): at most 36 characters, only letters, digits and `$ % & * + - /`; any other character (space, dot, umlaut, ...) becomes `-` |
| Buchungstext | Seller name (BT-27), at most 60 characters |

All numbers (advisor, client, fiscal year start month, account length, chart, accounts, tax keys) are settings
with documented placeholder defaults (`.env.example`), never constants in code.

**One fiscal year per file.** Belegdatum has no year, so DATEV accepts one fiscal year per file. An export takes
the oldest fiscal year among the waiting invoices; the response says how many are `remaining`, and the web app
asks the reviewer to export again.

**Never twice.** The waiting invoices are selected `FOR UPDATE`: a second export at the same moment waits for the
first to commit, then PostgreSQL re-checks the row and finds it exported, so it gets `409` ("no approved invoices
are waiting"). The file is stored in `datev_exports` exactly as created. Exporting an invoice "again" means
downloading its export again: the same file, the same rows. There is no way to put an exported invoice into a new
file.

**Audit.** `datev_export.created` (invoice IDs, count, how many without a tax key, fiscal year) on the export,
`invoice.exported` on each invoice (it shows in the invoice history), and `datev_export.downloaded` on every
download.

## Alternatives

- **A booking row per VAT rate:** correct for mixed-rate invoices, but needs the VAT breakdown (BG-23) stored per
  invoice; computing it from the line amounts breaks with document allowances and charges. Later, with BG-23 in
  `invoice_fields`.
- **Gross amount without a BU key for every invoice** (the advisor splits the tax): simpler, but leaves the
  common single-rate case to manual work.
- **Refuse invoices without a single configured rate:** they would stay approved and never reach accounting. We
  export them without a BU key and report the count instead.
- **Re-export by resetting an invoice to "not exported":** gives a second file with the same booking, the double
  booking we want to prevent. Downloading the stored file covers a lost download.
- **An `exported` invoice status:** status means review outcome (ADR-012); export is a separate fact, so a
  nullable link to the export row, which also says which file holds the invoice.
- **UTF-8:** newer DATEV versions may read it, but Windows-1252 is the encoding the format description has named
  for years, and German umlauts fit in it.
- **The DATEV API or a certified format check:** out of scope for R1 (PLAN.md backlog: "real DATEV format").

## Consequences

- The file is DATEV-style, not certified. It follows the public format description and has a golden-file test,
  but it has not been imported into a real DATEV installation. A tax advisor must check the first import.
- Mixed or unknown VAT rates (and exempt lines without a rate) get no BU key: the advisor sets the tax in DATEV.
  The export response and the web app show how many.
- Every invoice books to one creditor and one expense account until suppliers get creditor numbers and R3 brings
  booking suggestions; no cost centre, due date, discount or document link is written.
- Non-EUR invoices carry their currency in `WKZ Umsatz` but no exchange rate (`Kurs`), which DATEV needs for
  foreign currency.
- Invoice numbers with characters outside the allowed set are changed (`RE 2026.1` becomes `RE-2026-1`), which the
  advisor sees when matching open items; the original stays in InvoiceGuard.
- Files are stored in the database (a few hundred bytes per invoice). Exports are final: nothing undoes one.

## Amendment (2026-11-21, issue #24): one row per chosen account and VAT rate

Since R3-4 (ADR-020) reviewers choose an SKR03 account per line when approving; the export now uses them.

- An invoice with chosen accounts gets **one booking row per (account, VAT rate)**: Gegenkonto is the chosen
  account, the BU key comes from the rate (`INVOICEGUARD_DATEV_TAX_KEYS`), Umsatz is the row's gross amount. Rows of
  one account are together, rates ascending, lines without a rate last. Soll/Haben is set per row, so a row of
  negative (discount) lines is booked the other way round.
- **Amounts from the lines, checked against the totals.** The net per row is the sum of its lines' net amounts
  (BT-131). The tax is computed per rate on the sum of that rate's lines, as EN 16931 computes BT-117, so the
  tax per rate matches the invoice's VAT breakdown; when one rate is split over several accounts, the rounding cent
  goes to the largest row of that rate (on a tie, the first account). The split is used only when there is no
  document allowance or charge (BT-107, BT-108), the line nets equal BT-109, the taxes equal BT-110 and the rows
  add up to BT-112. BG-23 does not need to be stored: these checks catch every case where the lines and the
  breakdown would disagree.
- **Otherwise one row, as before**: on the chosen account when every line has the same one, else on
  `INVOICEGUARD_DATEV_EXPENSE_ACCOUNT`. These invoices are counted as `without_account_split` in the export
  response, the `datev_export.created` audit event and the web app's message, and the advisor splits them in DATEV.
  Invoices approved without accounts keep the single row and are not counted.
- `without_tax_key` still counts invoices: those with at least one row without a BU key.

This replaces the first alternative above ("a booking row per VAT rate ... later, with BG-23"): computing from
the lines works once the result is checked against the document totals, and an invoice that fails the check
falls back instead of being booked wrongly.

Consequences: DATEV computes the tax from each row's gross amount and BU key, so a rate split over several
accounts can differ from BT-117 by a cent in DATEV; the advisor sees it on import. Document allowances and charges
are not spread over the accounts. Still no creditor numbers per supplier, cost centre or exchange rate.
