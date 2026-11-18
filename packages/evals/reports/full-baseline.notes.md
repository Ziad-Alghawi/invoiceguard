- **Spend and the cut-off at `high`.** The live run cost $1.64 (141 calls; plus $0.03 for an earlier smoke run
  of the small set). During the second `high` repeat the Google project behind the key reached its billing spend
  cap: from then on every call failed with `PERMISSION_DENIED` ("Spend cap breached for project"), so 27 of 29
  invoices in that repeat failed. Compare the levels on **Completed**, not on **Fields**. Failed calls are not
  recorded; this report was rebuilt from the recordings with `--missing-as-failed`, which reproduces them.
- **Timeouts.** `medium` timed out twice and `high` four times at the client's 120 s limit
  (`INVOICEGUARD_LLM_TIMEOUT_SECONDS`); `low` never did (p95 23 s).
- **Thinking level.** On completed extractions all three levels get about 99 % of the document terms right;
  `low` costs $0.0058 per invoice against $0.0127 (`medium`) and $0.0221 (`high`), is 2 to 3 times faster and
  failed least. `low` stays the default (ADR-010).
- **Corrected truth.** Five corpus PDFs print a term their XML leaves out (four due dates, one payee IBAN in
  "überweisen Sie bitte auf folgende Bankverbindung"); the printed values are in `sources.json` with a note,
  checked against the PDF text. Unit codes H87 and C62 (both "piece") count as equal: the prompt asks for C62.
- **Remaining errors at `low`, checked against the PDFs.** Type codes 387 (rent) and 575 (insurance) came back
  as 380 at confidence 0.8; on the correction invoice the PDF prints "Gesamtbetrag der Abschläge 0,23" where the
  XML (and the VAT math) has -0.23; the insurance PDF puts a salutation in the buyer name ("Herrn\nMax
  Mustermann" in the XML) and prints instalment dates and a contract number that the model once took as due date
  and order reference. The item name "Stoßfänger" is broken in the corpus XML itself (encoding), so that
  line counts as wrong whatever the model returns. One run of the same invoice ended `failed` (an invalid
  decimal twice).
- **Confidence and the threshold (0.8 to 0.9).** Most errors sit at 0.8 to 0.9: in that bucket 4 of 6 fields were
  wrong, against 3 wrong of 1,110 fields at 1.0. Replayed from the same recordings at `low`, the `low_confidence`
  threshold (a field is flagged below it) gives:

  | Threshold | Wrong fields flagged | Wrong fields not flagged | Right fields flagged | Fields flagged |
  | --- | --- | --- | --- | --- |
  | 0.8 (before) | 1 of 9 | 8 | 2 of 1,197 | 3 |
  | 0.9 (now) | 5 of 9 | 4 | 4 of 1,197 | 9 |

  The default is now 0.9: four more errors reach a person for two more right fields flagged. The four that remain
  were all given 0.9 or more; `medium` and `high` have no errors below 0.9, so they gain nothing. The conflict
  cases never lowered the confidence, but the model picked the right value in all 10.
- **Parser.** The 9 UBL/CII pairs that differ are differences in the testsuite files (a placeholder order ID
  "Dummywert" in 7 UBL files, explicit 0.00 totals in one CII file, two different seller VAT IDs in 01.21a), not
  reader errors. The VAT check failed on 01.04a, a valid invoice with category O ("not subject to VAT"); that was a
  bug in `vat_math`, found by this eval and fixed afterwards: all 72 files now pass it.
- **What was rerun.** This report is a replay on commit `0745b8b` (the `vat_math` fix, threshold 0.9) of the
  parser and extraction parts. **The decisions (fraud set) were not rerun: those numbers are carried over from the
  run on commit `c94c320`** (threshold 0.8, KoSIT on). The XML variant has no confidences, so only the PDF
  variant can differ at 0.9 (a fraud PDF with a field at 0.8 to 0.9 would gain a `low_confidence` flag, and a clean
  one could be blocked); the next run with the eval database will confirm or correct these numbers.
