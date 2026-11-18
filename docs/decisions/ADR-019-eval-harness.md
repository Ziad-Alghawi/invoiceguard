# ADR-019: Evaluation harness with pinned datasets and recorded model replies

- **Status:** Accepted
- **Date:** 2026-11-18

## Context

PLAN section 3 says no claim without a number. Until R3 the extraction quality rests on one manual run of four
PDFs (ADR-010), fraud detection on unit tests, and the model's confidence has never been compared with its
errors: in R1 every confidence was 0.8 or higher, and a wrong order number got 0.9. R3 needs field accuracy,
fraud recall and precision, cost and latency, and later (R3-3) a CI gate that fails on a regression.

Forces:

- **Ground truth.** It has to come from somewhere other than the model: XML that travels with a PDF, or a
  generator that writes the truth together with the document.
- **Licences.** The public sample sets are on GitHub under Apache-2.0, but the ZUGFeRD corpus collects files
  from many vendors and FeRD, so the repo licence does not clearly cover every file. Committing copies would
  need a check per file.
- **Cost and repeatability.** Live model calls cost money (PLAN: ≤ €20 for six weeks), differ from run to
  run, and need a key that CI does not have on every PR. A gate on parser or check changes must be free and
  deterministic.
- **Same code as production.** An eval that re-implements the pipeline measures the re-implementation.

## Decision

A separate uv project, `packages/evals` (`invoiceguard-eval`), imports the api package and runs its real code:
the readers, `PdfExtractor`, and for decisions the whole app (`create_app` and `POST /invoices`) against a
throwaway PostgreSQL database seeded with the demo master data. Model calls go through a recording
`LLMClient`.

**Datasets** (`packages/evals/datasets/`):

| Set | Source | What it measures | Model calls |
| --- | --- | --- | --- |
| `kosit` | KoSIT `xrechnung-testsuite` business cases (UBL and CII) | Parser: each file is read; UBL and CII of the same case give the same terms | none |
| `corpus` | FeRD EN 16931 samples from the ZUGFeRD corpus (`XML-Rechnung/FX`) | Extraction: the model sees the PDF without its XML; the embedded XML is the truth | yes |
| `generated` | Own generator (reportlab): German layouts, several VAT rates, discounts, multi-page, conflicting printed values | Extraction, confidence, conflicts | yes |
| `fraud` | Generated from the same specs, as UBL XML and as PDF: changed IBAN, foreign IBAN, changed totals, duplicate number, unknown supplier, plus clean invoices | Decisions: which check flags it, whether the invoice is blocked | PDF only |

- **Downloads, not copies.** `sources.json` lists each corpus file with its repository, commit and SHA-256.
  `invoiceguard-eval fetch` downloads it into an ignored cache and refuses a file whose hash differs. Only our
  own generated files (and their ground truth) are committed.
- **Ground truth gaps.** A PDF can print a term its XML leaves out (the due date in R1). Such values are
  added in `sources.json` per file with a note, never inferred from the model's answer.
- **Recorded replies.** Every model request is keyed by a SHA-256 of model, system prompt, schema, reasoning
  effort, the user parts (files by hash) and the run number. `--live` calls the model and saves the reply
  with its tokens, cost and latency under `packages/evals/recordings/`; `--replay` (the default) answers
  from the recordings and stops with an error on a missing one. A changed prompt or schema changes the key,
  so replay cannot hide a prompt change: it needs a live run.
- **Spend cap.** A live run takes `--max-spend-usd` and stops before the next call once the replies so far
  cost that much. A failed call is never recorded.
- **Reports.** Each run writes a JSON report (git commit, settings, every case, every metric) under
  `packages/evals/reports/`; `invoiceguard-eval report` turns reports into `docs/results.md`.

**Metrics:**

- Field accuracy per EN 16931 term and per line term (exact match after normalising: decimals by value,
  dates, IBAN and VAT ID without spaces in upper case, text after NFKC and with whitespace collapsed).
- Document accuracy: invoice number, issue date, seller name, seller VAT ID, payee IBAN and the four totals
  all correct.
- Confidence: accuracy per confidence bucket, confident errors (wrong at or above the `low_confidence`
  threshold) and AUROC (how well confidence separates right from wrong fields).
- Conflict cases: the right value, the decoy, or neither; and whether the confidence fell below the threshold.
- Decisions: per fraud type, flagged (the expected check failed or warned), blocked, and precision of each
  check over the whole set including clean invoices.
- Cost, tokens and p50/p95 latency per invoice.

## Alternatives

- **Commit the corpus PDFs:** simplest to run, but the per-file licence is unclear (FeRD samples, vendor files).
- **Call the model in every CI run:** needs the key on every PR and money per push, and results drift
  between runs; replay plus a live run where the prompt changed gives both.
- **Black-box eval over HTTP against the Compose stack:** most realistic, but slow and needs the stack up for
  an extraction measurement that is a pure function; the in-process app is the same code without Docker.
- **promptfoo for the extraction set:** made for prompt-response pairs; our truth is structured invoice
  terms and check results, which a few typed Python functions compare better. It stays a candidate for the
  R3-3 attack suite.
- **HTML to PDF (WeasyPrint, Chromium) for the generator:** nicer templates, but system libraries on Windows or
  a browser download; reportlab is pure Python and writes byte-identical files in invariant mode.

## Consequences

- Extraction numbers are reproducible for free from the recordings; anyone can rerun `make eval`.
- Recordings hold the model's answers about the corpus files (extracted values), not the files.
- Recordings go stale when the prompt, schema or model changes: the next run must be live, which costs money
  and is the point.
- The fraud set measures the checks against the demo seed only; real master data has more cases.
- Generated layouts are cleaner than real invoices; scan-like variants (image noise, no text layer) are in
  the backlog.
- New dev-only dependency: `reportlab` (generator), in `packages/evals` only, not in the api image.
