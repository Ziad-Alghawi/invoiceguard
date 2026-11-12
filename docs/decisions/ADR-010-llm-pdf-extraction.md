# ADR-010: LLM extraction of plain PDF invoices

- **Status:** Accepted
- **Date:** 2026-11-12

## Context

Many suppliers still send PDFs without embedded e-invoice XML: printed from an office program or scanned.
ADR-002 allows an LLM for exactly this case, with a fixed output schema, a confidence per field and the
same deterministic checks as XML invoices afterwards. ADR-004 puts every model call behind our own
`LLMClient` interface (LiteLLM inside) and requires a cost log in which an unknown price is an error.

Requirements for this step:

- The result must be the same `ParsedInvoice` the XML readers produce, so the checks run unchanged.
- Each field needs a confidence (0-1) and evidence (page and printed text), and low confidence on the
  values money moves on must stop the invoice from being `ready`.
- The PDF is untrusted: it can contain text written to manipulate the model (prompt injection).
- The budget is about €20 in total, the demo runs on the Gemini free tier, and every call is logged.

## Decision

**Send the PDF itself to a multimodal model** (Gemini Flash by default) and ask for JSON that follows a
strict schema; convert the reply into `ParsedInvoice` and run the normal checks.

- **Input:** the PDF goes base64-encoded as a file part of the user message. There is no local text
  extraction or OCR, so scans and layout-heavy invoices work, and no new PDF library is needed.
- **Default model:** `gemini/gemini-3.8-flash`, the newest stable Flash model in the price table of the
  pinned LiteLLM version (1.108.1), with PDF input and response-schema support. It is set in
  `INVOICEGUARD_EXTRACTION_MODEL`, so changing it is a config change (ADR-004).
- **Output schema** (`extraction/schema.py`): for each EN 16931 term we store, an object with `value`
  (a string, as printed and normalised: ISO dates, decimals with a dot, IBAN without spaces, or null),
  `confidence` (0-1) and `evidence` (`page`, `snippet` of at most 200 characters, or null).
  **Each invoice line and each VAT breakdown row has one confidence and one evidence for the whole row**,
  not one per term. A line has seven terms, so one confidence per term would multiply the output tokens
  (and cost and latency) for little gain: a reviewer checks a line as a whole. In `invoice_fields`
  every term of a line carries its line's confidence and evidence.
- **Validation:** the reply is parsed by the schema models (`extra="forbid"`) and then by `ParsedInvoice`,
  which types the values (a date that is no date, a missing total, `1.234,50` all fail). An invalid reply
  gets **one retry** that tells the model where and why (field path and message, never the input value);
  a second invalid reply ends in `failed` with that reason.
- **Confidence policy:** a threshold from `INVOICEGUARD_EXTRACTION_CONFIDENCE_THRESHOLD` (default 0.8).
  The new `low_confidence` check lists every field below it: a `warning` in general, but **`failed`
  (invoice `blocked`) when the payee IBAN (BT-84) or a total (BT-109, BT-110, BT-112, BT-115) is below it**,
  so such an invoice is never `ready` without a human looking. XML invoices get no `low_confidence` result.
- **Prompt injection:** the system prompt is a constant that says the document is untrusted data and must
  never be followed as instructions. The PDF goes only into the user message, between labelled markers
  (`<<<UNTRUSTED_DOCUMENT>>>`). Whatever the document makes the model say, the result can only be values
  in the schema fields, and those go through the deterministic checks: an injected IBAN is blocked by the
  registry check like any changed IBAN. Rejection reasons never repeat document text, so it does not
  reach the retry prompt or the UI. Detecting injection attempts as security events is part of R2.
- **Cost log:** every call, also failed and invalid ones, is a row in `model_calls` (invoice, purpose,
  model, status, tokens, cost in USD, latency, error, start time). The rows are committed before the
  checks run, so the cost stays logged when a later step fails. A model without a price in LiteLLM's
  table ends the extraction as `failed` (`price_unknown`), never as zero cost. LiteLLM reads its
  bundled price table (`LITELLM_LOCAL_MODEL_COST_MAP=True`) instead of downloading the newest one at
  import, so costs come from the reviewed, pinned version. The same module sets `LITELLM_MODE=PRODUCTION`:
  in its default mode, importing LiteLLM loads the nearest `.env` file into the process environment, which
  put a developer's real API key into the test settings. Per-invoice and per-day cost caps follow with the
  agent in R2.
- **Thinking level:** Gemini 3 models think before they answer, and LiteLLM counts thinking tokens as
  output tokens, billed at the output price. In the manual run at the model's default level (4 PDFs, see
  `docs/status.md`) the output was 1.8 to 2.2 times the input (2,700 to 4,500 tokens), while a reply of
  this schema is roughly 1,000 to 2,000 tokens; output was about 90 % of the cost ($0.011 to $0.018 per
  invoice) and drives the latency (19 to 27 s). Extraction is mostly transcription, so
  `INVOICEGUARD_EXTRACTION_REASONING_EFFORT` (default **`low`**) is passed as LiteLLM's `reasoning_effort`,
  which LiteLLM sends as Gemini's `thinkingLevel`. **Trade-off:** less thinking should cut cost and latency,
  at the risk of more slips where an invoice needs reasoning to read: allowances and charges, several VAT
  rates, an amount due below the gross total (prepayment), totals on a later page than the lines. The
  deterministic checks (`vat_math`, `iban`, `low_confidence`, `po_match`) catch the slips that move money,
  and the model's confidence stays self-reported either way. `minimal` would be lower still, but the
  pinned price table marks Gemini 3.8 Flash as not supporting it (LiteLLM then sends `low`), and Gemini 3
  cannot turn thinking off. Measured on the same 4 PDFs, `low` halved cost and latency ($0.0141 to
  $0.0067 and 22.8 to 10.3 s per invoice) and misread 1 of 72 terms: of two different order numbers
  printed on one PDF it took the one in a free-text note, with confidence 0.9; IBANs and totals stayed
  correct. Going back to more thinking is a config change; R3 measures field accuracy per level on the
  eval set and sets the default from data.
- **Flow (ADR-007):** the same background task that finds no XML moves the invoice to
  `awaiting_extraction` and then claims it again (`awaiting_extraction → processing`, a conditional
  update), extracts, stores the fields with `source=llm`, runs the checks and ends in `ready`, `blocked`
  or `failed`. The KoSIT check is `skipped` because there is no XML. Without an API key the invoice stays
  in `awaiting_extraction` with a reason; on the next start with a key, startup recovery extracts it.
- **Data protection:** on the Gemini free tier, Google may use prompts and responses to improve its
  products, and human reviewers may read them. Therefore **only made-up or public sample invoices are
  sent to it** (the demo seed, the ZUGFeRD corpus). Real invoices need a paid tier or the EU-hosted
  endpoint from ADR-004.

## Alternatives

- **Extract the text locally (pypdf or pdfplumber) and send text:** fewer input tokens and works with
  text-only models, but fails on scans, loses the layout that tells which amount is the total, and needs
  a PDF text library. Stays the likely route for local Ollama models in R4.
- **OCR plus templates or rules, no LLM:** reliable for known layouts, breaks on every new supplier
  layout; ADR-002 rejected it.
- **One confidence per line term:** the most detail, at several times the output tokens per line.
- **Tool calling instead of a response schema:** the same result with more variance between providers.
- **Default thinking level:** the most careful reading (no misread on the 4 sample PDFs), at about twice
  the cost and latency of `low`; kept as a setting (`high`) instead of the default.
- **Token log-probabilities as confidence:** not offered uniformly across providers and LiteLLM; the
  model's own confidence is simpler, with its limits stated below.

## Consequences

- Plain PDFs reach `ready` or `blocked` with the same checks as e-invoices, and every extracted value
  shows where on the page it came from.
- The model's confidence is self-reported, not calibrated. It decides what a human must look at, not
  what is correct; the deterministic checks stay the real defence. R3 measures field accuracy and how
  well confidence predicts errors.
- The schema allows missing values where `ParsedInvoice` does not (for example a missing gross total),
  so such a PDF ends in `failed` after the retry instead of in review. A partial-extraction review is a
  possible later step.
- Free-tier quotas are low and change without notice (community reports of 20 requests per day for
  Gemini 3.8 Flash); a used-up quota ends the invoice in `failed` with a clear reason, and there is no
  automatic retry yet (ADR-007).
- The PDF is sent inline (base64), which is fine below the 10 MiB upload limit; larger files would need
  the provider's file upload API.
- Models that cannot read PDFs (most local Ollama models) need a PDF-to-image or text step before they
  can be used here.
