# ADR-026: gemini-3.8-flash stays the default extraction model

- **Status:** Accepted
- **Date:** 2026-11-21

## Context

The app sends a plain PDF to one model for extraction (ADR-010), through LiteLLM (ADR-004), at
reasoning effort `low` (R3-2, `docs/results.md`). The default is `gemini/gemini-3.8-flash`. R4-6 asks
whether another model would be the better default: more accurate, cheaper or faster.

The plan named Gemini, Mistral's EU free tier and a small Ollama model. That scope changed before the
work started, for two reasons:

- **Budget.** The Gemini credit for this work was about €1 to €2 (monthly cap €6), so the comparison
  had to stay small and capped. A second provider would have needed a second account, key and price
  check for one table.
- **The 4 GB demo server.** A local Ollama model cannot run next to the app on the demo (ADR-021,
  ADR-025: about 1.2 GB is free), so it could never be the demo's default. Measured only on the
  developer machine, its latency would not compare with an API model's.

So the comparison is three Gemini models on one key: the default, a cheaper one and a stronger one.

## Decision

**`gemini/gemini-3.8-flash` stays the default.** It was the only model with no wrong field, it costs
about the same as the cheaper model, and the pro model cost almost five times as much without being
more accurate.

The comparison (`make eval-models`, table in
[`docs/evals/model-comparison.md`](../evals/model-comparison.md)) runs the app's `PdfExtractor` on 12
PDFs: the 6 demo samples drawn as PDFs and the `small` set's 2 corpus and 4 generated PDFs. It uses
one run each at `low`, recorded on 2026-11-21:

| Model | Fields | Documents | Line terms | p50 / p95 s | Cost / invoice |
| --- | --- | --- | --- | --- | --- |
| `gemini-3.5-flash-lite` | 100.0 % | 100.0 % | 99.4 % | 4.4 / 7.9 | $0.0050 |
| `gemini-3.8-flash` (default) | 100.0 % | 100.0 % | 100.0 % | 8.6 / 15.0 | $0.0053 |
| `gemini-3.1-pro-preview` | 99.5 % | 100.0 % | 100.0 % | 11.5 / 20.0 | $0.0249 |

- **flash-lite is not cheaper in practice.** Its token price is lower, but it wrote more output
  tokens (thinking included), so an invoice cost $0.0050 against $0.0053. Its one error was a line's
  unit (`HUR` for `MON`) at a confidence above the 0.9 threshold. An error the reviewer is not warned
  about is the kind that matters here (ADR-010). On one invoice its first reply was rejected (the
  gross total and amount due were not valid decimals), and the retry got it right. Its real
  advantage is speed: about half the latency.
- **pro is not more accurate.** On `c01_order_note` it took the decoy order number printed in a note
  (`PO-2026-0030` for `PO-2026-0003`). It flagged that field with low confidence, so a reviewer would
  have seen it. It costs 4.7 times as much, is slower, and is a preview model with no stability
  promise.

The run cost $0.389 in total: $0.040 for a smoke run of one invoice per model, $0.348 for the rest,
and the default model's 6 small-set replies were already recorded. The run stops itself at $0.50
(`--max-spend-usd`): before each call it keeps the dearest call so far (at least $0.02) free, and it
stops at once on a reply without a price.

## Alternatives

- **Switch to flash-lite:** half the latency, but no cost saving on these invoices, and one
  confident error in 12 against none. Latency matters less than accuracy for an invoice that waits for
  review. Worth trying again on the full set if latency becomes a problem.
- **Switch to pro:** 4.7 times the cost and slower, with no accuracy gain on this set, and preview
  models can change or go away.
- **Mistral (EU) and Ollama as planned:** see Context. They would be the next comparison if
  EU-hosted inference becomes a requirement.
- **A bigger set or more runs:** the full set with 2 runs per model would cost about $3, over the
  budget. With 12 invoices, a single wrong field is within noise. This decision rests on "no model
  is clearly better", not on small differences.

## Consequences

- No code or settings change; `INVOICEGUARD_EXTRACTION_MODEL` can still name any model LiteLLM
  prices.
- The eval gate replays the comparison (`invoiceguard-eval models --check`) and fails when the table
  differs from its recordings. A change to the extraction prompt or schema therefore makes this check
  fail, like the eval gate's own replay. The comparison must then be recorded again: about $0.40 with
  all three models, or about $0.07 with the default model alone (`--models`). Either is a deliberate
  step, never a silent stale table.
- The 6 demo samples now also exist as PDFs (`packages/evals/datasets/demo`). A test keeps their
  truth equal to the demo XML.
- The sample is small: 12 invoices, all clean and machine-made, one of them with a conflicting value.
  Scans and real supplier layouts are not covered (status.md backlog).
