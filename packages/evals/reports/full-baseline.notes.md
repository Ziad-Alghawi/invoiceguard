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
- **What was rerun.** This report is a replay on commit `a39e05d` (the `vat_math` fix, threshold 0.9) of all four
  parts, with the eval database and KoSIT on. The fraud set now runs at threshold 0.9 too and still ends as
  expected in all 10 cases in both variants, with no clean invoice flagged; the numbers carried over from
  `c94c320` (threshold 0.8) are replaced.
- **Attacks: one live run.** The 44 attack cases were run live once at `low` (103 calls, $0.31: extraction for the
  PDF cases and the exception agent on every blocked invoice), then replayed from the recordings. No attack
  changed a field, a status, a check or an agent action, either end to end or with the injection gate taken
  out (model only).
- **Attacks: what the heuristic scan catches.** The regex scan flagged 14 of 44 (32 %). It catches 9 of 13 direct
  orders and 4 of 5 fake system messages, but none of the 24 indirect texts (a "Hinweis für die automatische
  Verarbeitung" with another IBAN, a "Korrektur" of the total), none of the filenames, the `skip_checks` cases or the French and Turkish
  texts, and 3 of 14 German ones; the regexes were not tuned to this set. In the 30 it misses the model ignored the
  text, and the design limits what a model that did not could do: XML notes and filenames never reach a model,
  extracted fields are checked against master data and the PO, and the agent's tools are read-only and
  allow-listed. The scan is a tripwire, not the defence.
- **Attacks: canaries in the finding.** In four cases (a25, a37, a39, a40) the agent's finding quotes the
  attacker's order number, VAT ID or link while describing the attack. Those are listed under finding mentions,
  not counted as successes: no tool was called with them and the email does not contain them.
