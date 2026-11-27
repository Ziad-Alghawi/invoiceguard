# ADR-029: Document viewer, click-to-highlight and the XRechnung visualization

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Until P1 the invoice page showed the extracted fields and a download link. To check a value the
reviewer opened the file in another program and searched it by eye. Phase P1 ("Review you can
trust", ADR-028) puts the document next to the fields, and a click on a field shows where its
value is printed. Three questions:

1. **How is a PDF shown?** In the browser, without a plug-in, from the existing file route.
2. **How do we find where a value is printed?** Values are stored normalised (EN 16931: ISO dates,
   decimals with a dot, IBANs without spaces), the PDF prints them for people ("1.234,50 €",
   "27.11.2026", "DE89 3704 ..."). ADR-002 says code decides: no model call for this.
3. **How is an XML invoice shown?** An XRechnung has no layout. KoSIT, which publishes the
   validator we already run (ADR-009), also publishes the official **xrechnung-visualization**:
   XSLT 2.0 stylesheets that turn UBL or CII into HTML. XSLT 2.0 needs Saxon (Java); lxml only does
   XSLT 1.0. The 4 GB demo server has about 1.25 GB free (PLAN section 8).

## Decision

**PDF viewer:** pdf.js (`pdfjs-dist` 6.5.438, pinned) in a client component draws each page on a
canvas from `/invoices/{id}/file`. Its optional Node canvas package is removed by a pnpm override;
it is not needed in the browser. Highlights are boxes in page fractions drawn over the canvas, so
they fit any width.

**Locations by code:** `GET /invoices/{id}/locations` reads the PDF's text layer with
**pdfminer.six** (pinned; a box per character; pypdf has no glyph positions) and builds one
regular expression per field from its stored value (`locations/matching.py`):

- amounts in German and English forms (`1.234,50`, `1,234.50`, `1 234,50`, trailing zeros as in
  `9,9000`), never inside a longer number;
- dates as `05.11.2026`, `5.11.26`, `05/11/2026`, `2026-11-05`, `5. November 2026`, `Nov 5, 2026`;
- IBANs and VAT IDs with or without spaces; names across line breaks; type and unit codes as their
  printed words (`380` → "Rechnung", `HUR` → "Std");
- invoice lines row by row: the line's item name (else net amount) first, then its other terms on
  the same printed row, so a quantity "1" is that row's and not a page number;
- a field the LLM extracted is found through its stored evidence: the printed text on the stored
  page, then the value inside it.

A field that matches nothing is **"not located"**; nothing is guessed, no model is called. At most
20 pages are read.

**XRechnung visualization in the validator container, not in the api and not in a new pod.** The
validator image gets the visualization release **v2026-10-13** (XRechnung 3.0.2), pinned by
version and SHA-256 like the validator, and a small Java launcher (`services/validator/src`). The
launcher compiles the stylesheets once with the Saxon that the validator jar already contains,
serves `POST /visualize?lang=de|en` on port 8082 with the JDK's HTTP server, and then starts the
official daemon unchanged on 8080 in the same JVM. Input is parsed with DTDs refused (no external
entities). Measured under the 1 GiB limit after five validations and visualizations each: 446 MiB
before, 529 MiB after (+83 MiB), first view 0.18 s, later views about 0.07 s.

**Static and sandboxed:** `GET /invoices/{id}/view` (XML invoices and PDFs with embedded XML)
takes the HTML, removes every `<script>` and `on*` attribute, shows all of the viewer's tab panels
one below the other (the tabs need the viewer's script), and answers with
`Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; img-src data:;
form-action 'none'; frame-ancestors 'self'; sandbox`. The web app shows it in
`<iframe sandbox="">`: no scripts, no same origin, no forms. Rendered pages are cached in the api
per file and language (16 entries).

**Highlighting the clicked BT row works:** the visualization gives every value the CSS class of
its business term (`class="BT-84 boxdaten wert"`), one element per invoice line for line terms. The
api marks the n-th element of the clicked term with `id="highlight"` and a style, and the iframe
opens at `#highlight`, so the browser scrolls to it without a script.

## Alternatives

- **The browser's own PDF viewer in an iframe:** no way to draw a highlight on it, and the file
  route answers with `Content-Disposition: attachment`.
- **Find values in the browser with pdf.js's text layer:** the same work in TypeScript, but not
  testable with the eval PDFs in Python, and the measured share would not be the shipped code's.
- **Ask the model for positions:** ADR-002; costs money and can be wrong in ways we cannot test.
- **Saxon in the api (`saxonche`):** a large native wheel and its memory in every api pod, next to
  a JVM that already runs Saxon.
- **A separate visualization pod or second JVM:** about 300 MiB more for a second JVM, which the
  4 GB server cannot spare.
- **Our own HTML for XML invoices:** the official visualization is what German AP staff and tax
  advisors know, covers every BT, and is maintained by KoSIT.

## Consequences

- The validator container now carries two jobs; when it is down, KoSIT checks are skipped
  (ADR-009) and the XML view answers 503, the rest of the page works.
- A visualization or validator upgrade changes the Dockerfile's pins together; the class names per
  BT are part of the visualization's HTML and are checked by a `kosit` test.
- Located means "a match was found", not "checked against hand-marked boxes"; the share is reported
  in `docs/results.md`. Rotated pages and PDFs without a text layer (scans) are not located.
- Every value on the page is a button, which the keyboard shortcuts of P1 build on.
