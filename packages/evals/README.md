# packages/evals

The evaluation harness (ADR-019): datasets, a PDF generator, metrics and the `invoiceguard-eval` CLI. It
imports the api package and runs its real code: the XML readers, the LLM `PdfExtractor`, and for decisions
the whole app (`POST /invoices` on a throwaway database). Results: [`docs/results.md`](../../docs/results.md).

## Run it

```bash
make dev        # PostgreSQL and the KoSIT validator
make eval       # fetch the pinned sources once, then replay every recorded model reply
```

`make eval` reads `INVOICEGUARD_EVAL_DATABASE_URL` (a database ending in `_eval`, dropped and recreated) and
`INVOICEGUARD_EVAL_VALIDATOR_URL` from the root `.env` (see `.env.example`). It calls no model and costs
nothing; a missing recording stops it with an error.

From this folder:

```bash
uv run invoiceguard-eval fetch                      # download corpus files, check their SHA-256
uv run invoiceguard-eval run --set small            # replay; report in reports/latest-small.json
uv run invoiceguard-eval run --set full --only parser,extraction
uv run invoiceguard-eval report reports/full-baseline.json   # write docs/results.md
uv run invoiceguard-eval generate                   # rewrite datasets/generated after a spec change
```

A live run calls the model for every request without a recording and saves the reply. It needs
`INVOICEGUARD_LLM_API_KEY` and a spend cap:

```bash
uv run --env-file ../../.env invoiceguard-eval run --set full --efforts low,medium,high --runs 2 \
  --live --max-spend-usd 2 --out reports/<name>.json
```

Only send public or generated invoices to a model (ADR-010).

## Datasets

| Set | Files | Truth | Model |
| --- | --- | --- | --- |
| `kosit` | 72 XRechnung business cases (UBL and CII) from the KoSIT testsuite | the UBL and CII file of a case must agree | no |
| `corpus` | 12 FeRD EN 16931 PDFs from the ZUGFeRD corpus, XML removed | the embedded XML, plus the overrides in `sources.json` | yes |
| `generated` | 17 PDFs from `specs.py`: clean, variants, conflicting printed values, fraud | `datasets/generated/*.truth.json` | yes |
| fraud set | the 10 generated specs with an expected decision, as UBL and as PDF | `Expected` in `specs.py` | PDF only |

`--set small` takes the files tagged `small` (for quick runs and, in R3-3, the CI gate).

- **Corpus files are downloaded, not committed.** `sources.json` pins each one by repository commit and
  SHA-256; `fetch` refuses a file whose hash differs. To add one: put its path and `sha256sum` into
  `sources.json`. When a PDF prints a term its XML leaves out, add the printed value to `truth_overrides`
  with a `note`; never take it from a model's answer.
- **Generated files are committed** and byte-identical between runs (reportlab invariant mode); a test fails
  when they are out of date with the specs.

## Recordings

`recordings/<sha256>.json` holds one model reply with its tokens, cost and latency. The key covers model,
system prompt, schema, reasoning effort, the user parts (files by hash) and the run number, so any change to
the prompt or a file needs a live run. Recordings store file hashes, never the files.

## Metrics

Field accuracy per EN 16931 term and per line term, document accuracy (key terms all right), line counts,
confidence (accuracy per bucket, confident errors at or above the `low_confidence` threshold, AUROC),
conflict outcomes (right value, decoy, other; flagged or not), cost, tokens and p50/p95 latency; for
decisions: flagged and blocked per fraud type, precision and recall per check. Definitions: `metrics.py`.
