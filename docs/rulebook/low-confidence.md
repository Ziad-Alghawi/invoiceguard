# Low confidence: check the extracted fields

## What the check does

For a PDF without embedded XML, an LLM reads the fields from the page and reports a confidence per
field (0 to 1). The `low_confidence` check flags every field below the threshold, so a person
compares it with the PDF. XML invoices are parsed in code and never get this check.

## Thresholds

- The default threshold is **0.9** (`INVOICEGUARD_EXTRACTION_CONFIDENCE_THRESHOLD`).
- **Failed:** a critical field is below the threshold: the payee IBAN (BT-84), the net total
  (BT-109), the VAT total (BT-110), the gross total (BT-112) or the amount due (BT-115). The
  invoice is `blocked`.
- **Warning:** only other fields are below the threshold.

## What the confidence means

The confidence is self-reported by the model and not calibrated: measured, most wrong values still
had 0.8 or more. A high confidence is no proof; a low one is a reason to look.

## How to resolve

Open the PDF, compare each flagged field with the printed value, and correct it if needed. For a
blocked invoice, a reviewer approves with a written reason after the comparison (four eyes). If the
PDF is unreadable (a scan), ask the supplier for an e-invoice (XRechnung or ZUGFeRD).
