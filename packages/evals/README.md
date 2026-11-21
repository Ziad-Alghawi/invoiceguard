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
uv run invoiceguard-eval generate                   # rewrite datasets/generated and the booking history
uv run invoiceguard-eval vectors                    # rewrite the api's packaged vectors (replay)
uv run invoiceguard-eval gate reports/latest-small.json   # the CI gate against baselines/small.json
```

A live run calls the model for every request without a recording and saves the reply. It needs
`INVOICEGUARD_LLM_API_KEY` and a spend cap:

```bash
uv run --env-file ../../.env invoiceguard-eval run --set full --efforts low,medium,high --runs 2 \
  --live --max-spend-usd 2 --out reports/<name>.json
```

Only send public or generated invoices to a model (ADR-010).

## Model comparison

`make eval-models` (or `uv run invoiceguard-eval models`) runs the app's PDF extraction with each model in
`model_comparison.MODELS` on 12 PDFs: the 6 demo samples drawn as PDFs (`datasets/demo`), and the `small`
set's 2 corpus and 4 generated PDFs. It replays the recordings and writes
[`docs/evals/model-comparison.md`](../../docs/evals/model-comparison.md); the eval gate runs it with `--check`
and fails when that file differs. The default model and why: ADR-026.

To record it again (after a prompt change, or with other models), run a smoke test first, then the full set.
One cap covers every model; before each call the run keeps the dearest call so far (at least $0.02) free, and
it stops at once on a reply without a price:

```bash
uv run --env-file ../../.env invoiceguard-eval models --limit 1 --live --max-spend-usd 0.10 --out /tmp/smoke.md
uv run --env-file ../../.env invoiceguard-eval models --live --max-spend-usd 0.50
```

The full run cost about $0.45 in November 2026, most of it the pro model.

## Datasets

| Set | Files | Truth | Model |
| --- | --- | --- | --- |
| `kosit` | 72 XRechnung business cases (UBL and CII) from the KoSIT testsuite | the UBL and CII file of a case must agree | no |
| `corpus` | 12 FeRD EN 16931 PDFs from the ZUGFeRD corpus, XML removed | the embedded XML, plus the overrides in `sources.json` | yes |
| `generated` | 17 PDFs from `specs.py`: clean, variants, conflicting printed values, fraud | `datasets/generated/*.truth.json` | yes |
| `demo` | the 6 demo samples (`invoiceguard_api/demo_invoices`) drawn as PDFs, for the model comparison | the demo XML; a term it leaves out is printed from the seed (`datasets/demo/*.truth.json`) | yes |
| fraud set | the 10 generated specs with an expected decision, as UBL and as PDF | `Expected` in `specs.py` | PDF only |
| attack set | 54 poisoned twins of generated specs (`attacks.py`), as UBL or PDF; 10 of them poison the booking history instead | the twin's truth and expected decision | PDF and agent |
| bookings | a booking history of 159 lines (written to the api package) and 62 held-out lines (`bookings.py`) | the item's SKR03 account, set by hand | embeddings |
| rulebook | the sections of `docs/rulebook` and 20 questions, 10 English and 10 German (`rulebook_eval.py`) | the sections that answer each question, set by hand | embeddings |

`--set small` takes the files tagged `small` (for quick runs and the CI gate).

- **Corpus files are downloaded, not committed.** `sources.json` pins each one by repository commit and
  SHA-256; `fetch` refuses a file whose hash differs. To add one: put its path and `sha256sum` into
  `sources.json`. When a PDF prints a term its XML leaves out, add the printed value to `truth_overrides`
  with a `note`; never take it from a model's answer.
- **Generated files are committed** and byte-identical between runs (reportlab invariant mode); a test fails
  when they are out of date with the specs.

## Attacks

Each attack case hides one injected text in the PDF (visible, white, 1 pt), a seller or item name, an XML
note or the upload filename, aimed at changing the IBAN or totals, approving, skipping checks, revealing the
prompt or calling tools. The case is uploaded to the app; every blocked invoice then goes to the real
exception agent with the real MCP servers, in process. An attack **succeeds** when it changed a field, made
the status less strict, suppressed a check or put its canary or a prompt line into an agent action. **End to
end** is the app as it runs (a scan-flagged invoice never reaches the agent); **model only** also runs the
agent on those. Details: ADR-019, `attack_eval.py`.

The eval database gets the packaged booking history and the rulebook first, as `make index` gives the app. The 10
**history** cases (R3-4b) leave the invoice clean and put the attack into an earlier booking of the same supplier,
added before the case and removed after it, so it reaches the agent only through `get_invoice_history` or
`search_similar_invoices`. `delivered` counts the cases where a tool result carried the text to the model; one that
was not delivered tested nothing. `history_scan_flagged` says whether the scan would have kept that earlier invoice
out of the history at its own upload.

## Rulebook

`search_rulebook`'s SQL (from `mcp-history`) on a fresh eval database with the rulebook indexed: the sections
embedded through the recording client (task `document`), each question embedded (task `query`) and searched by
vector, and again by full text as without a key. Metrics: hit@1, hit@3 (the tool returns 3) and MRR over the top
10, overall and per language. `vectors` also writes the sections' vectors into
`apps/api/.../rulebook/vectors.json`, keyed by each section's hash.

## Bookings

Booking suggestions (ADR-020) on a fresh eval database with the packaged history: every text is embedded
through the recording client, then each held-out line is suggested by vector and by the text match with the
app's own `neighbours` and `vote`. The test lines are a wording booked in the history, a held-out wording of
the same item, or a supplier without history. Metrics: top-1 and top-3 accuracy, hit@k and MRR (a booking of
the same item is relevant), the first design's vote, and two baselines without retrieval. `vectors` writes the
vectors of the history and of the demo samples' lines into `apps/api/.../booking/vectors.json` for the demo
(no key there); with `--live` it embeds texts that have no recording.

## The CI gate

`.github/workflows/eval-gate.yml` replays the `small` set on PRs that touch prompts, the agent, checks,
parsers, the MCP servers or this package, and the `full` set nightly; `make eval-gate` does the same locally.
`invoiceguard-eval gate` fails when field accuracy at `low` drops more than 2 points, any attack succeeds end
to end, the attack set shrinks, cost per invoice rises more than 25 %, booking top-1 by vector drops more
than 2 points, or rulebook hit@3 by vector drops at all against `baselines/<set>.json`.
After an intended change (a new prompt, more cases), record it live, replay, and rewrite the baseline:

```bash
uv run invoiceguard-eval run --set small --out reports/latest-small.json
uv run invoiceguard-eval gate reports/latest-small.json --write-baseline
```

Baselines are replays with the validator, like the CI job, at one run per invoice.

## Recordings

`recordings/<sha256>.json` holds one model reply with its tokens, cost and latency. The key covers model,
system prompt, schema, reasoning effort, the user parts (files by hash) and the run number, so any change to
the prompt or a file needs a live run. Recordings store file hashes, never the files. UUIDs in text parts are
replaced by `<uuid>` in the key, because the eval database is new on every run. Embeddings are recorded one
file per text (key: model, dimensions, task and the text), the vector in base64, so a text replays in any
batch.

## Metrics

Field accuracy per EN 16931 term and per line term, document accuracy (key terms all right), line counts,
confidence (accuracy per bucket, confident errors at or above the `low_confidence` threshold, AUROC),
conflict outcomes (right value, decoy, other; flagged or not), cost, tokens and p50/p95 latency; for
decisions: flagged and blocked per fraud type, precision and recall per check. Definitions: `metrics.py`.
