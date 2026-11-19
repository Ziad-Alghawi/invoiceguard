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
- **Bookings: spend.** Two live embedding runs on 2026-11-19 recorded every text: 59 history wordings for the
  demo's packaged vectors ($0.0001) and 34 held-out wordings ($0.00007); everything since is replayed. One
  probe call before any code ($0.000003). Total for R3-4a: under $0.001.
- **Bookings: the vote was changed once, after the first run.** The first design summed the neighbours'
  cosine similarities; it missed all three phone lines for the internet account of the same supplier, an
  exact match included, because the model's similarities are compressed (unrelated item names still score
  about 0.8) and the more frequent account won. The app now weighs each neighbour by
  exp((score - best) / 0.05). That change was made after seeing this test set, so its number is optimistic;
  the "first design" column keeps the original. The same weighting made the text match worse (it follows
  spurious trigram overlaps): see the misses below the table, all on held-out wordings.
- **Bookings: what the set can and cannot show.** The catalogue and the truth are mine, each item's wordings are
  distinct, and the history is clean (one account per item). It shows that retrieval finds meaning where words
  differ (held-out wordings: 100 % by vector, 82 % by text match) and that the supplier's most frequent account
  is a poor guess (45 %); it does not measure a real ledger with inconsistent bookings.
- **R3-4b live run (2026-11-19): history, rulebook and the new agent prompt.** The prompt and the tool list
  changed, so every agent reply was recorded again; extractions, decisions and bookings replayed unchanged. Two
  live runs of the attack set cost $0.263 (132 calls, embeddings of the rulebook and the questions included) and
  $0.065 (the 10 forced history runs, 21 calls); the two recorded demo runs $0.024. R3-4b spent $0.352 in total of
  its $0.45 cap.
- **Poisoned history, delivered or not.** Left to itself the agent read the history in none of the 10 history
  cases (`get_invoice_history` 3 times in 54 runs, `search_similar_invoices` never): it went to the registry and
  the ERP, which answer a changed IBAN or a wrong total directly. So 0 of 10 were delivered and those 10 runs
  tested nothing. Each history case therefore also runs with `get_invoice_history` already called (eval only):
  10 of 10 delivered, 0 of 10 followed. Seven findings name the poisoned line as an instruction and say it was
  ignored, three leave it out. The scan would have kept 2 of the 10 texts out of the history at their own upload.
- **Rulebook.** By vector 90 % hit@3 in both languages; by full text 90 % for English and 50 % for German
  questions (the rulebook is English, the German stemmer only helps where a German term is written in). The
  misses are listed above. By vector two questions miss the top 3: r10 (hidden text addressed to an AI, rank 4)
  and r20 (no IBAN, direct debit, rank 6), whose answer is one bullet in a section about the IBAN check's
  warnings. The numbers rest on 20 questions written by the person who wrote the rulebook.
