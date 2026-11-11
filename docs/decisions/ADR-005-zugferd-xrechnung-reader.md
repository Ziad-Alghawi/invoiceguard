# ADR-005: Reading ZUGFeRD and XRechnung with factur-x and an own lxml parser

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

German e-invoices arrive in two forms:

- **XRechnung**, a pure XML file in one of two syntaxes: UBL 2.1 or UN/CEFACT CII.
- **ZUGFeRD / Factur-X**, a PDF/A-3 with a CII XML file embedded as an attachment, in profiles from
  MINIMUM to EXTENDED.

Under ADR-002 these are read by deterministic code, not an LLM. We need the EN 16931 business terms that
our checks use: invoice number (BT-1), issue date (BT-2), type (BT-3), currency (BT-5), seller name and
VAT ID (BT-27, BT-31), payee IBAN (BT-84), totals (BT-109, BT-110, BT-112, BT-115) and the invoice lines.
Correctness against official test files matters more than coverage of every optional field.

We ran a one-hour spike to compare two options:

- **(a)** `factur-x` to pull the embedded XML out of the PDF, plus our own `lxml` parser (XPath per
  business term) for both CII and UBL.
- **(b)** `drafthorse`, a typed object model for ZUGFeRD 2 / Factur-X CII.

During the spike we found that `factur-x` 7.0 (released 2026-09-29) added its own parser for UBL and
CII, `parse_ubl_cii_xml()`, so we measured it as well:

- **(c)** `factur-x` for both extraction and parsing.

### Spike

Samples (23 files): 12 XML files from the KoSIT XRechnung test suite (6 UBL, 6 CII, standard and
extension cases) and 11 PDFs from the ZUGFeRD corpus (MINIMUM, BASIC WL, BASIC, EN 16931, EXTENDED,
XRechnung-in-PDF, one ZUGFeRD 1.0 file). Versions: factur-x 7.9, drafthorse 2025.2.0, lxml 6.1.3,
Python 3.12, Windows 10, with the XSD check repeated in a Linux container.

A file counts as parsed if the call does not raise and returns invoice number and grand total. Where two
options parsed the same file, we compared BT-1, BT-5 and BT-112.

| | (a) factur-x + own lxml | (b) drafthorse | (c) factur-x parser |
| --- | --- | --- | --- |
| XML extracted from the 11 PDFs | 11/11 (factur-x) | not supported, needs factur-x or pypdf | 11/11 |
| KoSIT UBL (6) | **6/6** | 0/6: CII only | 6/6 |
| KoSIT CII (6) | **6/6** | 0/6 strict, 3/6 lenient | 6/6 |
| ZUGFeRD 2 / Factur-X PDFs (10) | **10/10** | 10/10 | 10/10 |
| ZUGFeRD 1.0 PDF (1) | 0/1 (by design) | 0/1 | 0/1 |
| **Total** | **22/23** | 10/23 (13/23 lenient) | 22/23 |
| Values agree with (a) | n/a | yes (formatting only) | yes, all 22 |
| Median parse time per file | 0.4 ms | 2.1 ms | 5.0 ms |
| Our code for the fields above | 65 lines (CII + UBL) | 14 lines mapping + a UBL parser + PDF extraction | 3 lines glue |
| Library size (Python, non-blank lines) | factur-x 7,651 | 2,437 | factur-x 7,651 |
| Licence | BSD (factur-x), BSD-3-Clause (lxml) | Apache-2.0 | BSD |
| Maintenance | factur-x: 70 releases, latest 2026-10-30, commits this week | 12 releases, latest 2025-09-15, last code change 2025-11 | parser API is six weeks old; its output dict changed within 7.x |

Why drafthorse failed on the official KoSIT CII files:

- It rejects XML comments in strict mode (the KoSIT files contain comments).
- It models `ClassCode` (BT-158, item classification) as a decimal, so an ISSN like `0721-880X` raises.
- It requires date containers to have exactly one child, so a comment inside a date element fails even
  in lenient mode.

Other findings:

- `factur-x`'s optional XSD check (`check_xsd=True`, the default for its parser) failed on all 16 CII
  files on Windows, because the bundled schemas did not resolve their imports there. The same check
  passed in a Linux container.
- Payee IBAN (BT-84) is often absent: KoSIT case 03.01a (UBL and CII) is a SEPA direct debit that
  carries only the buyer's account (BT-91), and 6 of the 11 PDFs have no payment account at all.
  Option (a) correctly returned no BT-84 for all of them.
- No library reads ZUGFeRD 1.0 (`CrossIndustryDocument`, superseded in 2019).

## Decision

Use **option (a)**: `factur-x` only to extract the embedded XML from PDFs, and **our own `lxml` parser**
for CII and UBL that maps each business term by an explicit XPath.

- XML is parsed with a hardened `lxml` parser: no entity resolution, no network access, no DTD loading.
- The parser returns typed values plus the source (`xml`) for each field, as the data model requires.
- Schema and business-rule validation is the job of the KoSIT validator service, not of the parser, so
  `factur-x`'s XSD check is not used.
- ZUGFeRD 1.0 and other unknown root elements are rejected with a clear "unsupported format" result
  and logged; they are not sent to the LLM path.
- `factur-x`'s own parser (option c) agreed with ours on every file, so the test suite will use it as a
  cross-check on the sample corpus (differential testing), not as the production parser.

## Alternatives

- **(b) drafthorse:** parsed none of the six official KoSIT CII files in strict mode, does not read UBL
  and cannot extract XML from a PDF, so it would still need the other two pieces. Its strength is
  generating ZUGFeRD, which we do not need.
- **(c) factur-x parser only:** least code and correct on all samples, but the API is six weeks old, its
  output structure changed between minor versions, its default XSD check fails on Windows, and its
  output dictionary hides which XPath a value came from. We would also give up an interview-relevant
  piece of code we can explain line by line. Revisit once the API has been stable for a few months.
- **Generated classes from the XSDs (xsdata):** full typing, but thousands of generated lines for the
  ~15 terms we use.

## Consequences

- We own about 65 lines of mapping code per field set and must extend it as checks need more terms.
  Every new term gets a test against the KoSIT and ZUGFeRD samples.
- `factur-x` is a dependency (with `pypdf`), used for one function. Its other features (XSD,
  Schematron, generation) are not used.
- The IBAN check must treat "no payee IBAN" (for example direct debit) as its own case, not as a
  mismatch with the registry.
- ZUGFeRD 1.0 invoices are not supported; the README says so.
